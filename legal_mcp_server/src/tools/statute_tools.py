"""Bare-Act and statutory-provision tools for the Legal MCP Server.

These tools read the bundled offline corpus rather than the live India Code
portal, so they are free, fast and available without a network. The price of
that is bounded coverage, and every response states its coverage honestly: a
section that is absent from a *partial* Act is reported as "not in the corpus",
never as "does not exist".
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from legal_mcp_server.src.domain import new_criminal_codes as ncc
from legal_mcp_server.src.sources import india_code
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()


def _corpus_missing() -> Dict[str, Any]:
    """Response used when no Act corpus is bundled at all."""
    return {
        "status": "unavailable",
        "error": "statute corpus not found",
        "message": (
            "No bare-Act corpus is installed, so statutory text cannot be looked "
            "up. Run 'python scripts/build_seed_acts.py' then "
            "'python scripts/fetch_corpus.py'. Do not answer statutory questions "
            "from memory in the meantime."
        ),
    }


def get_section(statute: str, section: str) -> Dict[str, Any]:
    """Retrieve the text of a specific section of an Indian Act.

    TOOL_NAME=get_section
    DISPLAY_NAME=Bare Act Section Lookup
    USECASE=Read the actual provision before advising on it, instead of relying on a remembered paraphrase
    INSTRUCTIONS=1. Give the Act by name or common abbreviation, 2. Give the section number, 3. Check the text_kind field - 'authentic' is the statute's own words, 'summary' is a curated paraphrase that must not be quoted as statutory text
    INPUT_DESCRIPTION=statute (string, required): Act name or abbreviation such as "NI Act", "Indian Contract Act, 1872", "IPC", "BNS", "Constitution". section (string, required): section number, with or without sub-section, e.g. "138", "4(2)", "Article 21".
    OUTPUT_DESCRIPTION=Dictionary with status, act, section, heading, text, text_kind, chapter, India Code url, and a caveat when the text is a summary
    EXAMPLES=get_section("NI Act", "138"), get_section("Indian Contract Act, 1872", "27"), get_section("Constitution", "21")
    PREREQUISITES=Bundled corpus installed via scripts/fetch_corpus.py; no API key or network needed
    RELATED_TOOLS=search_statute to find a section by subject; map_criminal_code_section for IPC/BNS equivalence; list_bundled_acts for coverage

    CPU-bound operation - uses def for local corpus lookup.

    Args:
        statute: Act name, short title or alias.
        section: Section or article number.

    Returns:
        Dict with the provision, or an explanation of why it was not found.
    """
    try:
        if not statute or not statute.strip():
            raise ValueError("statute must be a non-empty string")
        if not section or not str(section).strip():
            raise ValueError("section must be a non-empty value")

        if not india_code.corpus_available():
            return _corpus_missing()

        act = india_code.resolve_act(statute)
        if act is None:
            return {
                "status": "not_found",
                "operation": "get_section",
                "statute_requested": statute,
                "message": (
                    f"'{statute}' is not in the bundled corpus, so this provision "
                    "could not be checked. Read it at indiacode.nic.in rather than "
                    "reconstructing it from memory. Call list_bundled_acts to see "
                    "what is available."
                ),
            }

        found = act.sections.get(india_code._normalise_section_number(str(section)))
        if found is None:
            if act.is_complete:
                explanation = (
                    f"{act.title} is fully bundled and has no section {section}. "
                    "The section number is wrong, or it was inserted or renumbered "
                    "by an amendment later than this corpus."
                )
            else:
                explanation = (
                    f"Only selected sections of {act.title} are bundled, and "
                    f"section {section} is not among them. This is NOT a finding "
                    "that the section does not exist - read it at "
                    f"{act.url or 'indiacode.nic.in'}."
                )
            return {
                "status": "not_found",
                "operation": "get_section",
                "act": act.title,
                "section_requested": str(section),
                "coverage": act.coverage,
                "url": act.url,
                "message": explanation,
            }

        payload = found.to_dict()
        return {
            "status": "success",
            "operation": "get_section",
            **payload,
            "act_coverage": act.coverage,
            "act_note": act.note,
            "message": (
                f"{act.title}, section {found.number}."
                + (
                    ""
                    if found.is_authentic
                    else " Returned text is a SUMMARY, not the statute's own words."
                )
                + (f" Note: {act.note}" if act.note else "")
            ),
        }

    except Exception as e:
        logger.error(f"Error in get_section: {e}")
        return {
            "status": "error",
            "operation": "get_section",
            "error": str(e),
            "message": "Failed to look up section",
        }


def search_statute(
    query: str, statute: Optional[str] = None, limit: int = 10
) -> Dict[str, Any]:
    """Search the bundled Acts for provisions dealing with a subject.

    TOOL_NAME=search_statute
    DISPLAY_NAME=Statutory Provision Search
    USECASE=Find which section governs a situation when you know the subject but not the section number
    INSTRUCTIONS=1. Describe the subject in a few words, 2. Optionally restrict to one Act, 3. Read the promising results in full with get_section
    INPUT_DESCRIPTION=query (string, required): subject words, e.g. "dishonour of cheque" or "restraint of trade". statute (string, optional): restrict to one Act. limit (int, optional, default 10): maximum results.
    OUTPUT_DESCRIPTION=Dictionary with status, matching sections (act, section, heading, snippet, text_kind, url), result count, and the coverage caveat
    EXAMPLES=search_statute("dishonour of cheque"), search_statute("anticipatory bail", statute="BNSS"), search_statute("restraint of trade", statute="Indian Contract Act, 1872")
    PREREQUISITES=Bundled corpus installed; no API key or network needed
    RELATED_TOOLS=get_section for the full provision; search_case_law for judicial interpretation of it

    CPU-bound operation - uses def for local corpus search.

    Args:
        query: Subject words to search for.
        statute: Optional Act to restrict the search to.
        limit: Maximum results to return.

    Returns:
        Dict with the matching provisions.
    """
    try:
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")

        if not india_code.corpus_available():
            return _corpus_missing()

        if statute and india_code.resolve_act(statute) is None:
            return {
                "status": "not_found",
                "operation": "search_statute",
                "message": (
                    f"'{statute}' is not in the bundled corpus. Call "
                    "list_bundled_acts to see what is available, or drop the "
                    "statute filter to search everything."
                ),
            }

        matches = india_code.search_sections(
            query.strip(), statute=statute, limit=max(1, min(limit, 50))
        )

        results = []
        for section in matches:
            entry = section.to_dict()
            entry["snippet"] = (
                section.text[:400] + "..." if len(section.text) > 400 else section.text
            )
            entry.pop("text", None)
            results.append(entry)

        return {
            "status": "success",
            "operation": "search_statute",
            "query": query,
            "statute_filter": statute,
            "results": results,
            "result_count": len(results),
            "message": (
                f"Found {len(results)} provisions. This searches only the bundled "
                "corpus, so absence here is not proof that no such provision "
                "exists. Read the full text of anything you rely on with get_section."
            ),
        }

    except Exception as e:
        logger.error(f"Error in search_statute: {e}")
        return {
            "status": "error",
            "operation": "search_statute",
            "error": str(e),
            "message": "Failed to search statutes",
        }


def map_criminal_code_section(
    section: str,
    direction: str = "auto",
    domain: Optional[str] = None,
    offence_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Translate between the IPC/CrPC/Evidence Act and the BNS/BNSS/BSA.

    TOOL_NAME=map_criminal_code_section
    DISPLAY_NAME=Old-New Criminal Code Concordance
    USECASE=Find the corresponding provision after the 1 July 2024 replacement of the IPC, CrPC and Evidence Act, and determine which code actually governs an offence
    INSTRUCTIONS=1. Give the section number, 2. Give the offence date whenever you have one - it decides which code applies, 3. Report BOTH the old and new provision when advising, 4. Read any note on the mapping: several are substantive changes, not renumberings
    INPUT_DESCRIPTION=section (string, required): e.g. "420", "138", "482". direction (string, optional): "old_to_new", "new_to_old" or "auto" (default). domain (string, optional): "penal", "procedure" or "evidence" to disambiguate a number used in more than one code. offence_date (string, optional): YYYY-MM-DD, to determine the governing regime.
    OUTPUT_DESCRIPTION=Dictionary with status, matching mappings (old and new code and section, subject, note), the applicable regime when an offence date is given, and a coverage caveat
    EXAMPLES=map_criminal_code_section("420", offence_date="2024-03-15"), map_criminal_code_section("318", direction="new_to_old"), map_criminal_code_section("482", domain="procedure")
    PREREQUISITES=None - fully offline
    RELATED_TOOLS=get_section to read either provision; search_statute to find a provision by subject

    CPU-bound operation - uses def for local table lookup.

    Args:
        section: Section number to translate.
        direction: Which way to translate, or "auto" to try both.
        domain: Optional restriction to penal, procedure or evidence.
        offence_date: Optional offence date in YYYY-MM-DD form.

    Returns:
        Dict with the mappings and the governing regime.
    """
    try:
        if not section or not str(section).strip():
            raise ValueError("section must be a non-empty value")
        if direction not in {"auto", "old_to_new", "new_to_old"}:
            raise ValueError("direction must be 'auto', 'old_to_new' or 'new_to_old'")
        if domain is not None and domain not in ncc.CODE_PAIRS:
            raise ValueError(
                f"domain must be one of {sorted(ncc.CODE_PAIRS)} or omitted"
            )

        regime: Optional[Dict[str, Any]] = None
        if offence_date:
            try:
                parsed = datetime.strptime(offence_date, "%Y-%m-%d").date()
            except ValueError as e:
                raise ValueError(
                    f"offence_date must be YYYY-MM-DD, got '{offence_date}'"
                ) from e
            regime = ncc.applicable_code(parsed)

        old_to_new = (
            ncc.map_old_to_new(str(section), domain)
            if direction in {"auto", "old_to_new"}
            else []
        )
        new_to_old = (
            ncc.map_new_to_old(str(section), domain)
            if direction in {"auto", "new_to_old"}
            else []
        )

        mappings = [{"direction": "old_to_new", **m.to_dict()} for m in old_to_new] + [
            {"direction": "new_to_old", **m.to_dict()} for m in new_to_old
        ]

        if not mappings:
            return {
                "status": "not_found",
                "operation": "map_criminal_code_section",
                "section": str(section),
                "applicable_regime": regime,
                "coverage": ncc.coverage(),
                "message": (
                    f"Section {section} is not in the curated concordance, which "
                    f"covers {ncc.coverage()['total']} of the most-used provisions "
                    "rather than the complete official mapping. Consult the "
                    "official IPC-BNS concordance before charging or advising on "
                    "this section - do not guess the equivalent."
                ),
            }

        substantive = [m for m in mappings if m.get("note")]

        return {
            "status": "success",
            "operation": "map_criminal_code_section",
            "section": str(section),
            "mappings": mappings,
            "mapping_count": len(mappings),
            "applicable_regime": regime,
            "commencement_date": ncc.NEW_CODES_COMMENCEMENT.isoformat(),
            "substantive_changes": substantive,
            "message": (
                f"Found {len(mappings)} mapping(s)."
                + (
                    f" The offence date places this under the {regime['regime']} "
                    f"regime: {regime['penal_code']}."
                    if regime
                    else " No offence date was given - establish it, because it "
                    "decides which code governs."
                )
                + (
                    " At least one mapping is a substantive change rather than a "
                    "renumbering; read the note before relying on it."
                    if substantive
                    else ""
                )
            ),
        }

    except Exception as e:
        logger.error(f"Error in map_criminal_code_section: {e}")
        return {
            "status": "error",
            "operation": "map_criminal_code_section",
            "error": str(e),
            "message": "Failed to map criminal code section",
        }


def which_criminal_code_applies(offence_date: str) -> Dict[str, Any]:
    """State which criminal codes govern an offence committed on a given date.

    TOOL_NAME=which_criminal_code_applies
    DISPLAY_NAME=Governing Criminal Code
    USECASE=Settle whether the IPC/CrPC/Evidence Act or the BNS/BNSS/BSA applies before drafting a charge, complaint, bail application or opinion
    INSTRUCTIONS=1. Establish the date the offence was committed, 2. Call this tool, 3. Use the named codes for every provision cited thereafter
    INPUT_DESCRIPTION=offence_date (string, required): date of the offence in YYYY-MM-DD form
    OUTPUT_DESCRIPTION=Dictionary with status, the regime (old or new), the governing penal, procedural and evidence statutes, the reasoning, and a caveat about pending proceedings
    EXAMPLES=which_criminal_code_applies("2024-06-30"), which_criminal_code_applies("2024-07-01")
    PREREQUISITES=None - fully offline
    RELATED_TOOLS=map_criminal_code_section to translate a specific section once the regime is known

    CPU-bound operation - uses def for date comparison.

    Args:
        offence_date: Date of the offence, YYYY-MM-DD.

    Returns:
        Dict naming the governing codes and explaining why.
    """
    try:
        try:
            parsed: date = datetime.strptime(offence_date, "%Y-%m-%d").date()
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"offence_date must be YYYY-MM-DD, got '{offence_date}'"
            ) from e

        regime = ncc.applicable_code(parsed)
        return {
            "status": "success",
            "operation": "which_criminal_code_applies",
            **regime,
            "message": regime["reason"],
        }

    except Exception as e:
        logger.error(f"Error in which_criminal_code_applies: {e}")
        return {
            "status": "error",
            "operation": "which_criminal_code_applies",
            "error": str(e),
            "message": "Failed to determine the applicable criminal code",
        }


def list_bundled_acts(include_sections: bool = False) -> Dict[str, Any]:
    """List the Acts available offline and how completely each is covered.

    TOOL_NAME=list_bundled_acts
    DISPLAY_NAME=Statute Corpus Coverage
    USECASE=Check whether an Act can be consulted offline before asserting what it says, and see which Acts are only partially bundled
    INSTRUCTIONS=1. Call before relying on a statutory lookup for an unfamiliar Act, 2. Treat a 'partial' Act as an extract - a section missing from it may still exist
    INPUT_DESCRIPTION=include_sections (bool, optional, default False): also list every section number and heading per Act
    OUTPUT_DESCRIPTION=Dictionary with status, the Acts with title, coverage, section count and source, plus totals and the corpus path
    EXAMPLES=list_bundled_acts(), list_bundled_acts(include_sections=True)
    PREREQUISITES=None
    RELATED_TOOLS=get_section and search_statute both read this same corpus

    CPU-bound operation - uses def for local corpus inspection.

    Args:
        include_sections: Whether to enumerate section numbers and headings.

    Returns:
        Dict describing corpus coverage.
    """
    try:
        acts = india_code.list_acts()
        if not acts:
            return _corpus_missing()

        report = india_code.coverage_report()
        return {
            "status": "success",
            "operation": "list_bundled_acts",
            "acts": [a.to_dict(include_sections=include_sections) for a in acts],
            **report,
            "concordance_coverage": ncc.coverage(),
            "message": (
                f"{report['act_count']} Acts bundled with "
                f"{report['section_count']} sections. Acts marked 'partial' hold "
                "curated extracts only, and their section text is a summary rather "
                "than the statute's own words - never quote a summary as statutory "
                "text."
            ),
        }

    except Exception as e:
        logger.error(f"Error in list_bundled_acts: {e}")
        return {
            "status": "error",
            "operation": "list_bundled_acts",
            "error": str(e),
            "message": "Failed to list bundled Acts",
        }


TOOLS: List[Any] = [
    get_section,
    search_statute,
    map_criminal_code_section,
    which_criminal_code_applies,
    list_bundled_acts,
]
