"""Case-law research and citation-verification tools for the Legal MCP Server.

These tools are the server's answer to the single biggest failure mode in
AI-assisted legal work: a citation that reads perfectly and does not exist.
Every authority surfaced here comes from a real lookup against Indian Kanoon,
and :func:`verify_all_citations` exists so that any prose - including prose the
model wrote itself - can be swept before it reaches the user.
"""

from typing import Any, Dict, List, Optional

from legal_mcp_server.src.domain import citations as cit
from legal_mcp_server.src.settings import settings
from legal_mcp_server.src.sources.indian_kanoon import (
    SourceUnavailable,
    get_client,
)
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()

# Indian Kanoon court filter tokens, exposed so tool callers use valid values.
COURT_FILTERS = {
    "supreme court": "supremecourt",
    "sc": "supremecourt",
    "bombay": "bombay",
    "bombay high court": "bombay",
    "delhi": "delhi",
    "delhi high court": "delhi",
    "kolkata": "kolkata",
    "chennai": "chennai",
    "madras": "chennai",
    "karnataka": "karnataka",
    "allahabad": "allahabad",
    "gujarat": "gujarat",
    "kerala": "kerala",
    "punjab": "punjab",
    "rajasthan": "rajasthan",
    "nclat": "nclat",
    "ncdrc": "ncdrc",
    "cat": "cat",
    "itat": "itat",
    "tribunals": "tribunals",
    "high courts": "highcourts",
}

VERDICT_VERIFIED = "VERIFIED"
VERDICT_NOT_FOUND = "NOT_FOUND"
VERDICT_AMBIGUOUS = "AMBIGUOUS"
VERDICT_UNCHECKED = "UNCHECKED"


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


def _resolve_court(court: Optional[str]) -> Optional[str]:
    """Map a friendly court name to an Indian Kanoon filter token."""
    if not court:
        return None
    return COURT_FILTERS.get(court.strip().lower(), court.strip().lower())


async def search_case_law(
    query: str,
    court: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    judge: Optional[str] = None,
    page: int = 0,
) -> Dict[str, Any]:
    """Search Indian case law on Indian Kanoon.

    TOOL_NAME=search_case_law
    DISPLAY_NAME=Indian Case Law Search
    USECASE=Find Indian judgments on a legal proposition, from the Supreme Court, any High Court, or tribunals
    INSTRUCTIONS=1. Phrase the query as the legal proposition, not a natural-language question, 2. Narrow with court and date filters where the forum matters, 3. Read the snippets and fetch promising judgments with get_judgment, 4. Never cite a result you have not opened
    INPUT_DESCRIPTION=query (string, required): search terms; Indian Kanoon operators work, so quotes force a phrase and AND/OR/NOT combine terms. court (string, optional): "supreme court", "bombay", "delhi", etc. from_date/to_date (string, optional): DD-MM-YYYY bounds. judge (string, optional): judge surname. page (int, optional): zero-based results page.
    OUTPUT_DESCRIPTION=Dictionary with status, results (doc_id, title, court, date, snippet, url), found count, the query actually sent, and the running Indian Kanoon spend
    EXAMPLES=search_case_law('"cheque dishonour" AND "section 138" AND territorial jurisdiction', court="bombay"), search_case_law("non-compete clause section 27 Contract Act void", court="supreme court")
    PREREQUISITES=INDIAN_KANOON_API_KEY must be configured; each search costs Rs 0.50 against the daily budget
    RELATED_TOOLS=get_judgment to read a result, search_within_judgment to locate a passage, verify_citation to confirm a citation you already have

    I/O-bound operation - uses async def for external API calls.

    Args:
        query: Search terms expressing the legal proposition.
        court: Optional court filter.
        from_date: Optional lower date bound, DD-MM-YYYY.
        to_date: Optional upper date bound, DD-MM-YYYY.
        judge: Optional authoring-judge filter.
        page: Zero-based results page.

    Returns:
        Dict with the ranked results and search metadata.
    """
    try:
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")

        client = get_client()
        payload = await client.search(
            query=query.strip(),
            page=max(0, page),
            court=_resolve_court(court),
            from_date=from_date,
            to_date=to_date,
            author=judge,
        )

        logger.info(
            f"Case law search returned {len(payload['results'])} results for: {query}"
        )

        return {
            "status": "success",
            "operation": "search_case_law",
            "results": payload["results"],
            "result_count": len(payload["results"]),
            "total_found": payload.get("found"),
            "query_sent": payload["query"],
            "page": payload["page"],
            "spend": client.spend_report(),
            "message": (
                f"Found {len(payload['results'])} judgments. Open the relevant ones "
                "with get_judgment before relying on them; snippets are not a "
                "sufficient basis for a citation."
            ),
        }

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
    doc_id: int, include_citations: bool = True, max_chars: int = 0
) -> Dict[str, Any]:
    """Retrieve the full text of a judgment by its Indian Kanoon document id.

    TOOL_NAME=get_judgment
    DISPLAY_NAME=Full Judgment Retrieval
    USECASE=Read a complete judgment, with its authorities-cited and cited-by lists, before relying on it
    INSTRUCTIONS=1. Obtain a doc_id from search_case_law, 2. Call this tool, 3. Read the holding rather than the headnote, 4. Check cited_by via find_citing_cases if the case is old or the point is contested
    INPUT_DESCRIPTION=doc_id (int, required): Indian Kanoon document id. include_citations (bool, optional, default True): include the citation graph. max_chars (int, optional, default 0 = whole judgment): truncate very long judgments.
    OUTPUT_DESCRIPTION=Dictionary with status, doc_id, title, court, date, bench, full text, cites, cited_by, url, and running spend
    EXAMPLES=get_judgment(1766147), get_judgment(1766147, max_chars=20000)
    PREREQUISITES=INDIAN_KANOON_API_KEY configured; costs Rs 0.20 per judgment
    RELATED_TOOLS=search_within_judgment is far cheaper if you only need one passage; find_citing_cases checks whether the case is still good law

    I/O-bound operation - uses async def for external API calls.

    Args:
        doc_id: Indian Kanoon document id.
        include_citations: Whether to return the citation graph.
        max_chars: Optional truncation limit; 0 returns the whole judgment.

    Returns:
        Dict with the judgment text and metadata.
    """
    try:
        if not isinstance(doc_id, int) or doc_id <= 0:
            raise ValueError("doc_id must be a positive integer")

        client = get_client()
        max_edges = 20 if include_citations else 0
        judgment = await client.get_document(
            doc_id, max_cites=max_edges, max_cited_by=max_edges
        )

        result = judgment.to_dict()
        truncated = False
        if max_chars and len(result["text"]) > max_chars:
            result["text"] = result["text"][:max_chars]
            truncated = True

        return {
            "status": "success",
            "operation": "get_judgment",
            **result,
            "truncated": truncated,
            "spend": client.spend_report(),
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


async def search_within_judgment(doc_id: int, query: str) -> Dict[str, Any]:
    """Find the passages inside one judgment that deal with a specific point.

    TOOL_NAME=search_within_judgment
    DISPLAY_NAME=Judgment Passage Finder
    USECASE=Locate what a specific judgment says about a specific point without paying to download the whole thing
    INSTRUCTIONS=1. Obtain a doc_id from search_case_law, 2. Pass the point you need, 3. If the fragments settle the question, stop - do not fetch the full judgment
    INPUT_DESCRIPTION=doc_id (int, required): Indian Kanoon document id. query (string, required): the point to locate, e.g. "territorial jurisdiction" or "burden of proof"
    OUTPUT_DESCRIPTION=Dictionary with status, doc_id, title, matching fragments, url, and running spend
    EXAMPLES=search_within_judgment(1766147, "territorial jurisdiction"), search_within_judgment(59736, "presumption under section 139")
    PREREQUISITES=INDIAN_KANOON_API_KEY configured; costs Rs 0.05, the cheapest case-law call available
    RELATED_TOOLS=get_judgment when you need the full reasoning; search_case_law to find the doc_id

    I/O-bound operation - uses async def for external API calls.

    Args:
        doc_id: Indian Kanoon document id.
        query: The proposition or term to locate within the judgment.

    Returns:
        Dict with the matching passages.
    """
    try:
        if not isinstance(doc_id, int) or doc_id <= 0:
            raise ValueError("doc_id must be a positive integer")
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")

        client = get_client()
        payload = await client.get_fragments(doc_id, query.strip())

        return {
            "status": "success",
            "operation": "search_within_judgment",
            **payload,
            "fragment_count": len(payload["fragments"]),
            "spend": client.spend_report(),
            "message": (
                f"Found {len(payload['fragments'])} matching passages."
                if payload["fragments"]
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


async def find_citing_cases(doc_id: int, limit: int = 20) -> Dict[str, Any]:
    """List later cases that cite a judgment, to test whether it is still good law.

    TOOL_NAME=find_citing_cases
    DISPLAY_NAME=Subsequent History Check
    USECASE=Check whether a judgment has been followed, distinguished, doubted or overruled before you rely on it
    INSTRUCTIONS=1. Obtain a doc_id, 2. Call this tool, 3. Open any later Supreme Court or larger-bench decision in the list, 4. Report explicitly if the authority appears to have been overtaken
    INPUT_DESCRIPTION=doc_id (int, required): Indian Kanoon document id. limit (int, optional, default 20): maximum citing cases to return.
    OUTPUT_DESCRIPTION=Dictionary with status, the judgment being checked, cited_by list, cites list, counts, and a caution about interpreting the result
    EXAMPLES=find_citing_cases(1766147), find_citing_cases(59736, limit=50)
    PREREQUISITES=INDIAN_KANOON_API_KEY configured; costs Rs 0.20
    RELATED_TOOLS=get_judgment for the full text; search_case_law to find later authority directly

    I/O-bound operation - uses async def for external API calls.

    Args:
        doc_id: Indian Kanoon document id.
        limit: Maximum number of citing cases to return.

    Returns:
        Dict with the citing and cited lists.
    """
    try:
        if not isinstance(doc_id, int) or doc_id <= 0:
            raise ValueError("doc_id must be a positive integer")

        client = get_client()
        bounded = max(1, min(limit, 100))
        judgment = await client.get_document(
            doc_id, max_cites=bounded, max_cited_by=bounded
        )

        return {
            "status": "success",
            "operation": "find_citing_cases",
            "doc_id": doc_id,
            "title": judgment.title,
            "court": judgment.court,
            "date": judgment.date,
            "cited_by": judgment.cited_by,
            "cited_by_count": len(judgment.cited_by),
            "cites": judgment.citations,
            "cites_count": len(judgment.citations),
            "url": judgment.url,
            "spend": client.spend_report(),
            "message": (
                "A citing case may follow, distinguish, doubt or overrule this "
                "judgment - the list alone does not tell you which. Open the "
                "significant ones, particularly any later Supreme Court or "
                "larger-bench decision, before relying on this authority."
            ),
        }

    except SourceUnavailable as e:
        return _unavailable("find_citing_cases", e)
    except Exception as e:
        logger.error(f"Error in find_citing_cases: {e}")
        return {
            "status": "error",
            "operation": "find_citing_cases",
            "error": str(e),
            "message": "Failed to retrieve citing cases",
        }


async def _verify_case_citation(citation: cit.Citation) -> Dict[str, Any]:
    """Resolve one case citation against Indian Kanoon."""
    client = get_client()
    payload = await client.search(query=citation.search_query(), page=0)
    results = payload["results"]

    if not results:
        # Retry on the bare citation in case the party names were the problem.
        if citation.case_name:
            payload = await client.search(query=citation.normalized, page=0)
            results = payload["results"]

    if not results:
        return {
            "verdict": VERDICT_NOT_FOUND,
            "matches": [],
            "note": (
                "No judgment on Indian Kanoon matches this citation. Treat it as "
                "unverified and do not present it as authority."
            ),
        }

    # A citation string is distinctive; if the top hit does not contain the
    # citation or the party names, the match is not safe to assert.
    needle = citation.normalized.lower()
    strong = [
        r
        for r in results
        if needle in (r["title"] or "").lower()
        or needle in (r["snippet"] or "").lower()
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
        "matches": results[:5],
        "note": (
            "Search returned results but none contains the citation itself, so "
            "the match is by party name only. Open the candidates and confirm."
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
                "note": (
                    f"'{citation.statute}' is not in the bundled corpus, so this "
                    "reference could not be checked either way. Confirm it on "
                    "indiacode.nic.in before relying on it."
                ),
            }
        return {
            "verdict": VERDICT_NOT_FOUND,
            "matches": [],
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
        "note": f"Resolves to {section.act_title}, section {section.number}.",
    }


async def verify_citation(citation: str) -> Dict[str, Any]:
    """Check that a single legal citation refers to something that actually exists.

    TOOL_NAME=verify_citation
    DISPLAY_NAME=Citation Verification
    USECASE=Confirm that a case citation or statutory reference is real before it goes into a memo, opinion, notice or pleading
    INSTRUCTIONS=1. Pass the citation exactly as written, 2. Read the verdict, 3. Present anything other than VERIFIED with its warning intact - never silently drop or reword a failed citation
    INPUT_DESCRIPTION=citation (string, required): one citation, e.g. "(2014) 9 SCC 129", "AIR 1973 SC 1461", "2024:BHC-AS:12345", or "Section 138 of the Negotiable Instruments Act, 1881"
    OUTPUT_DESCRIPTION=Dictionary with status, the parsed citation, verdict (VERIFIED, NOT_FOUND, AMBIGUOUS or UNCHECKED), matching authorities, and a note explaining the verdict
    EXAMPLES=verify_citation("(2014) 9 SCC 129"), verify_citation("Section 27 of the Indian Contract Act, 1872")
    PREREQUISITES=Case citations need INDIAN_KANOON_API_KEY and cost Rs 0.50; statutory citations are checked offline and are free
    RELATED_TOOLS=verify_all_citations sweeps a whole document at once; get_judgment reads a verified authority

    I/O-bound operation - uses async def for external API calls.

    Args:
        citation: A single citation string.

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
                "matches": [],
                "note": (
                    "ENABLE_CITATION_VERIFICATION is False, so no lookup was "
                    "performed. Say so rather than implying the citation checks out."
                ),
                "message": "Verification disabled by configuration",
            }

        if parsed.kind is cit.CitationKind.CASE:
            outcome = await _verify_case_citation(parsed)
        else:
            outcome = _verify_statutory_citation(parsed)

        return {
            "status": "success",
            "operation": "verify_citation",
            "citation": citation,
            "parsed": parsed.to_dict(),
            **outcome,
            "message": f"Verdict: {outcome['verdict']}",
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


async def verify_all_citations(text: str, max_citations: int = 25) -> Dict[str, Any]:
    """Extract and verify every citation in a block of text.

    TOOL_NAME=verify_all_citations
    DISPLAY_NAME=Document Citation Sweep
    USECASE=Sweep a memo, opinion, notice or pleading for fabricated or mistaken authority before it is presented or sent
    INSTRUCTIONS=1. Pass the full text, 2. Read the summary counts first, 3. Reproduce every unverified citation to the user with its warning - a draft with unverified authority must be presented as such, never cleaned up silently
    INPUT_DESCRIPTION=text (string, required): the prose to sweep. max_citations (int, optional, default 25): cap on case citations verified, to bound cost.
    OUTPUT_DESCRIPTION=Dictionary with status, per-citation verdicts, counts by verdict, an all_verified flag, and the total spend incurred
    EXAMPLES=verify_all_citations(draft_memo_text), verify_all_citations(notice_text, max_citations=10)
    PREREQUISITES=Case citations cost Rs 0.50 each against the Indian Kanoon budget; statutory citations are free
    RELATED_TOOLS=verify_citation for a single citation; build_research_memo runs this sweep automatically

    I/O-bound operation - uses async def for external API calls.

    Args:
        text: The prose to sweep for citations.
        max_citations: Maximum number of paid case-citation checks to run.

    Returns:
        Dict with a verdict for every citation found.
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
                    outcome = await _verify_case_citation(citation)
                except SourceUnavailable as e:
                    outcome = {
                        "verdict": VERDICT_UNCHECKED,
                        "matches": [],
                        "note": f"Source unavailable, not checked: {e}",
                    }
            else:
                outcome = _verify_statutory_citation(citation)

            checked.append(
                {
                    "citation": citation.raw,
                    "parsed": citation.to_dict(),
                    **outcome,
                }
            )

        tally = {
            VERDICT_VERIFIED: 0,
            VERDICT_NOT_FOUND: 0,
            VERDICT_AMBIGUOUS: 0,
            VERDICT_UNCHECKED: 0,
        }
        for entry in checked:
            tally[entry["verdict"]] = tally.get(entry["verdict"], 0) + 1

        problems = [e for e in checked if e["verdict"] != VERDICT_VERIFIED]
        all_verified = not problems

        if all_verified:
            message = f"All {len(checked)} citations verified against a live source."
        else:
            message = (
                f"{len(problems)} of {len(checked)} citations are not verified "
                f"({tally[VERDICT_NOT_FOUND]} not found, "
                f"{tally[VERDICT_AMBIGUOUS]} ambiguous, "
                f"{tally[VERDICT_UNCHECKED]} unchecked). Present each of these to "
                "the user marked UNVERIFIED. Do not remove them quietly and do not "
                "restate them as if they were confirmed."
            )

        return {
            "status": "success",
            "operation": "verify_all_citations",
            "citations": checked,
            "citation_count": len(checked),
            "verdict_counts": tally,
            "unverified": problems,
            "all_verified": all_verified,
            "skipped_for_budget": skipped,
            "spend": get_client().spend_report(),
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
    PREREQUISITES=INDIAN_KANOON_API_KEY configured; each query costs Rs 0.50
    RELATED_TOOLS=get_judgment to read an authority in full; verify_all_citations to sweep the memo you write

    I/O-bound operation - uses async def for external API calls.

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

        client = get_client()
        per_query: List[Dict[str, Any]] = []
        authorities: Dict[int, Dict[str, Any]] = {}

        for term in search_terms:
            try:
                payload = await client.search(
                    query=term, page=0, court=_resolve_court(court)
                )
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
            "spend": client.spend_report(),
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


def get_research_budget_status() -> Dict[str, Any]:
    """Report today's Indian Kanoon spend against the configured daily cap.

    TOOL_NAME=get_research_budget_status
    DISPLAY_NAME=Case Law Budget Status
    USECASE=Check how much of today's paid case-law budget remains before starting a broad research run
    INSTRUCTIONS=1. Call before a large research task, 2. If remaining budget is low, narrow the queries or use search_within_judgment instead of get_judgment
    INPUT_DESCRIPTION=No parameters
    OUTPUT_DESCRIPTION=Dictionary with status, whether case law is available at all, today's spend and call count, the configured cap, remaining budget, and per-call prices
    EXAMPLES=get_research_budget_status()
    PREREQUISITES=None
    RELATED_TOOLS=search_case_law, get_judgment and search_within_judgment all draw on this budget

    CPU-bound operation - uses def for local state inspection.

    Returns:
        Dict describing the current spend position.
    """
    try:
        client = get_client()
        return {
            "status": "success",
            "operation": "get_research_budget_status",
            "case_law_available": client.available,
            "api_key_configured": bool(settings.INDIAN_KANOON_API_KEY),
            "citation_verification_enabled": settings.ENABLE_CITATION_VERIFICATION,
            **client.spend_report(),
            "prices_inr": {
                "search": 0.50,
                "full_judgment": 0.20,
                "judgment_metadata": 0.05,
                "passage_search": 0.05,
            },
            "message": (
                "Case law is available."
                if client.available
                else "Case law is NOT available - INDIAN_KANOON_API_KEY is missing "
                "or the daily budget is zero. Say so rather than answering from "
                "recalled case law."
            ),
        }
    except Exception as e:
        logger.error(f"Error in get_research_budget_status: {e}")
        return {
            "status": "error",
            "operation": "get_research_budget_status",
            "error": str(e),
            "message": "Failed to read budget status",
        }


TOOLS: List[Any] = [
    search_case_law,
    get_judgment,
    search_within_judgment,
    find_citing_cases,
    verify_citation,
    verify_all_citations,
    build_research_memo,
    get_research_budget_status,
]
