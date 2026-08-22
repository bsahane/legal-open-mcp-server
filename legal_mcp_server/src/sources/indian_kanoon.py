"""Client for the Indian Kanoon API (api.indiankanoon.org).

Indian Kanoon indexes roughly 30 million Indian judgments and is the primary
case-law source for this server. Every call is metered and billed, so this
module adds three things on top of the raw HTTP API:

* a per-day spend cap, enforced before the request goes out and mirrored to
  disk so restarting the server cannot bypass it;
* an in-process response cache, so repeated lookups within a session are free;
* a uniform ``SourceUnavailable`` failure mode, so tools can report honestly
  that they could not consult the source instead of answering from memory.

All Indian Kanoon endpoints are POST with an ``Authorization: Token <key>``
header, per the official ikapi.py reference client.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx

from legal_mcp_server.src.settings import settings
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()

# Published Indian Kanoon per-call pricing, in INR.
COST_SEARCH_INR = 0.50
COST_DOCUMENT_INR = 0.20
COST_FRAGMENT_INR = 0.05
COST_METADATA_INR = 0.05

CACHE_TTL_SECONDS = 60 * 60 * 6
REQUEST_TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 3

#: Name of the JSON file mirroring the day's spend under
#: ``<LEGAL_DATA_PATH>/cache/``.
LEDGER_FILENAME = "indian_kanoon_spend.json"


class SourceUnavailable(RuntimeError):
    """Raised when Indian Kanoon cannot be consulted at all.

    Distinct from "the search returned nothing": callers must surface this to
    the user rather than treating it as an absence of authority.
    """


class BudgetExceeded(SourceUnavailable):
    """Raised when a call would push today's spend past the configured cap."""


@dataclass
class SpendLedger:
    """Tracks Indian Kanoon spend for the current UTC day.

    When ``path`` is set, the day's totals are mirrored to disk after every
    recorded call and adopted back on construction, so a server restart
    cannot reset today's spend and slip past the configured cap. I/O
    problems are logged and swallowed: an unreadable ledger must never
    block a billable call outright.
    """

    day: date = field(default_factory=lambda: datetime.now(timezone.utc).date())
    spent_inr: float = 0.0
    calls: int = 0
    path: Optional[Path] = None

    def __post_init__(self) -> None:
        """Adopt today's persisted totals from disk when a path is set."""
        self._load()

    def _load(self) -> None:
        """Adopt today's persisted totals, ignoring stale or broken state."""
        if self.path is None:
            return
        try:
            raw = json.loads(self.path.read_text())
            if date.fromisoformat(raw["day"]) == self.day:
                self.spent_inr = float(raw["spent_inr"])
                self.calls = int(raw["calls"])
        except FileNotFoundError:
            return
        except Exception as e:
            logger.warning(
                f"Ignoring unreadable Indian Kanoon spend ledger {self.path}: {e}"
            )

    def _save(self) -> None:
        """Mirror the current totals to disk atomically; never raise."""
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "day": self.day.isoformat(),
                        "spent_inr": round(self.spent_inr, 4),
                        "calls": self.calls,
                    }
                )
            )
            os.replace(tmp, self.path)
        except Exception as e:
            logger.warning(f"Could not persist Indian Kanoon spend ledger: {e}")

    def _roll_over(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self.day:
            self.day = today
            self.spent_inr = 0.0
            self.calls = 0
            self._save()

    def check(self, cost_inr: float, budget_inr: float) -> None:
        """Raise if spending ``cost_inr`` would breach ``budget_inr``.

        Args:
            cost_inr: Cost of the call about to be made.
            budget_inr: Configured daily cap.

        Raises:
            BudgetExceeded: If the call would take the day's spend over budget.
        """
        self._roll_over()
        if self.spent_inr + cost_inr > budget_inr:
            raise BudgetExceeded(
                f"Indian Kanoon daily budget of Rs {budget_inr:.2f} would be exceeded "
                f"(spent Rs {self.spent_inr:.2f} across {self.calls} calls today; "
                f"this call costs Rs {cost_inr:.2f}). Raise "
                f"INDIAN_KANOON_DAILY_BUDGET_INR or continue tomorrow."
            )

    def record(self, cost_inr: float) -> None:
        """Record a completed billable call."""
        self._roll_over()
        self.spent_inr += cost_inr
        self.calls += 1
        self._save()

    def snapshot(self) -> Dict[str, Any]:
        """Return the current day's spend for reporting in tool output."""
        self._roll_over()
        return {
            "date": self.day.isoformat(),
            "spent_inr": round(self.spent_inr, 2),
            "calls": self.calls,
            "budget_inr": settings.INDIAN_KANOON_DAILY_BUDGET_INR,
            "remaining_inr": round(
                max(0.0, settings.INDIAN_KANOON_DAILY_BUDGET_INR - self.spent_inr), 2
            ),
        }


@dataclass
class SearchResult:
    """One hit from an Indian Kanoon search."""

    doc_id: int
    title: str
    court: Optional[str]
    date: Optional[str]
    snippet: str
    url: str

    def to_dict(self) -> Dict[str, Any]:
        """Serialise for MCP tool output."""
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "court": self.court,
            "date": self.date,
            "snippet": self.snippet,
            "url": self.url,
        }


@dataclass
class Judgment:
    """A full judgment retrieved by document id."""

    doc_id: int
    title: str
    court: Optional[str]
    date: Optional[str]
    bench: Optional[str]
    text: str
    citations: List[Dict[str, Any]]
    cited_by: List[Dict[str, Any]]
    url: str

    def to_dict(self) -> Dict[str, Any]:
        """Serialise for MCP tool output."""
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "court": self.court,
            "date": self.date,
            "bench": self.bench,
            "text": self.text,
            "cites": self.citations,
            "cited_by": self.cited_by,
            "url": self.url,
        }


def _doc_url(doc_id: int) -> str:
    """Public Indian Kanoon URL for a document id."""
    return f"https://indiankanoon.org/doc/{doc_id}/"


def _strip_html(value: Optional[str]) -> str:
    """Remove Indian Kanoon's inline markup from a snippet or title.

    Indian Kanoon wraps search-term matches in ``<b>`` and separates fragments
    with ``<br>``; neither is useful once the text reaches a model.
    """
    if not value:
        return ""

    import re

    text = re.sub(r"<br\s*/?>", " ", value)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())


class IndianKanoonClient:
    """Async client for the Indian Kanoon API with budget and cache control."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        ledger_path: Optional[Path] = None,
    ):
        """Create a client.

        Args:
            api_key: Indian Kanoon token. Defaults to the configured key.
            base_url: API base URL. Defaults to the configured URL.
            transport: Optional httpx transport, used to inject mocks in tests.
            ledger_path: Optional file the spend ledger mirrors to. Leave
                ``None`` for an in-memory-only ledger (tests); the shared
                client passes a real path so restarts cannot reset spend.
        """
        self._api_key = (
            api_key if api_key is not None else settings.INDIAN_KANOON_API_KEY
        )
        self._base_url = (base_url or settings.INDIAN_KANOON_BASE_URL).rstrip("/")
        self._transport = transport
        self._cache: Dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()
        self.ledger = SpendLedger(path=ledger_path)
        # Long-lived client so connection pools and TLS sessions survive across
        # calls; creating a fresh AsyncClient per request forces a TCP+TLS
        # handshake every time. Created lazily so tests that never hit the
        # network do not construct one.
        self._http: Optional[httpx.AsyncClient] = None

    def _get_http(self) -> httpx.AsyncClient:
        """Return the shared HTTP client, creating it on first use."""
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                transport=self._transport,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._http

    async def close(self) -> None:
        """Close the shared HTTP client, releasing its connection pool."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    @property
    def available(self) -> bool:
        """Whether the client is configured well enough to make a call."""
        return bool(self._api_key) and settings.INDIAN_KANOON_DAILY_BUDGET_INR > 0

    def _require_available(self) -> None:
        if not self._api_key:
            raise SourceUnavailable(
                "INDIAN_KANOON_API_KEY is not configured, so case law cannot be "
                "consulted. Obtain a token at https://api.indiankanoon.org/ and set "
                "the environment variable. Do not substitute recalled case law for "
                "a real search."
            )
        if settings.INDIAN_KANOON_DAILY_BUDGET_INR <= 0:
            raise BudgetExceeded(
                "INDIAN_KANOON_DAILY_BUDGET_INR is 0, so all paid case-law calls "
                "are disabled."
            )

    def _cache_get(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if time.monotonic() - stored_at > CACHE_TTL_SECONDS:
            self._cache.pop(key, None)
            return None
        return value

    def _cache_put(self, key: str, value: Any) -> None:
        self._cache[key] = (time.monotonic(), value)

    async def _post(self, path: str, cost_inr: float) -> Dict[str, Any]:
        """POST to an Indian Kanoon endpoint, honouring cache and budget.

        Args:
            path: Path beginning with ``/``, query string already encoded.
            cost_inr: Published price of this endpoint, for the spend ledger.

        Returns:
            The decoded JSON body.

        Raises:
            SourceUnavailable: On misconfiguration, budget exhaustion, or a
                network or API failure that survives retries.
        """
        self._require_available()

        cached = self._cache_get(path)
        if cached is not None:
            logger.debug(f"Indian Kanoon cache hit: {path}")
            return cached

        async with self._lock:
            # Re-check inside the lock: a concurrent caller may have filled it.
            cached = self._cache_get(path)
            if cached is not None:
                return cached

            self.ledger.check(cost_inr, settings.INDIAN_KANOON_DAILY_BUDGET_INR)

            headers = {
                "Authorization": f"Token {self._api_key}",
                "Accept": "application/json",
            }

            last_error: Optional[Exception] = None
            client = self._get_http()
            for attempt in range(MAX_RETRIES):
                try:
                    response = await client.post(path, headers=headers)
                    if response.status_code == 401:
                        raise SourceUnavailable(
                            "Indian Kanoon rejected the API token (401). Check "
                            "INDIAN_KANOON_API_KEY."
                        )
                    if response.status_code == 429:
                        await asyncio.sleep(2**attempt)
                        last_error = SourceUnavailable(
                            "Indian Kanoon rate limit (429)."
                        )
                        continue
                    response.raise_for_status()
                    payload = response.json()
                except SourceUnavailable:
                    raise
                except Exception as e:  # noqa: BLE001 - retried below
                    last_error = e
                    logger.warning(
                        f"Indian Kanoon call failed (attempt {attempt + 1}"
                        f"/{MAX_RETRIES}): {path}: {e}"
                    )
                    await asyncio.sleep(2**attempt)
                    continue

                # The API reports some failures as a 200 with an error body.
                if isinstance(payload, dict) and payload.get("errmsg"):
                    raise SourceUnavailable(
                        f"Indian Kanoon returned an error: {payload['errmsg']}"
                    )

                self.ledger.record(cost_inr)
                self._cache_put(path, payload)
                return payload

            raise SourceUnavailable(
                f"Indian Kanoon could not be reached after {MAX_RETRIES} attempts: "
                f"{last_error}"
            )

    async def search(
        self,
        query: str,
        page: int = 0,
        court: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        author: Optional[str] = None,
        doc_types: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run a case-law search.

        Args:
            query: Search terms. Indian Kanoon operators are supported, so
                ``"cheque dishonour" AND "section 138"`` works as written.
            page: Zero-based results page.
            court: Court filter, e.g. ``bombay``, ``supremecourt``, ``delhi``.
            from_date: Lower bound as ``DD-MM-YYYY``.
            to_date: Upper bound as ``DD-MM-YYYY``.
            author: Judge name filter.
            doc_types: Document-type filter, e.g. ``judgments``.

        Returns:
            Dict with ``results`` (list of SearchResult dicts), ``found``, and
            the raw ``query`` actually sent.
        """
        terms = [query]
        if court:
            terms.append(f"doctypes:{court}")
        if doc_types:
            terms.append(f"doctypes:{doc_types}")
        if from_date:
            terms.append(f"fromdate:{from_date}")
        if to_date:
            terms.append(f"todate:{to_date}")
        if author:
            terms.append(f"author:{author}")

        full_query = " ".join(terms)
        path = f"/search/?formInput={quote_plus(full_query)}&pagenum={page}"

        payload = await self._post(path, COST_SEARCH_INR)

        results = [
            SearchResult(
                doc_id=int(doc["tid"]),
                title=_strip_html(doc.get("title")),
                court=doc.get("docsource"),
                date=doc.get("publishdate"),
                snippet=_strip_html(doc.get("headline")),
                url=_doc_url(int(doc["tid"])),
            ).to_dict()
            for doc in payload.get("docs", [])
            if doc.get("tid") is not None
        ]

        return {
            "results": results,
            "found": payload.get("found"),
            "query": full_query,
            "page": page,
        }

    async def get_document(
        self, doc_id: int, max_cites: int = 20, max_cited_by: int = 20
    ) -> Judgment:
        """Fetch a full judgment by document id.

        Args:
            doc_id: Indian Kanoon document id.
            max_cites: Maximum authorities-cited entries to return.
            max_cited_by: Maximum citing-cases entries to return.

        Returns:
            The judgment, including text and citation graph edges.
        """
        path = f"/doc/{doc_id}/?maxcites={max_cites}&maxcitedby={max_cited_by}"
        payload = await self._post(path, COST_DOCUMENT_INR)

        return Judgment(
            doc_id=doc_id,
            title=_strip_html(payload.get("title")),
            court=payload.get("docsource"),
            date=payload.get("publishdate"),
            bench=payload.get("bench") or payload.get("author"),
            text=_strip_html(payload.get("doc", "")),
            citations=payload.get("citeList", []) or [],
            cited_by=payload.get("citedbyList", []) or [],
            url=_doc_url(doc_id),
        )

    async def get_metadata(self, doc_id: int) -> Dict[str, Any]:
        """Fetch judgment metadata without the full text.

        Cheaper than :meth:`get_document` and sufficient for verifying that a
        citation resolves to a real decision.
        """
        path = f"/docmeta/{doc_id}/?maxcites=5&maxcitedby=5"
        payload = await self._post(path, COST_METADATA_INR)

        return {
            "doc_id": doc_id,
            "title": _strip_html(payload.get("title")),
            "court": payload.get("docsource"),
            "date": payload.get("publishdate"),
            "bench": payload.get("bench") or payload.get("author"),
            "cited_by_count": payload.get("numcitedby"),
            "cites_count": payload.get("numcites"),
            "url": _doc_url(doc_id),
        }

    async def get_fragments(self, doc_id: int, query: str) -> Dict[str, Any]:
        """Find passages inside one judgment that match a query.

        The cheapest endpoint at Rs 0.05. Prefer it over a full document fetch
        when the question is "where does this judgment say X".

        Args:
            doc_id: Indian Kanoon document id.
            query: Terms to locate within the judgment.

        Returns:
            Dict with ``fragments`` (list of matching passages) and the title.
        """
        path = f"/docfragment/{doc_id}/?formInput={quote_plus(query)}"
        payload = await self._post(path, COST_FRAGMENT_INR)

        headlines = payload.get("headline", [])
        if isinstance(headlines, str):
            headlines = [headlines]

        return {
            "doc_id": doc_id,
            "title": _strip_html(payload.get("title")),
            "fragments": [_strip_html(h) for h in headlines if h],
            "url": _doc_url(doc_id),
        }

    def spend_report(self) -> Dict[str, Any]:
        """Today's Indian Kanoon spend against the configured cap."""
        return self.ledger.snapshot()


_client: Optional[IndianKanoonClient] = None


def get_client() -> IndianKanoonClient:
    """Return the process-wide Indian Kanoon client.

    Sharing one instance keeps the response cache and the spend ledger
    effective across tool calls within a session. The shared client also
    persists the day's spend under ``<LEGAL_DATA_PATH>/cache/`` so a
    restart cannot bypass the daily cap; directly constructed clients
    (tests) keep an in-memory-only ledger.
    """
    global _client
    if _client is None:
        _client = IndianKanoonClient(
            ledger_path=Path(settings.LEGAL_DATA_PATH) / "cache" / LEDGER_FILENAME,
        )
    return _client


def reset_client() -> None:
    """Drop the shared client. Used by tests and after a settings change."""
    global _client
    if _client is not None:
        try:
            asyncio.run(_client.close())
        except RuntimeError:
            pass  # a loop is already running; leave cleanup to GC
    _client = None


async def aclose_client() -> None:
    """Close and drop the shared client if one exists (server shutdown).

    A no-op when nothing was instantiated; safe to call from a running loop.
    """
    global _client
    if _client is not None:
        await _client.close()
        _client = None
