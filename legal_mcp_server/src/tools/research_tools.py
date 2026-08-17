"""Case-law research and citation-verification tools for the Legal MCP Server.

These tools are the server's answer to the single biggest failure mode in
AI-assisted legal work: a citation that reads perfectly and does not exist.
Every authority surfaced here comes from a real lookup against a real corpus,
and :func:`verify_all_citations` exists so that any prose - including prose the
model wrote itself - can be swept before it reaches the user.

The default corpus is the free AWS Open Data release of Indian Supreme Court
and High Court judgments (CC-BY-4.0): no API key, no per-query cost.
"""

from typing import Any, Dict, List, Optional

from legal_mcp_server.src.domain import citations as cit
from legal_mcp_server.src.settings import settings
from legal_mcp_server.src.sources import case_law
from legal_mcp_server.src.sources.case_law import SourceUnavailable
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()

VERDICT_VERIFIED = "VERIFIED"
VERDICT_NOT_FOUND = "NOT_FOUND"
VERDICT_AMBIGUOUS = "AMBIGUOUS"
VERDICT_UNCHECKED = "UNCHECKED"

# Confidence scores for each verdict type
CONFIDENCE_SCORES = {
    VERDICT_VERIFIED: 1.0,
    VERDICT_NOT_FOUND: 0.2,
    VERDICT_AMBIGUOUS: 0.5,
    VERDICT_UNCHECKED: 0.0,
}


def _unavailable(operation: str, error: Exception) -> Dict[str, Any]:
    """Build the standard 'could not consult the source' response.

    This is deliberately distinct from an empty result. An empty result means
    no authority was found; this means the search never happened, and the model
    must not fill the gap from memory.
    """
    return {
        "status": "unavailable",
        "operation": operation,
        "error": str(error),
        "message": (
            "The case-law source could not be consulted, so this is NOT a finding "
            "that no authority exists. Tell the user the search could not be run "
            "and do not substitute recalled case law."
        ),
    }


async def search_case_law(
    query: str,
    court: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    judge: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
) -> Dict[str, Any]:
    """Search Indian case law in the free open-access judgment corpus.

    TOOL_NAME=search_case_law
    DISPLAY_NAME=Indian Case Law Search
    USECASE=Find Indian judgments on a legal proposition, from the Supreme Court or any High Court, at no cost
    INSTRUCTIONS=1. Check the corpus covers what you need with case_law_status, 2. Search by party name, case title terms or judge - this indexes case metadata, not full judgment text, 3. Open promising results with get_judgment to read the actual reasoning, 4. Never cite a result you have not opened
    INPUT_DESCRIPTION=query (string, required): search terms; all terms must appear. court (string, optional): "Supreme Court", "Bombay High Court", "Delhi", etc. from_date/to_date (string, optional): YYYY-MM-DD bounds. judge (string, optional): judge name fragment. limit (int, optional, default 20): maximum results.
    OUTPUT_DESCRIPTION=Dictionary with status, results (doc_id, title, court, date, citation, neutral_citation, judge, disposal, url), the backend used, and a scope note stating what was actually searched
    EXAMPLES=search_case_law("cheque dishonour", court="Bombay High Court"), search_case_law("Vijay Singh Bihar", court="Supreme Court")
    PREREQUISITES=Run sync_case_law once for the courts and years you need. No API key and no per-query cost on the default open-data backend.
    RELATED_TOOLS=sync_case_law to widen coverage, get_judgment to read a result, search_within_judgment to locate a passage, verify_citation to confirm a citation

    I/O-bound operation - uses async def for external data access.

    Args:
        query: Search terms expressing the legal proposition or party names.
        court: Optional court filter.
        from_date: Optional lower date bound, YYYY-MM-DD.
        to_date: Optional upper date bound, YYYY-MM-DD.
        judge: Optional judge filter.
        limit: Maximum results to return.
        page: Zero-based results page (paid backend only).

    Returns:
        Dict with the ranked results and search metadata.
    """
    try:
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")

        payload = await case_law.search(
            query=query.strip(),
            court=court,
            from_date=from_date,
            to_date=to_date,
            judge=judge,
            limit=limit,
            page=max(0, page),
        )

        results = payload["results"]
        logger.info(f"Case law search returned {len(results)} results for: {query}")

        response = {
            "status": "success",
            "operation": "search_case_law",
            "results": results,
            "result_count": len(results),
            "total_found": payload.get("found"),
            "query_sent": payload.get("query", query),
            "backend": payload["backend"],
            "cost": payload["cost"],
            "message": (
                f"Found {len(results)} judgments. Open the relevant ones with "
                "get_judgment before relying on them; metadata snippets are not a "
                "sufficient basis for a citation."
            ),
        }
        for key in ("attribution", "scope_note", "spend", "page"):
            if key in payload:
                response[key] = payload[key]
        return response

    except SourceUnavailable as e:
        logger.warning(f"Case law search unavailable: {e}")
        return _unavailable("search_case_law", e)
    except Exception as e:
        logger.error(f"Error in search_case_law: {e}")
        return {
            "status": "error",
            "operation": "search_case_law",
            "error": str(e),
            "message": "Failed to search case law",
        }


async def get_judgment(
    doc_id: str, include_citations: bool = True, max_chars: int = 0
) -> Dict[str, Any]:
    """Retrieve the full text of a judgment from the official PDF.

    TOOL_NAME=get_judgment
    DISPLAY_NAME=Full Judgment Retrieval
    USECASE=Read a complete judgment before relying on it
    INSTRUCTIONS=1. Obtain a doc_id from search_case_law, 2. Call this tool, 3. Read the holding rather than the headnote, 4. Quote only what the text actually says
    INPUT_DESCRIPTION=doc_id (string, required): identifier from search_case_law, e.g. "sc:2024:2024_10_108_125" or "hc:27_1:hcbgoa:2024:HCBM050003922024_1_2024-04-25.pdf". include_citations (bool, optional): reserved. max_chars (int, optional, default 0 = whole judgment): truncate very long judgments.
    OUTPUT_DESCRIPTION=Dictionary with status, doc_id, title, court, date, bench, full text, citation, neutral_citation, disposal, cnr, url and attribution
    EXAMPLES=get_judgment("sc:2024:2024_10_108_125"), get_judgment("sc:2024:2024_10_108_125", max_chars=20000)
    PREREQUISITES=The judgment PDF is downloaded once from public S3 and cached locally. Free on the default open-data backend.
    RELATED_TOOLS=search_within_judgment to jump to one passage; find_related_proceedings for connected matters

    I/O-bound operation - uses async def for external data access.

    Args:
        doc_id: Judgment identifier returned by search_case_law.
        include_citations: Reserved; the open corpus has no citation graph.
        max_chars: Optional truncation limit; 0 returns the whole judgment.

    Returns:
        Dict with the judgment text and metadata.
    """
    try:
        if not doc_id or not str(doc_id).strip():
            raise ValueError("doc_id must be a non-empty identifier")

        result = await case_law.get_judgment(str(doc_id).strip())

        truncated = False
        if max_chars and len(result.get("text", "")) > max_chars:
            result["text"] = result["text"][:max_chars]
            truncated = True

        return {
            "status": "success",
            "operation": "get_judgment",
            **result,
            "truncated": truncated,
            "message": (
                f"Retrieved judgment {doc_id}."
                + (
                    " Text was truncated; re-fetch with a higher max_chars if the "
                    "holding is not in the portion returned."
                    if truncated
                    else ""
                )
            ),
        }

    except SourceUnavailable as e:
        return _unavailable("get_judgment", e)
    except Exception as e:
        logger.error(f"Error in get_judgment: {e}")
        return {
            "status": "error",
            "operation": "get_judgment",
            "error": str(e),
            "message": "Failed to retrieve judgment",
        }


async def search_within_judgment(doc_id: str, query: str) -> Dict[str, Any]:
    """Find the passages inside one judgment that deal with a specific point.

    TOOL_NAME=search_within_judgment
    DISPLAY_NAME=Judgment Passage Finder
    USECASE=Locate what a specific judgment says about a specific point without reading the whole thing
    INSTRUCTIONS=1. Obtain a doc_id from search_case_law, 2. Pass the point you need, 3. Read the surrounding passage, not just the matched phrase
    INPUT_DESCRIPTION=doc_id (string, required): identifier from search_case_law. query (string, required): the point to locate, e.g. "territorial jurisdiction" or "burden of proof"
    OUTPUT_DESCRIPTION=Dictionary with status, doc_id, title, matching passages with character offsets, url and match count
    EXAMPLES=search_within_judgment("sc:2024:2024_10_108_125", "burden of proof"), search_within_judgment("hc:27_1:hcbgoa:2024:HCBM050003922024_1_2024-04-25.pdf", "jurisdiction")
    PREREQUISITES=The judgment PDF is cached after the first fetch, so repeat searches are offline and free
    RELATED_TOOLS=get_judgment for the full reasoning; search_case_law to find the doc_id

    I/O-bound operation - uses async def for external data access.

    Args:
        doc_id: Judgment identifier returned by search_case_law.
        query: The proposition or term to locate within the judgment.

    Returns:
        Dict with the matching passages.
    """
    try:
        if not doc_id or not str(doc_id).strip():
            raise ValueError("doc_id must be a non-empty identifier")
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")

        payload = await case_law.search_within_judgment(
            str(doc_id).strip(), query.strip()
        )

        return {
            "status": "success",
            "operation": "search_within_judgment",
            **payload,
            "message": (
                f"Found {payload['match_count']} matching passages."
                if payload["match_count"]
                else "No passage in this judgment matched. The judgment may not "
                "address the point, or the wording may differ - try a synonym "
                "before concluding it is silent."
            ),
        }

    except SourceUnavailable as e:
        return _unavailable("search_within_judgment", e)
    except Exception as e:
        logger.error(f"Error in search_within_judgment: {e}")
        return {
            "status": "error",
            "operation": "search_within_judgment",
            "error": str(e),
            "message": "Failed to search within judgment",
        }


async def find_related_proceedings(doc_id: str, limit: int = 20) -> Dict[str, Any]:
    """Find other proceedings involving the same parties as a judgment.

    TOOL_NAME=find_related_proceedings
    DISPLAY_NAME=Related Proceedings Finder
    USECASE=Surface appeals, reviews and connected matters involving the same parties
    INSTRUCTIONS=1. Obtain a doc_id, 2. Call this tool, 3. Read the is_citator flag - when it is False this is a party-name match and tells you NOTHING about whether the judgment is still good law, 4. Say so plainly when reporting
    INPUT_DESCRIPTION=doc_id (string, required): identifier from search_case_law. limit (int, optional, default 20): maximum results.
    OUTPUT_DESCRIPTION=Dictionary with status, results, is_citator flag, the party terms matched on, and an explicit note on what the list does and does not establish
    EXAMPLES=find_related_proceedings("sc:2024:2024_10_108_125"), find_related_proceedings("sc:2024:2024_10_108_125", limit=50)
    PREREQUISITES=Free on the open-data backend. The open corpus has no citation graph, so this is NOT a citator.
    RELATED_TOOLS=search_case_law to look for later authority on the point directly; get_judgment to read a result

    I/O-bound operation - uses async def for external data access.

    Args:
        doc_id: Judgment identifier returned by search_case_law.
        limit: Maximum number of related proceedings to return.

    Returns:
        Dict with related proceedings and a caveat about their meaning.
    """
    try:
        if not doc_id or not str(doc_id).strip():
            raise ValueError("doc_id must be a non-empty identifier")

        bounded = max(1, min(limit, 100))
        payload = await case_law.find_related_proceedings(
            str(doc_id).strip(), limit=bounded
        )

        caution = (
            "A citing case may follow, distinguish, doubt or overrule this "
            "judgment - the list alone does not tell you which."
            if payload.get("is_citator")
            else "This is a party-name match, NOT a citator. It does not establish "
            "whether this judgment is still good law. To test that, search for "
            "later authority on the same point and check any subsequent Supreme "
            "Court or larger-bench decision."
        )

        return {
            "status": "success",
            "operation": "find_related_proceedings",
            "doc_id": doc_id,
            **payload,
            "result_count": len(payload.get("results", [])),
            "message": caution,
        }

    except SourceUnavailable as e:
        return _unavailable("find_related_proceedings", e)
    except Exception as e:
        logger.error(f"Error in find_related_proceedings: {e}")
        return {
            "status": "error",
            "operation": "find_related_proceedings",
            "error": str(e),
            "message": "Failed to find related proceedings",
        }


async def _verify_case_citation(citation: cit.Citation) -> Dict[str, Any]:
    """Resolve one case citation against the configured case-law corpus.

    Supreme Court citations are checked against the dataset's official S.C.R.
    and neutral-citation fields, which is an exact match rather than a text
    search. Anything else falls back to searching case titles, which is weaker
    and is reported as such.
    """
    exact = await case_law.find_by_citation(citation.normalized)
    results = exact.get("results", [])

    if results and exact.get("exact"):
        if len(results) == 1:
            return {
                "verdict": VERDICT_VERIFIED,
                "matches": results,
                "note": (
                    "Citation matches the official citation field for this "
                    f"judgment in the {exact['backend']} corpus."
                ),
            }
        return {
            "verdict": VERDICT_AMBIGUOUS,
            "matches": results[:5],
            "note": (
                "More than one judgment carries this citation. Confirm which is "
                "intended before relying on it."
            ),
        }

    # Fall back to searching party names and case titles.
    query = citation.case_name or citation.search_query() or citation.normalized
    payload = await case_law.search(query=query, limit=10)
    candidates = payload.get("results", [])

    if not candidates:
        synced = ""
        if payload.get("backend") == "open_data":
            synced = (
                " Note this only searched the courts and years synced locally - "
                "run case_law_status to see coverage, and sync_case_law to widen "
                "it. A citation outside the synced range is unverified, not false."
            )
        return {
            "verdict": VERDICT_NOT_FOUND,
            "matches": [],
            "note": (
                "No judgment in the corpus matches this citation. Treat it as "
                "unverified and do not present it as authority." + synced
            ),
        }

    needle = citation.normalized.lower()
    strong = [
        r
        for r in candidates
        if needle in (r.get("title") or "").lower()
        or needle in (r.get("citation") or "").lower()
        or needle in (r.get("neutral_citation") or "").lower()
    ]

    if len(strong) == 1:
        return {
            "verdict": VERDICT_VERIFIED,
            "matches": strong,
            "note": "Citation resolves to a single judgment.",
        }
    if len(strong) > 1:
        return {
            "verdict": VERDICT_AMBIGUOUS,
            "matches": strong[:5],
            "note": (
                "More than one judgment matches this citation. Confirm which one "
                "is intended before relying on it."
            ),
        }

    return {
        "verdict": VERDICT_AMBIGUOUS,
        "matches": candidates[:5],
        "note": (
            "Candidates share party names but none carries this citation, so the "
            "citation itself is unconfirmed. Open the candidates and check."
        ),
    }


def _verify_statutory_citation(citation: cit.Citation) -> Dict[str, Any]:
    """Resolve one statutory citation against the bundled statute corpus."""
    from legal_mcp_server.src.sources import india_code

    section = india_code.lookup_section(
        statute=citation.statute or "", section=citation.section or ""
    )

    if section is None:
        known = india_code.resolve_act(citation.statute or "")
        if known is None:
            return {
                "verdict": VERDICT_UNCHECKED,
                "matches": [],
                "confidence": CONFIDENCE_SCORES[VERDICT_UNCHECKED],
                "note": (
                    f"'{citation.statute}' is not in the bundled corpus, so this "
                    "reference could not be checked either way. Confirm it on "
                    "indiacode.nic.in before relying on it."
                ),
            }
        return {
            "verdict": VERDICT_NOT_FOUND,
            "matches": [],
            "confidence": CONFIDENCE_SCORES[VERDICT_NOT_FOUND],
            "note": (
                f"{known.title} is in the corpus but has no section "
                f"{citation.section}. The section number is wrong or has been "
                "renumbered by amendment."
            ),
        }

    return {
        "verdict": VERDICT_VERIFIED,
        "matches": [
            {
                "act": section.act_title,
                "section": section.number,
                "heading": section.heading,
                "url": section.url,
            }
        ],
        "confidence": CONFIDENCE_SCORES[VERDICT_VERIFIED],
        "note": f"Resolves to {section.act_title}, section {section.number}.",
    }


async def _verify_case_citation_dual(
    citation: cit.Citation,
    use_fallback: bool = True,
    max_fallback_budget: int = 5,
) -> Dict[str, Any]:
    """
    Verify a case citation with dual-source fallback.

    First tries the primary backend (open_data). If that returns NOT_FOUND or
    AMBIGUOUS and use_fallback is True, queries Indian Kanoon (paid) if budget
    allows.
    """
    from legal_mcp_server.src.sources import case_law

    # Try primary backend first
    primary_result = await _verify_case_citation(citation)

    if primary_result["verdict"] == VERDICT_VERIFIED:
        return primary_result

    # If primary failed and fallback enabled, try Indian Kanoon
    if use_fallback and max_fallback_budget > 0:
        try:
            # Temporarily switch to indian_kanoon backend
            original_backend = case_law.active_backend()
            if original_backend != "indian_kanoon" and settings.INDIAN_KANOON_API_KEY:
                case_law.set_backend("indian_kanoon")
                try:
                    fallback_result = await _verify_case_citation(citation)
                    fallback_result["fallback_used"] = True
                    fallback_result["primary_backend"] = original_backend
                    fallback_result["fallback_backend"] = "indian_kanoon"
                    return fallback_result
                finally:
                    case_law.set_backend(original_backend)
        except Exception as e:
            logger.warning(f"Dual-source fallback failed: {e}")

    # Return primary result with confidence
    primary_result["confidence"] = CONFIDENCE_SCORES.get(
        primary_result["verdict"], 0.0
    )
    return primary_result


def _build_verification_summary(checked: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a standardized verification summary for tool outputs."""
    if not checked:
        return {
            "total": 0,
            "verified": 0,
            "not_found": 0,
            "ambiguous": 0,
            "unchecked": 0,
            "avg_confidence": 1.0,
            "all_verified": True,
        }

    tally = {
        VERDICT_VERIFIED: 0,
        VERDICT_NOT_FOUND: 0,
        VERDICT_AMBIGUOUS: 0,
        VERDICT_UNCHECKED: 0,
    }
    total_confidence = 0.0

    for entry in checked:
        verdict = entry.get("verdict", VERDICT_UNCHECKED)
        tally[verdict] = tally.get(verdict, 0) + 1
        total_confidence += entry.get("confidence", CONFIDENCE_SCORES.get(verdict, 0.0))

    total = len(checked)
    avg_confidence = total_confidence / total if total > 0 else 1.0
    all_verified = tally[VERDICT_NOT_FOUND] == 0 and tally[VERDICT_AMBIGUOUS] == 0 and tally[VERDICT_UNCHECKED] == 0

    return {
        "total": total,
        "verified": tally[VERDICT_VERIFIED],
        "not_found": tally[VERDICT_NOT_FOUND],
        "ambiguous": tally[VERDICT_AMBIGUOUS],
        "unchecked": tally[VERDICT_UNCHECKED],
        "avg_confidence": round(avg_confidence, 3),
        "all_verified": all_verified,
    }


async def verify_citation(
    citation: str,
    use_dual_source: bool = True,
) -> Dict[str, Any]:
    """Check that a single legal citation refers to something that actually exists.

    TOOL_NAME=verify_citation
    DISPLAY_NAME=Citation Verification
    USECASE=Confirm that a case citation or statutory reference is real before it goes into a memo, opinion, notice or pleading
    INSTRUCTIONS=1. Pass the citation exactly as written, 2. Read the verdict, 3. Present anything other than VERIFIED with its warning intact - never silently drop or reword a failed citation
    INPUT_DESCRIPTION=citation (string, required): one citation, e.g. "(2014) 9 SCC 129", "AIR 1973 SC 1461", "2024:BHC-AS:12345", or "Section 138 of the Negotiable Instruments Act, 1881". use_dual_source (bool, optional, default True): if True, falls back to Indian Kanoon when open_data cannot verify.
    OUTPUT_DESCRIPTION=Dictionary with status, the parsed citation, verdict (VERIFIED, NOT_FOUND, AMBIGUOUS or UNCHECKED), matching authorities, confidence score, and a note explaining the verdict
    EXAMPLES=verify_citation("(2014) 9 SCC 129"), verify_citation("Section 27 of the Indian Contract Act, 1872")
    PREREQUISITES=Case citations need INDIAN_KANOON_API_KEY and cost Rs 0.50; statutory citations are checked offline and are free
    RELATED_TOOLS=verify_all_citations sweeps a whole document at once; get_judgment reads a verified authority

    I/O-bound operation - uses async def for external API calls.

    Args:
        citation: A single citation string.
        use_dual_source: If True, falls back to Indian Kanoon when open_data cannot verify.

    Returns:
        Dict with the verdict and any matching authorities.
    """
    try:
        if not citation or not citation.strip():
            raise ValueError("citation must be a non-empty string")

        parsed = cit.parse_citation(citation.strip())
        if parsed is None:
            return {
                "status": "success",
                "operation": "verify_citation",
                "citation": citation,
                "verdict": VERDICT_UNCHECKED,
                "confidence": CONFIDENCE_SCORES[VERDICT_UNCHECKED],
                "matches": [],
                "note": (
                    "This string was not recognised as an Indian citation format, "
                    "so nothing was checked. If it is meant to be authority, "
                    "rewrite it in a standard form."
                ),
                "message": "Citation format not recognised",
            }

        if not settings.ENABLE_CITATION_VERIFICATION:
            return {
                "status": "success",
                "operation": "verify_citation",
                "citation": citation,
                "parsed": parsed.to_dict(),
                "verdict": VERDICT_UNCHECKED,
                "confidence": CONFIDENCE_SCORES[VERDICT_UNCHECKED],
                "matches": [],
                "note": (
                    "ENABLE_CITATION_VERIFICATION is False, so no lookup was "
                    "performed. Say so rather than implying the citation checks out."
                ),
                "message": "Verification disabled by configuration",
            }

        if parsed.kind is cit.CitationKind.CASE:
            outcome = await _verify_case_citation_dual(
                parsed, use_fallback=use_dual_source
            )
        else:
            outcome = _verify_statutory_citation(parsed)

        return {
            "status": "success",
            "operation": "verify_citation",
            "citation": citation,
            "parsed": parsed.to_dict(),
            **outcome,
            "message": f"Verdict: {outcome['verdict']} (confidence: {outcome.get('confidence', 0.0):.0%})",
        }

    except SourceUnavailable as e:
        return _unavailable("verify_citation", e)
    except Exception as e:
        logger.error(f"Error in verify_citation: {e}")
        return {
            "status": "error",
            "operation": "verify_citation",
            "error": str(e),
            "message": "Failed to verify citation",
        }


async def verify_all_citations(
    text: str,
    max_citations: int = 25,
    use_dual_source: bool = True,
) -> Dict[str, Any]:
    """Extract and verify every citation in a block of text.

    TOOL_NAME=verify_all_citations
    DISPLAY_NAME=Document Citation Sweep
    USECASE=Sweep a memo, opinion, notice or pleading for fabricated or mistaken authority before it is presented or sent
    INSTRUCTIONS=1. Pass the full text, 2. Read the summary counts first, 3. Reproduce every unverified citation to the user with its warning - a draft with unverified authority must be presented as such, never cleaned up silently
    INPUT_DESCRIPTION=text (string, required): the prose to sweep. max_citations (int, optional, default 25): cap on case citations verified, to bound cost. use_dual_source (bool, optional, default True): if True, falls back to Indian Kanoon when open_data cannot verify.
    OUTPUT_DESCRIPTION=Dictionary with status, per-citation verdicts, counts by verdict, confidence scores, an all_verified flag, a verification summary, and the total spend incurred
    EXAMPLES=verify_all_citations(draft_memo_text), verify_all_citations(notice_text, max_citations=10)
    PREREQUISITES=Case citations cost Rs 0.50 each against the Indian Kanoon budget; statutory citations are free
    RELATED_TOOLS=verify_citation for a single citation; build_research_memo runs this sweep automatically

    I/O-bound operation - uses async def for external API calls.

    Args:
        text: The prose to sweep for citations.
        max_citations: Maximum number of paid case-citation checks to run.
        use_dual_source: If True, falls back to Indian Kanoon when open_data cannot verify.

    Returns:
        Dict with a verdict for every citation found, plus verification summary.
    """
    try:
        if not text or not text.strip():
            raise ValueError("text must be a non-empty string")

        found = cit.extract_all(text)
        if not found:
            return {
                "status": "success",
                "operation": "verify_all_citations",
                "citations": [],
                "citation_count": 0,
                "all_verified": True,
                "verification_summary": _build_verification_summary([]),
                "message": (
                    "No citations found in this text. If it makes legal assertions "
                    "without authority, that is itself worth flagging to the user."
                ),
            }

        checked: List[Dict[str, Any]] = []
        case_budget = max(0, max_citations)
        skipped = 0

        for citation in found:
            if citation.kind is cit.CitationKind.CASE:
                if case_budget <= 0:
                    skipped += 1
                    checked.append(
                        {
                            "citation": citation.raw,
                            "parsed": citation.to_dict(),
                            "verdict": VERDICT_UNCHECKED,
                            "confidence": CONFIDENCE_SCORES[VERDICT_UNCHECKED],
                            "matches": [],
                            "note": (
                                "Skipped: max_citations limit reached. This citation "
                                "was NOT checked."
                            ),
                        }
                    )
                    continue
                case_budget -= 1
                try:
                    outcome = await _verify_case_citation_dual(
                        citation,
                        use_fallback=use_dual_source,
                        max_fallback_budget=case_budget,
                    )
                except SourceUnavailable as e:
                    outcome = {
                        "verdict": VERDICT_UNCHECKED,
                        "confidence": CONFIDENCE_SCORES[VERDICT_UNCHECKED],
                        "matches": [],
                        "note": f"Source unavailable, not checked: {e}",
                    }
            else:
                outcome = _verify_statutory_citation(citation)

            # Ensure confidence is present
            if "confidence" not in outcome:
                outcome["confidence"] = CONFIDENCE_SCORES.get(
                    outcome["verdict"], 0.0
                )

            checked.append(
                {
                    "citation": citation.raw,
                    "parsed": citation.to_dict(),
                    **outcome,
                }
            )

        verification_summary = _build_verification_summary(checked)

        if verification_summary["all_verified"]:
            message = f"All {len(checked)} citations verified against a live source."
        else:
            message = (
                f"{verification_summary['total'] - verification_summary['verified']} of "
                f"{verification_summary['total']} citations are not verified "
                f"({verification_summary['not_found']} not found, "
                f"{verification_summary['ambiguous']} ambiguous, "
                f"{verification_summary['unchecked']} unchecked). "
                f"Average confidence: {verification_summary['avg_confidence']:.0%}. "
                "Present each of these to the user marked UNVERIFIED. Do not remove them "
                "quietly and do not restate them as if they were confirmed."
            )

        return {
            "status": "success",
            "operation": "verify_all_citations",
            "citations": checked,
            "citation_count": len(checked),
            "verdict_counts": {
                VERDICT_VERIFIED: verification_summary["verified"],
                VERDICT_NOT_FOUND: verification_summary["not_found"],
                VERDICT_AMBIGUOUS: verification_summary["ambiguous"],
                VERDICT_UNCHECKED: verification_summary["unchecked"],
            },
            "unverified": [e for e in checked if e["verdict"] != VERDICT_VERIFIED],
            "all_verified": verification_summary["all_verified"],
            "verification_summary": verification_summary,
            "skipped_for_budget": skipped,
            "backend": case_law.active_backend(),
            "message": message,
        }

    except Exception as e:
        logger.error(f"Error in verify_all_citations: {e}")
        return {
            "status": "error",
            "operation": "verify_all_citations",
            "error": str(e),
            "message": "Failed to verify citations",
        }


async def build_research_memo(
    issue: str,
    queries: Optional[List[str]] = None,
    court: Optional[str] = None,
    max_authorities: int = 6,
) -> Dict[str, Any]:
    """Assemble the sourced evidence base for a legal research memo.

    TOOL_NAME=build_research_memo
    DISPLAY_NAME=Research Memo Builder
    USECASE=Gather and verify the authorities needed to answer a legal question, ready to be written up as a memo
    INSTRUCTIONS=1. State the issue as a legal question, 2. Supply two to four search queries covering different phrasings of the point, 3. Read the returned authorities, 4. Write the memo yourself from what came back - this tool gathers evidence, it does not draft the analysis
    INPUT_DESCRIPTION=issue (string, required): the legal question. queries (list of strings, optional): search phrasings; the issue text is used if omitted. court (string, optional): court filter. max_authorities (int, optional, default 6): cap on judgments gathered.
    OUTPUT_DESCRIPTION=Dictionary with status, the issue, per-query results, a de-duplicated authority list, the citation sweep, cost incurred, and explicit drafting instructions
    EXAMPLES=build_research_memo("Is a post-termination non-compete enforceable against an employee in India?", queries=["section 27 Contract Act restraint of trade employment", "negative covenant post termination employee void"])
    PREREQUISITES=Run sync_case_law for the relevant courts and years. Free on the default open-data backend.
    RELATED_TOOLS=get_judgment to read an authority in full; verify_all_citations to sweep the memo you write

    I/O-bound operation - uses async def for external data access.

    Args:
        issue: The legal question to research.
        queries: Alternative search phrasings of the issue.
        court: Optional court filter applied to every query.
        max_authorities: Maximum de-duplicated authorities to return.

    Returns:
        Dict with the gathered, verified evidence base.
    """
    try:
        if not issue or not issue.strip():
            raise ValueError("issue must be a non-empty string")

        search_terms = [q.strip() for q in (queries or []) if q and q.strip()]
        if not search_terms:
            search_terms = [issue.strip()]

        per_query: List[Dict[str, Any]] = []
        authorities: Dict[str, Dict[str, Any]] = {}

        for term in search_terms:
            try:
                payload = await case_law.search(query=term, court=court)
            except SourceUnavailable as e:
                per_query.append(
                    {"query": term, "status": "unavailable", "error": str(e)}
                )
                continue

            per_query.append(
                {
                    "query": term,
                    "status": "success",
                    "result_count": len(payload["results"]),
                }
            )
            for result in payload["results"]:
                if len(authorities) >= max_authorities:
                    break
                authorities.setdefault(result["doc_id"], result)

        statutory = [c.to_dict() for c in cit.extract_statutory_citations(issue)]

        if not authorities and all(q.get("status") == "unavailable" for q in per_query):
            return _unavailable(
                "build_research_memo", SourceUnavailable("all queries failed")
            )

        return {
            "status": "success",
            "operation": "build_research_memo",
            "issue": issue,
            "queries_run": per_query,
            "authorities": list(authorities.values()),
            "authority_count": len(authorities),
            "statutory_references_in_issue": statutory,
            "backend": case_law.active_backend(),
            "drafting_instructions": (
                "Write the memo in this order: ISSUE, SHORT ANSWER, STATUTORY "
                "FRAMEWORK, AUTHORITIES, ANALYSIS, RISKS AND UNKNOWNS. "
                "Open each authority with get_judgment or search_within_judgment "
                "before you characterise its holding - the snippets above are not "
                "a sufficient basis. Where the authorities conflict, say so rather "
                "than picking the convenient one. State explicitly what you could "
                "not find. When the memo is written, run verify_all_citations over "
                "it and reproduce any UNVERIFIED result to the user."
            ),
            "message": (
                f"Gathered {len(authorities)} candidate authorities across "
                f"{len(search_terms)} queries. This is an evidence base, not a memo."
            ),
        }

    except Exception as e:
        logger.error(f"Error in build_research_memo: {e}")
        return {
            "status": "error",
            "operation": "build_research_memo",
            "error": str(e),
            "message": "Failed to build research memo",
        }


async def sync_case_law(
    courts: Optional[List[str]] = None,
    from_year: int = 2015,
    to_year: int = 2026,
    force: bool = False,
) -> Dict[str, Any]:
    """Download free judgment metadata so case-law search works offline.

    TOOL_NAME=sync_case_law
    DISPLAY_NAME=Case Law Corpus Sync
    USECASE=Set up or widen the local free case-law corpus for the courts and years the user actually needs
    INSTRUCTIONS=1. Run once before first use, 2. Start narrow - the default state High Court plus the Supreme Court for recent years, 3. Widen the year range later if a search comes up empty, 4. Tell the user this downloads tens of MB and takes a minute or two
    INPUT_DESCRIPTION=courts (list of strings, optional): e.g. ["Supreme Court", "Bombay High Court"]; defaults to the Supreme Court plus the configured default High Court. from_year/to_year (int, optional): inclusive year range, default 2015-2026. force (bool, optional): re-download files already present.
    OUTPUT_DESCRIPTION=Dictionary with status, per-court file counts, years and benches synced, megabytes downloaded, and the attribution required by the licence
    EXAMPLES=sync_case_law(), sync_case_law(courts=["Supreme Court"], from_year=2020, to_year=2026), sync_case_law(courts=["Bombay High Court", "Delhi"], from_year=2023, to_year=2026)
    PREREQUISITES=Internet access. No API key, no account, no charge - the data is public and CC-BY-4.0.
    RELATED_TOOLS=case_law_status to see current coverage; search_case_law to query what was synced

    I/O-bound operation - uses async def for external data access.

    Args:
        courts: Courts to sync. Defaults to Supreme Court plus the configured
            default High Court.
        from_year: First year to sync, inclusive.
        to_year: Last year to sync, inclusive.
        force: Re-download files that already exist locally.

    Returns:
        Dict summarising what was downloaded.
    """
    try:
        from legal_mcp_server.src.sources import open_judgments

        if case_law.active_backend() != "open_data":
            return {
                "status": "error",
                "operation": "sync_case_law",
                "error": f"CASE_LAW_SOURCE is '{case_law.active_backend()}'",
                "message": (
                    "Syncing only applies to the free open-data backend. Set "
                    "CASE_LAW_SOURCE=open_data to use it."
                ),
            }

        targets = [c for c in (courts or []) if c and c.strip()]
        if not targets:
            targets = ["Supreme Court", f"{settings.DEFAULT_HIGH_COURT} High Court"]

        client = open_judgments.get_client()
        summary = await client.sync(
            courts=targets,
            from_year=int(from_year),
            to_year=int(to_year),
            force=bool(force),
        )

        logger.info(
            f"Synced case law: {summary['files']} files, {summary['megabytes']} MB"
        )

        return {
            "status": "success",
            "operation": "sync_case_law",
            **summary,
            "message": (
                f"Downloaded {summary['files']} metadata files "
                f"({summary['megabytes']} MB) covering {from_year}-{to_year}. "
                f"{summary['skipped']} already present. Search is now local, "
                "offline and free. Judgment PDFs are fetched individually on "
                "demand when you open one."
            ),
        }

    except open_judgments.SourceUnavailable as e:
        return _unavailable("sync_case_law", e)
    except Exception as e:
        logger.error(f"Error in sync_case_law: {e}")
        return {
            "status": "error",
            "operation": "sync_case_law",
            "error": str(e),
            "message": "Failed to sync case law corpus",
        }


def case_law_status() -> Dict[str, Any]:
    """Report which case-law backend is active and what it currently covers.

    TOOL_NAME=case_law_status
    DISPLAY_NAME=Case Law Source Status
    USECASE=Check before researching whether case law is available and which courts and years are actually searchable
    INSTRUCTIONS=1. Call before a research task, 2. If the corpus is not synced or the years needed are missing, run sync_case_law, 3. Never treat an empty search over an unsynced range as proof that no authority exists
    INPUT_DESCRIPTION=No parameters
    OUTPUT_DESCRIPTION=Dictionary with status, the active backend, whether it is usable, the courts and years synced, cached PDF count, and the cost model
    EXAMPLES=case_law_status()
    PREREQUISITES=None
    RELATED_TOOLS=sync_case_law to widen coverage; search_case_law to query it

    CPU-bound operation - uses def for local state inspection.

    Returns:
        Dict describing the active backend and its coverage.
    """
    try:
        report = case_law.status()
        return {
            "status": "success",
            "operation": "case_law_status",
            "citation_verification_enabled": settings.ENABLE_CITATION_VERIFICATION,
            **report,
        }
    except Exception as e:
        logger.error(f"Error in case_law_status: {e}")
        return {
            "status": "error",
            "operation": "case_law_status",
            "error": str(e),
            "message": "Failed to read case law status",
        }


TOOLS: List[Any] = [
    search_case_law,
    get_judgment,
    search_within_judgment,
    find_related_proceedings,
    verify_citation,
    verify_all_citations,
    build_research_memo,
    sync_case_law,
    case_law_status,
]
