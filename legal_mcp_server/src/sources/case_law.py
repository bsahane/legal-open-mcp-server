"""Backend-agnostic case-law access for the Legal MCP Server.

The research tools do not care which corpus answers a query; they care that an
answer came from a real lookup. This module picks the backend from
``CASE_LAW_SOURCE`` and presents one interface over both:

* ``open_data`` (default) - the free AWS Open Data judgment corpus. No API key,
  no per-query cost, works offline once synced.
* ``indian_kanoon`` - the paid api.indiankanoon.org, opt-in only.

Every response carries a ``backend`` key so the caller can tell the user where
an authority came from, and a ``cost`` note so the free path is never mistaken
for a billed one.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from legal_mcp_server.src.settings import settings
from legal_mcp_server.src.sources import open_judgments
from legal_mcp_server.src.sources.open_judgments import (
    CorpusNotSynced,
    SourceUnavailable,
)
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()

__all__ = [
    "SourceUnavailable",
    "CorpusNotSynced",
    "CaseLawDisabled",
    "active_backend",
    "search",
    "get_judgment",
    "find_by_citation",
    "find_related_proceedings",
    "search_within_judgment",
    "status",
]


class CaseLawDisabled(SourceUnavailable):
    """Raised when case-law tools are switched off by configuration."""


def active_backend() -> str:
    """Name of the configured case-law backend."""
    return settings.CASE_LAW_SOURCE


def _require_enabled() -> str:
    """Return the active backend, or raise if case law is disabled."""
    backend = active_backend()
    if backend == "disabled":
        raise CaseLawDisabled(
            "Case-law tools are disabled (CASE_LAW_SOURCE='disabled'). Set it to "
            "'open_data' for the free corpus."
        )
    return backend


def _cost_note(backend: str) -> str:
    """Human-readable cost statement for a backend."""
    if backend == "open_data":
        return "free - public open data, no API key, no per-query charge"
    return "billed - Indian Kanoon charges per search and per document"


async def search(
    query: str,
    court: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    judge: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
) -> Dict[str, Any]:
    """Search case law using the configured backend.

    Args:
        query: Search terms expressing the legal proposition.
        court: Court name, alias or code.
        from_date: Inclusive lower bound, ``YYYY-MM-DD``.
        to_date: Inclusive upper bound, ``YYYY-MM-DD``.
        judge: Restrict to a judge whose name contains this.
        limit: Maximum results (open-data backend).
        page: Zero-based page (Indian Kanoon backend).

    Returns:
        Dict with ``results``, ``backend``, ``cost`` and backend metadata.
    """
    backend = _require_enabled()

    if backend == "open_data":
        open_client = open_judgments.get_client()
        results = await open_client.search(
            query=query,
            court=court,
            from_date=from_date,
            to_date=to_date,
            judge=judge,
            limit=limit,
        )
        return {
            "backend": backend,
            "cost": _cost_note(backend),
            "results": [r.to_dict() for r in results],
            "found": len(results),
            "query": query,
            "page": 0,
            "attribution": open_judgments.ATTRIBUTION,
            "scope_note": (
                "Search covers case metadata (party names, case titles, judges) "
                "for the courts and years synced locally, not the full text of "
                "every judgment. Widen coverage with sync_case_law."
            ),
        }

    from legal_mcp_server.src.sources import indian_kanoon

    ik_client = indian_kanoon.get_client()
    payload = await ik_client.search(
        query=query,
        page=page,
        court=court,
        from_date=from_date,
        to_date=to_date,
        author=judge,
    )
    return {
        "backend": backend,
        "cost": _cost_note(backend),
        "results": payload["results"],
        "found": payload.get("found"),
        "query": payload["query"],
        "page": payload["page"],
        "spend": ik_client.spend_report(),
    }


async def get_judgment(doc_id: str) -> Dict[str, Any]:
    """Retrieve one judgment in full.

    Args:
        doc_id: Identifier returned by :func:`search`.

    Returns:
        Dict describing the judgment, including its text.
    """
    backend = _require_enabled()

    if backend == "open_data":
        open_client = open_judgments.get_client()
        open_judgment = await open_client.get_judgment(str(doc_id))
        payload = open_judgment.to_dict()
        payload["backend"] = backend
        payload["cost"] = _cost_note(backend)
        return payload

    from legal_mcp_server.src.sources import indian_kanoon

    ik_client = indian_kanoon.get_client()
    ik_judgment = await ik_client.get_document(int(doc_id))
    payload = ik_judgment.to_dict()
    payload["backend"] = backend
    payload["cost"] = _cost_note(backend)
    payload["spend"] = ik_client.spend_report()
    return payload


async def find_by_citation(citation: str) -> Dict[str, Any]:
    """Resolve a citation to the judgment it refers to.

    Args:
        citation: Citation text, e.g. ``[2024] 10 S.C.R. 108`` or ``2024INSC735``.

    Returns:
        Dict with ``results`` and an ``exact`` flag indicating whether the
        backend matched on a real citation field rather than by text search.
    """
    backend = _require_enabled()

    if backend == "open_data":
        open_client = open_judgments.get_client()
        results = await open_client.find_by_citation(citation)
        return {
            "backend": backend,
            "cost": _cost_note(backend),
            "results": [r.to_dict() for r in results],
            "exact": True,
            "note": (
                "Matched against the official S.C.R. and neutral-citation fields "
                "in the Supreme Court open dataset."
            ),
        }

    payload = await search(query=citation)
    payload["exact"] = False
    payload["note"] = "Matched by full-text search, not a citation field."
    return payload


async def find_related_proceedings(
    doc_id: str, limit: int = 20
) -> Dict[str, Any]:
    """Find other proceedings sharing this case's party names.

    This is deliberately *not* a citator. The open corpus has no citation graph,
    so this surfaces connected matters - appeals, reviews, contempt petitions,
    companion writs - by matching party names. It does not tell you whether a
    judgment has been followed, distinguished or overruled.

    Args:
        doc_id: Identifier of the judgment to find relatives of.
        limit: Maximum results.

    Returns:
        Dict with ``results`` and an explicit note on what the list means.
    """
    backend = _require_enabled()

    if backend == "indian_kanoon":
        from legal_mcp_server.src.sources import indian_kanoon

        ik_client = indian_kanoon.get_client()
        ik_judgment = await ik_client.get_document(int(doc_id))
        return {
            "backend": backend,
            "cost": _cost_note(backend),
            "results": ik_judgment.cited_by[:limit],
            "is_citator": True,
            "note": "These judgments cite the subject judgment.",
        }

    open_client = open_judgments.get_client()
    judgment = await open_client.get_judgment(str(doc_id))

    parties = _party_terms(judgment.title)
    if not parties:
        return {
            "backend": backend,
            "cost": _cost_note(backend),
            "results": [],
            "is_citator": False,
            "note": (
                "Could not extract party names from the case title, so no related "
                "proceedings could be looked up."
            ),
        }

    results = await open_client.search(query=" ".join(parties), limit=limit + 1)
    filtered = [r.to_dict() for r in results if r.doc_id != str(doc_id)][:limit]

    return {
        "backend": backend,
        "cost": _cost_note(backend),
        "results": filtered,
        "is_citator": False,
        "matched_on": parties,
        "note": (
            "NOT a citator. These are other proceedings involving the same party "
            "names - appeals, reviews or connected matters. This does NOT show "
            "which judgments cite, follow, distinguish or overrule this one, and "
            "it is not a substitute for checking whether the judgment is still "
            "good law."
        ),
    }


def _party_terms(title: str) -> List[str]:
    """Pull the most distinctive party words out of a case title."""
    if not title:
        return []

    cleaned = re.sub(r"^[A-Z]+/\d+/\d+\s+of\s+", "", title)
    halves = re.split(r"\s+(?:versus|vs\.?|v\.?)\s+", cleaned, flags=re.IGNORECASE)

    stop = {
        "the", "of", "and", "ors", "anr", "state", "union", "india", "ltd",
        "limited", "pvt", "private", "company", "co", "through", "another",
        "others", "dec", "no", "nos",
    }
    terms: List[str] = []
    for half in halves[:2]:
        words = [w for w in re.findall(r"[A-Za-z]{4,}", half) if w.lower() not in stop]
        terms.extend(words[:2])

    return terms[:3]


async def search_within_judgment(doc_id: str, query: str) -> Dict[str, Any]:
    """Locate passages matching a query inside one judgment.

    Args:
        doc_id: Identifier of the judgment to search inside.
        query: Terms to locate.

    Returns:
        Dict with matching passages and their character offsets.
    """
    backend = _require_enabled()

    if backend == "indian_kanoon":
        from legal_mcp_server.src.sources import indian_kanoon

        ik_client = indian_kanoon.get_client()
        payload = await ik_client.get_fragments(int(doc_id), query)
        payload["backend"] = backend
        payload["cost"] = _cost_note(backend)
        return payload

    open_client = open_judgments.get_client()
    judgment = await open_client.get_judgment(str(doc_id))
    text = judgment.text

    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    passages: List[Dict[str, Any]] = []

    for match in re.finditer("|".join(re.escape(t) for t in terms), text, re.IGNORECASE):
        start = max(0, match.start() - 300)
        end = min(len(text), match.end() + 300)
        passages.append(
            {
                "offset": match.start(),
                "matched": match.group(0),
                "passage": text[start:end].strip(),
            }
        )
        if len(passages) >= 20:
            break

    return {
        "backend": backend,
        "cost": _cost_note(backend),
        "doc_id": doc_id,
        "title": judgment.title,
        "url": judgment.url,
        "passages": passages,
        "match_count": len(passages),
        "note": (
            "Passages are matched literally against the judgment text extracted "
            "from the official PDF."
        ),
    }


def status() -> Dict[str, Any]:
    """Describe the configured backend and what it can currently answer."""
    backend = active_backend()

    if backend == "disabled":
        return {
            "backend": backend,
            "available": False,
            "message": "Case-law tools are disabled by configuration.",
        }

    if backend == "open_data":
        open_client = open_judgments.get_client()
        report = open_client.corpus_report()
        return {
            "backend": backend,
            "available": report["synced"],
            "cost": _cost_note(backend),
            **report,
            "message": (
                "Free open-data case law is ready."
                if report["synced"]
                else "No corpus synced yet. Run sync_case_law to download metadata."
            ),
        }

    from legal_mcp_server.src.sources import indian_kanoon

    ik_client = indian_kanoon.get_client()
    return {
        "backend": backend,
        "available": ik_client.available,
        "cost": _cost_note(backend),
        "spend": ik_client.spend_report(),
        "message": "Paid Indian Kanoon backend is active.",
    }
