"""Free, open-access Indian case law from the AWS Open Data registry.

This is the default case-law backend and it costs nothing to query. Two public
S3 buckets, sponsored by AWS and maintained by Dattam Labs, hold judgments
scraped from the eCourts platform and released under CC-BY-4.0:

* ``indian-supreme-court-judgments`` - Supreme Court, 1950 to present, with
  official S.C.R. citations and neutral citations (e.g. ``2024INSC735``).
* ``indian-high-court-judgments``    - 25 High Courts / 45 benches, ~17.8M
  judgments.

Both allow anonymous reads, so no AWS account, credentials or API key is
needed. Rather than depend on a paid search API, this module works in two
steps:

1. ``sync`` downloads the small Parquet *metadata* files for the courts and
   years the user cares about (tens of MB, not the 1.25 TiB of PDFs).
2. ``search`` runs DuckDB SQL over that local Parquet. Queries are then
   instant, offline, unlimited and free.

Judgment PDFs are fetched individually over plain HTTPS only when a specific
judgment is opened, and cached on disk.

Attribution (required by CC-BY-4.0) is returned with every result.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.etree import ElementTree

import httpx

from legal_mcp_server.src.settings import settings
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()

S3_NAMESPACE = "{http://s3.amazonaws.com/doc/2006-03-01/}"

#: HTTP statuses worth retrying with backoff: throttling and transient
#: upstream failures. Any other status is returned to the caller unchanged.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

#: Attempts made by the S3/PDF fetch helper before giving up.
MAX_RETRIES = 3

ATTRIBUTION = (
    "Source: Indian Supreme Court / High Court Judgments open dataset "
    "(AWS Open Data, maintained by Dattam Labs), licensed CC-BY-4.0. "
    "Derived from the eCourts platform."
)

#: Court code -> canonical High Court name. Bench codes are discovered from S3.
HIGH_COURTS: Dict[str, str] = {
    "9_13": "Allahabad High Court",
    "27_1": "Bombay High Court",
    "19_16": "Calcutta High Court",
    "18_6": "Gauhati High Court",
    "36_29": "High Court for State of Telangana",
    "28_2": "High Court of Andhra Pradesh",
    "22_18": "High Court of Chhattisgarh",
    "7_26": "High Court of Delhi",
    "24_17": "High Court of Gujarat",
    "2_5": "High Court of Himachal Pradesh",
    "1_12": "High Court of Jammu and Kashmir",
    "20_7": "High Court of Jharkhand",
    "29_3": "High Court of Karnataka",
    "32_4": "High Court of Kerala",
    "23_23": "High Court of Madhya Pradesh",
    "14_25": "High Court of Manipur",
    "17_21": "High Court of Meghalaya",
    "21_11": "High Court of Orissa",
    "3_22": "High Court of Punjab and Haryana",
    "8_9": "High Court of Rajasthan",
    "11_24": "High Court of Sikkim",
    "16_20": "High Court of Tripura",
    "5_15": "High Court of Uttarakhand",
    "33_10": "Madras High Court",
    "10_8": "Patna High Court",
}

#: Friendly aliases accepted by the tools, mapped to court codes.
COURT_ALIASES: Dict[str, str] = {
    "supreme court": "SC",
    "supreme court of india": "SC",
    "sc": "SC",
    "sci": "SC",
    "bombay": "27_1",
    "bombay high court": "27_1",
    "bombay hc": "27_1",
    "mumbai": "27_1",
    "delhi": "7_26",
    "delhi high court": "7_26",
    "madras": "33_10",
    "chennai": "33_10",
    "calcutta": "19_16",
    "kolkata": "19_16",
    "karnataka": "29_3",
    "bangalore": "29_3",
    "bengaluru": "29_3",
    "kerala": "32_4",
    "allahabad": "9_13",
    "gujarat": "24_17",
    "madhya pradesh": "23_23",
    "punjab and haryana": "3_22",
    "rajasthan": "8_9",
    "telangana": "36_29",
    "andhra pradesh": "28_2",
    "patna": "10_8",
    "orissa": "21_11",
    "odisha": "21_11",
    "jharkhand": "20_7",
    "chhattisgarh": "22_18",
    "uttarakhand": "5_15",
    "himachal pradesh": "2_5",
    "jammu and kashmir": "1_12",
    "gauhati": "18_6",
    "guwahati": "18_6",
    "manipur": "14_25",
    "meghalaya": "17_21",
    "sikkim": "11_24",
    "tripura": "16_20",
}


class SourceUnavailable(RuntimeError):
    """Raised when the open-data corpus cannot serve a request."""


class CorpusNotSynced(SourceUnavailable):
    """Raised when no local metadata has been downloaded yet."""


def resolve_court(court: Optional[str]) -> Optional[str]:
    """Map a human court name to a court code, or ``None`` for all courts.

    Args:
        court: Court name, alias or code. ``None`` means every synced court.

    Returns:
        ``"SC"`` for the Supreme Court, a High Court code, or ``None``.
    """
    if not court:
        return None

    key = court.strip().lower()
    if key in COURT_ALIASES:
        return COURT_ALIASES[key]
    if court in HIGH_COURTS or court == "SC":
        return court

    # Tolerate "Bombay High Court at Goa" style inputs.
    for alias, code in COURT_ALIASES.items():
        if alias in key and len(alias) > 3:
            return code

    raise SourceUnavailable(
        f"Unknown court {court!r}. Known: 'Supreme Court' or one of "
        f"{', '.join(sorted(HIGH_COURTS.values()))}."
    )


def court_label(court_code: Optional[str]) -> str:
    """Human-readable court name for a court code."""
    if court_code == "SC":
        return "Supreme Court of India"
    return HIGH_COURTS.get(court_code or "", court_code or "Unknown court")


@dataclass
class SearchResult:
    """One hit from an open-data case-law search."""

    doc_id: str
    title: str
    court: Optional[str]
    date: Optional[str]
    snippet: str
    url: str
    citation: Optional[str] = None
    neutral_citation: Optional[str] = None
    judge: Optional[str] = None
    disposal: Optional[str] = None
    cnr: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise for MCP tool output."""
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "court": self.court,
            "date": self.date,
            "snippet": self.snippet,
            "url": self.url,
            "citation": self.citation,
            "neutral_citation": self.neutral_citation,
            "judge": self.judge,
            "disposal": self.disposal,
            "cnr": self.cnr,
        }


@dataclass
class Judgment:
    """A full judgment, with text extracted from the official PDF."""

    doc_id: str
    title: str
    court: Optional[str]
    date: Optional[str]
    bench: Optional[str]
    text: str
    url: str
    citation: Optional[str] = None
    neutral_citation: Optional[str] = None
    disposal: Optional[str] = None
    cnr: Optional[str] = None
    citations: List[Dict[str, Any]] = field(default_factory=list)
    cited_by: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise for MCP tool output."""
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "court": self.court,
            "date": self.date,
            "bench": self.bench,
            "text": self.text,
            "url": self.url,
            "citation": self.citation,
            "neutral_citation": self.neutral_citation,
            "disposal": self.disposal,
            "cnr": self.cnr,
            "cites": self.citations,
            "cited_by": self.cited_by,
            "attribution": ATTRIBUTION,
        }


def _sql_quote(value: str) -> str:
    """Escape a string for safe inlining into DuckDB SQL.

    DuckDB's Python API supports parameters, and those are used for user input.
    This helper is only for file paths built from validated settings.
    """
    return value.replace("'", "''")


# Above this many matches a query is listed newest first instead of being
# BM25-ranked: scoring costs ~3.5us per match, so 100k matches rank in well
# under a second while the broadest one-word queries match 10M+.
FTS_RANK_LIMIT = 100_000


class SearchResults(list):
    """Search hits, flagged ``broad`` when listed newest first, not ranked."""

    broad: bool = False


# Words so common in case titles ("X v. State of Y") that their FTS5 doclists
# cover most of the corpus; they are checked with LIKE on narrowed candidates.
_FTS_STOPWORDS = frozenset(
    {"and", "for", "the", "with", "from", "versus", "state", "ors", "anr"}
)


class OpenJudgmentsClient:
    """Query free Indian case law held in public S3 Parquet + PDF files."""

    def __init__(
        self,
        data_path: Optional[str] = None,
        sc_bucket: Optional[str] = None,
        hc_bucket: Optional[str] = None,
        region: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        """Configure bucket locations and the local corpus directory.

        Args:
            data_path: Directory holding synced metadata and cached PDFs.
            sc_bucket: Supreme Court bucket name.
            hc_bucket: High Court bucket name.
            region: AWS region hosting both buckets.
            timeout: Per-request HTTP timeout in seconds.
        """
        self.root = Path(data_path or settings.CASE_LAW_DATA_PATH).expanduser()
        self.sc_bucket = sc_bucket or settings.OPEN_DATA_SC_BUCKET
        self.hc_bucket = hc_bucket or settings.OPEN_DATA_HC_BUCKET
        self.region = region or settings.OPEN_DATA_REGION
        self.timeout = timeout

        # DuckDB connections are cached per worker thread (queries run via
        # ``asyncio.to_thread``). A fresh in-memory connection per query would
        # discard DuckDB's Parquet metadata cache every call; a single shared
        # connection is not safe for concurrent use from multiple threads.
        self._local = threading.local()
        self._conns_lock = threading.Lock()
        self._conns: set = set()
        self._generation = 0
        # Shared HTTP client for S3 sync and judgment PDF downloads.
        self._http: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Locations
    # ------------------------------------------------------------------
    def _endpoint(self, bucket: str) -> str:
        """Base HTTPS endpoint for a bucket."""
        return f"https://{bucket}.s3.{self.region}.amazonaws.com"

    @property
    def sc_metadata_dir(self) -> Path:
        """Local directory holding Supreme Court metadata Parquet."""
        return self.root / "sc" / "metadata"

    @property
    def hc_metadata_dir(self) -> Path:
        """Local directory holding High Court metadata Parquet."""
        return self.root / "hc" / "metadata"

    @property
    def pdf_cache_dir(self) -> Path:
        """Local directory holding cached judgment PDFs."""
        return self.root / "pdf-cache"

    def _sc_glob(self) -> str:
        """Glob for synced Supreme Court metadata, DuckDB-flavoured."""
        return str(self.sc_metadata_dir / "year=*" / "metadata.parquet")

    def _hc_glob(self) -> str:
        """Glob for synced High Court metadata, DuckDB-flavoured."""
        return str(
            self.hc_metadata_dir / "year=*" / "court=*" / "bench=*" / "metadata.parquet"
        )

    def _historical_glob(self) -> str:
        """Glob for the digitized pre-1950 corpus, per-court dirs."""
        return str(self.root / "historical" / "*" / "metadata.parquet")

    def _recent_glob(self) -> str:
        """Glob for the recently-published corpus, per-court dirs."""
        return str(self.root / "recent" / "*" / "metadata.parquet")

    def synced_courts(self) -> Dict[str, List[int]]:
        """Report which courts and years are available locally.

        Returns:
            Mapping of court code (``"SC"`` or a High Court code) to the sorted
            list of years synced for it.
        """
        out: Dict[str, List[int]] = {}

        sc_years = sorted(
            int(p.name.split("=", 1)[1])
            for p in self.sc_metadata_dir.glob("year=*")
            if p.is_dir() and (p / "metadata.parquet").exists()
        )
        if sc_years:
            out["SC"] = sc_years

        for year_dir in self.hc_metadata_dir.glob("year=*"):
            if not year_dir.is_dir():
                continue
            year = int(year_dir.name.split("=", 1)[1])
            for court_dir in year_dir.glob("court=*"):
                code = court_dir.name.split("=", 1)[1]
                if any(court_dir.glob("bench=*/metadata.parquet")):
                    out.setdefault(code, [])
                    if year not in out[code]:
                        out[code].append(year)

        for code in out:
            out[code].sort()
        return out

    def is_synced(self) -> bool:
        """Whether any metadata has been downloaded."""
        return bool(self.synced_courts())

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------
    async def _list_keys(
        self, bucket: str, prefix: str, client: httpx.AsyncClient
    ) -> List[Tuple[str, int]]:
        """List every object under a prefix, following continuation tokens.

        Args:
            bucket: Bucket name.
            prefix: Key prefix to list.
            client: Shared HTTP client.

        Returns:
            List of ``(key, size_in_bytes)`` tuples.
        """
        keys: List[Tuple[str, int]] = []
        token: Optional[str] = None
        endpoint = self._endpoint(bucket)

        while True:
            params: Dict[str, str] = {
                "list-type": "2",
                "prefix": prefix,
                "max-keys": "1000",
            }
            if token:
                params["continuation-token"] = token

            response = await self._get_with_retry(client, endpoint, params=params)
            response.raise_for_status()
            # XML from the public AWS S3 listing API over HTTPS; no untrusted input.
            root = ElementTree.fromstring(response.text)  # nosec B314

            for contents in root.findall(f"{S3_NAMESPACE}Contents"):
                key_el = contents.find(f"{S3_NAMESPACE}Key")
                size_el = contents.find(f"{S3_NAMESPACE}Size")
                if key_el is not None and key_el.text:
                    keys.append(
                        (
                            key_el.text,
                            int(size_el.text or 0) if size_el is not None else 0,
                        )
                    )

            truncated = root.find(f"{S3_NAMESPACE}IsTruncated")
            if truncated is None or truncated.text != "true":
                break
            token_el = root.find(f"{S3_NAMESPACE}NextContinuationToken")
            if token_el is None or not token_el.text:
                break
            token = token_el.text

        return keys

    async def sync(
        self,
        courts: Sequence[str],
        from_year: int,
        to_year: int,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Download metadata Parquet for the given courts and year range.

        Only metadata is downloaded - typically a few tens of MB per court-year,
        against 1.25 TiB for the full PDF corpus. PDFs are fetched lazily.

        Args:
            courts: Court names, aliases or codes. ``"SC"`` for Supreme Court.
            from_year: First year to sync, inclusive.
            to_year: Last year to sync, inclusive.
            force: Re-download files that already exist locally.

        Returns:
            Summary with per-court file counts and total bytes downloaded.
        """
        if from_year > to_year:
            raise SourceUnavailable(
                f"from_year ({from_year}) must not exceed to_year ({to_year})."
            )

        codes = [resolve_court(c) for c in courts] or [None]
        years = set(range(from_year, to_year + 1))
        summary: Dict[str, Any] = {"courts": {}, "files": 0, "bytes": 0, "skipped": 0}

        client = self._http_client()
        for code in codes:
            if code is None:
                continue
            if code == "SC":
                stats = await self._sync_sc(client, years, force)
            else:
                stats = await self._sync_hc(client, code, years, force)

            summary["courts"][court_label(code)] = stats
            summary["files"] += stats["files"]
            summary["bytes"] += stats["bytes"]
            summary["skipped"] += stats["skipped"]

        summary["megabytes"] = round(summary["bytes"] / (1024 * 1024), 1)
        summary["attribution"] = ATTRIBUTION
        return summary

    async def _download(
        self,
        client: httpx.AsyncClient,
        bucket: str,
        key: str,
        target: Path,
        force: bool,
    ) -> Tuple[bool, int]:
        """Download one object unless it is already present.

        Returns:
            ``(downloaded, bytes_written)``. ``downloaded`` is False when the
            local copy was reused.
        """
        if target.exists() and not force and target.stat().st_size > 0:
            return False, 0

        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"{self._endpoint(bucket)}/{key}"
        response = await self._get_with_retry(client, url)
        response.raise_for_status()
        target.write_bytes(response.content)
        return True, len(response.content)

    async def _sync_sc(
        self, client: httpx.AsyncClient, years: set, force: bool
    ) -> Dict[str, Any]:
        """Sync Supreme Court metadata for the requested years."""
        stats: Dict[str, Any] = {"files": 0, "bytes": 0, "skipped": 0, "years": []}
        keys = await self._list_keys(self.sc_bucket, "metadata/parquet/year=", client)

        for key, _size in keys:
            match = re.search(r"year=(\d{4})/", key)
            if not match or int(match.group(1)) not in years:
                continue
            if not key.endswith(".parquet"):
                continue

            year = int(match.group(1))
            target = self.sc_metadata_dir / f"year={year}" / "metadata.parquet"
            downloaded, size = await self._download(
                client, self.sc_bucket, key, target, force
            )
            if downloaded:
                stats["files"] += 1
                stats["bytes"] += size
            else:
                stats["skipped"] += 1
            if year not in stats["years"]:
                stats["years"].append(year)

        stats["years"].sort()
        return stats

    async def _sync_hc(
        self, client: httpx.AsyncClient, code: str, years: set, force: bool
    ) -> Dict[str, Any]:
        """Sync one High Court's metadata for the requested years."""
        stats: Dict[str, Any] = {
            "files": 0,
            "bytes": 0,
            "skipped": 0,
            "years": [],
            "benches": [],
        }

        for year in sorted(years):
            prefix = f"metadata/parquet/year={year}/court={code}/"
            keys = await self._list_keys(self.hc_bucket, prefix, client)

            for key, _size in keys:
                # Skip the mobile-sourced sidecar; the main file is canonical.
                if not key.endswith("metadata.parquet"):
                    continue
                bench_match = re.search(r"bench=([^/]+)/", key)
                if not bench_match:
                    continue
                bench = bench_match.group(1)

                target = (
                    self.hc_metadata_dir
                    / f"year={year}"
                    / f"court={code}"
                    / f"bench={bench}"
                    / "metadata.parquet"
                )
                downloaded, size = await self._download(
                    client, self.hc_bucket, key, target, force
                )
                if downloaded:
                    stats["files"] += 1
                    stats["bytes"] += size
                else:
                    stats["skipped"] += 1
                if bench not in stats["benches"]:
                    stats["benches"].append(bench)
                if year not in stats["years"]:
                    stats["years"].append(year)

        stats["years"].sort()
        return stats

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def _connect(self):
        """Return a persistent, thread-local DuckDB connection.

        Queries run in worker threads via ``asyncio.to_thread``, so each thread
        keeps one connection. Reusing the connection across queries retains
        DuckDB's Parquet metadata and row-group statistics cache, which a
        fresh ``duckdb.connect()`` per call would discard.
        """
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise SourceUnavailable(
                "duckdb is required for open-data case law. Install with "
                "'uv pip install duckdb'."
            ) from exc

        entry = getattr(self._local, "conn", None)
        if entry is None or entry[0] != self._generation:
            conn = duckdb.connect()
            with self._conns_lock:
                self._conns.add(conn)
            self._local.conn = (self._generation, conn)
            return conn
        return entry[1]

    def _http_client(self) -> httpx.AsyncClient:
        """Return the shared HTTP client for S3 sync and PDF downloads."""
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
        return self._http

    async def _get_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        """GET a remote URL with exponential backoff on transient failures.

        The public S3 buckets and court PDF endpoints occasionally throttle
        or blip; a one-shot fetch turns that into a hard failure of an
        otherwise routine sync or document read. Network errors and
        429/5xx responses are retried; any other status is returned
        immediately so callers keep their own handling (e.g. the 404 path
        in :meth:`get_document`).

        Args:
            client: Shared HTTP client.
            url: Endpoint to fetch.
            params: Optional query parameters.

        Returns:
            The response for a non-retryable outcome.

        Raises:
            SourceUnavailable: When every attempt fails.
        """
        last_error = ""
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    f"Fetch failed (attempt {attempt + 1}/{MAX_RETRIES}): {url}: {exc}"
                )
            else:
                if response.status_code not in RETRYABLE_STATUSES:
                    return response
                last_error = f"HTTP {response.status_code}"
                logger.warning(
                    f"Fetch got {response.status_code} "
                    f"(attempt {attempt + 1}/{MAX_RETRIES}): {url}"
                )
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2**attempt)
        raise SourceUnavailable(
            f"{url} could not be fetched after {MAX_RETRIES} attempts ({last_error})."
        )

    # ------------------------------------------------------------------
    # Full-text search index
    # ------------------------------------------------------------------
    def _fts_path(self) -> Path:
        """Persistent SQLite file holding the corpus table + FTS5 index."""
        return self.root / "fts" / "corpus.sqlite"

    def _metadata_files(self) -> Dict[str, int]:
        """Every synced metadata Parquet file mapped to its mtime in ns."""
        files: Dict[str, int] = {}
        for pattern in (
            self.sc_metadata_dir.glob("year=*/metadata.parquet"),
            self.hc_metadata_dir.glob("year=*/court=*/bench=*/metadata.parquet"),
            self.root.glob("historical/*/metadata.parquet"),
            self.root.glob("recent/*/metadata.parquet"),
        ):
            for meta in pattern:
                try:
                    files[str(meta)] = meta.stat().st_mtime_ns
                except OSError:  # removed mid-scan
                    continue
        return files

    def _fts_available(self) -> bool:
        """Whether a fresh FTS index exists for the synced corpus.

        The index counts as stale once any metadata Parquet file is newer than
        it, because a sync may have added rows the index does not cover.
        """
        path = self._fts_path()
        if not path.is_file() or path.stat().st_size == 0:
            return False
        index_mtime = path.stat().st_mtime_ns
        return all(m <= index_mtime for m in self._metadata_files().values())

    def corpus_version(self) -> str:
        """A token that changes whenever search results could change.

        Combines the index file's mtime with the newest metadata mtime, so a
        sync (new Parquet) or an index update both invalidate cached searches.
        """
        try:
            index = self._fts_path().stat().st_mtime_ns
        except OSError:
            index = 0
        newest = max(self._metadata_files().values(), default=0)
        return f"{index}:{newest}"

    def _connect_fts(self):
        """Thread-local read-only connection to the FTS corpus file.

        Reopens when the file's inode changes: a full rebuild (the nightly
        cron or the sync tool) swaps a new file in with os.replace, and a
        handle on the old inode would keep serving the previous index forever.
        Incremental updates write the live file in place; readers take normal
        shared locks and see them on their next query.
        """
        entry = getattr(self._local, "fts_conn", None)
        try:
            inode = self._fts_path().stat().st_ino
        except OSError:
            inode = None
        if entry is None or entry[0] != self._generation or entry[2] != inode:
            if entry is not None:
                try:
                    entry[1].close()
                except Exception:  # noqa: BLE001 - stale handle, best-effort
                    pass
                with self._conns_lock:
                    self._conns.discard(entry[1])
            # check_same_thread=False lets _close_duckdb_handles close it
            # from whichever thread shuts down; the per-thread cache still
            # keeps one connection per thread. The timeout rides out an
            # incremental update's brief commit lock.
            conn = sqlite3.connect(
                f"file:{self._fts_path()}?mode=ro",
                uri=True,
                timeout=30,
                check_same_thread=False,
            )
            conn.execute("PRAGMA cache_size=-65536")  # 64 MiB page cache
            with self._conns_lock:
                self._conns.add(conn)
            self._local.fts_conn = (self._generation, conn, inode)
            return conn
        return entry[1]

    def build_fts_index(self, force: bool = False) -> Dict[str, Any]:
        """Bring the FTS index up to date with the synced metadata.

        DuckDB scans the Parquet metadata into a SQLite file with an FTS5
        index over title and description. The search tool uses it for
        BM25-ranked search when it is present and fresh, falling back to the
        LIKE-based scan otherwise.

        Without ``force`` only Parquet files that are new, changed or removed
        since the last build are re-indexed, in place; a nightly sync touches
        a handful of files, so this takes seconds rather than the half hour
        of a full build. A missing index, or one built before per-file
        tracking existed, gets a full build.

        Args:
            force: Rebuild the whole index from scratch.

        Returns:
            Summary with the index path, row count and what was re-indexed.
        """
        path = self._fts_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not force and path.is_file() and path.stat().st_size > 0:
            result = self._update_fts_index()
            if result is not None:
                return result
        return self._full_build()

    def _scan(self) -> Any:
        """A DuckDB connection bounded for scanning Parquet into the index."""
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - dependency declared
            raise SourceUnavailable(
                "duckdb is required to build the open-data case-law index."
            ) from exc
        scan = duckdb.connect()
        # Bound the Parquet scan's memory so containerised builds are not OOM
        # killed, and let any spill land on the scratch disk.
        self._apply_duckdb_resource_guards(scan)
        if settings.FTS_BUILD_TEMP_DIR:
            Path(settings.FTS_BUILD_TEMP_DIR).mkdir(parents=True, exist_ok=True)
            scan.execute(
                f"SET temp_directory='{_sql_quote(settings.FTS_BUILD_TEMP_DIR)}'"
            )
        return scan

    def _years(self, scan: Any, sql: str) -> List[str]:
        """Every year in the corpus, oldest first, ``"NULL"`` leading."""
        found = {
            row[0]
            for row in scan.execute(f"SELECT DISTINCT year FROM ({sql})").fetchall()
        }
        dated = sorted(y for y in found if y is not None)
        return (["NULL"] if None in found else []) + dated

    @staticmethod
    def _insert_rows(
        out: sqlite3.Connection, cursor: Any, ids: Dict[str, int], create: bool
    ) -> int:
        """Copy a DuckDB result into ``corpus``, paths swapped for source ids.

        Rows store the integer, not the path: 16M copies of a ~90-byte path
        plus their index cost about 3 GB of the index file. A row from a file
        that appeared after the snapshot is skipped; the next incremental
        update picks that file up.
        """
        columns = [d[0] for d in cursor.description]
        if create:
            out.execute(
                "CREATE TABLE IF NOT EXISTS corpus (id INTEGER PRIMARY KEY, "
                + ", ".join(columns)
                + ")"
            )
        k = columns.index("_source")
        insert = (
            f"INSERT INTO corpus ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' * len(columns))})"
        )
        added = 0
        while batch := cursor.fetchmany(50_000):
            rows = [r[:k] + (ids[r[k]],) + r[k + 1 :] for r in batch if r[k] in ids]
            out.executemany(insert, rows)
            added += len(rows)
        return added

    def _full_build(self) -> Dict[str, Any]:
        """Build the whole index into a side file and swap it in."""
        sql, _globs = self._search_sql("all")
        path = self._fts_path()
        # Build into a side file and swap it in at the end, so readers (the
        # running server, when the nightly cron rebuilds) never see a
        # half-built index, and a crash leaves the previous one in service.
        building = path.with_name(path.name + ".building")
        self._discard_build(building)
        # Snapshot before the scan: a file that changes during it is picked
        # up by the next incremental update.
        sources = self._metadata_files()
        ids = {p: i for i, p in enumerate(sorted(sources), start=1)}
        scan = self._scan()
        out = sqlite3.connect(str(building))
        started = time.monotonic()
        count = 0
        try:
            # The side file is discarded on any failure, so durability buys
            # nothing here: skip the journal and fsyncs.
            out.execute("PRAGMA journal_mode=OFF")
            out.execute("PRAGMA synchronous=OFF")
            out.execute("PRAGMA cache_size=-262144")  # 256 MiB
            # Oldest first, one year at a time, so rowids follow decision
            # date: FTS5 can then list matches newest-first just by walking
            # rowids downwards, the cheap path for queries too broad to rank
            # (see _search_fts). Sorting all 16M rows at once ran DuckDB out
            # of memory in a 4 GB container; one year's partition fits.
            logger.info("FTS build: streaming metadata Parquet into SQLite")
            for year in self._years(scan, sql):
                try:
                    year_sql, _ = self._search_sql("all", year)
                except CorpusNotSynced:
                    continue
                cursor = scan.execute(
                    f"SELECT * FROM ({year_sql}) ORDER BY decision_date NULLS FIRST"
                )
                count += self._insert_rows(out, cursor, ids, create=True)
            out.commit()
            logger.info(
                f"FTS build: corpus table ready with {count} rows "
                f"in {time.monotonic() - started:.1f}s"
            )
            out.execute("CREATE INDEX corpus_source ON corpus (_source)")
            out.execute(
                "CREATE TABLE fts_sources "
                "(id INTEGER PRIMARY KEY, path TEXT UNIQUE, mtime_ns INTEGER)"
            )
            out.executemany(
                "INSERT INTO fts_sources VALUES (?, ?, ?)",
                [(i, p, sources[p]) for p, i in ids.items()],
            )
            # External-content index: the text lives once, in `corpus`.
            # court_code is indexed so a court filter narrows inside FTS5
            # instead of re-reading every matching row. No stemming: search
            # terms are prefix-matched, which mirrors the LIKE path's
            # substring semantics far better than stemmed tokens do.
            out.execute(
                "CREATE VIRTUAL TABLE corpus_fts USING fts5("
                "title, description, court_code, "
                "content='corpus', content_rowid='id', "
                "tokenize='unicode61 remove_diacritics 2')"
            )
            out.execute("INSERT INTO corpus_fts(corpus_fts) VALUES('rebuild')")
            out.execute("INSERT INTO corpus_fts(corpus_fts) VALUES('optimize')")
            out.commit()
            # Leave the file in rollback-journal mode for the in-place
            # incremental updates that follow.
            out.execute("PRAGMA journal_mode=DELETE")
            logger.info(
                f"FTS build: FTS5 index created in "
                f"{time.monotonic() - started:.1f}s total"
            )
        except BaseException:
            scan.close()
            out.close()
            self._discard_build(building)
            raise
        scan.close()
        out.close()
        os.replace(building, path)

        elapsed = time.monotonic() - started
        # Readers in this process reopen on the new inode; close them now too.
        self._close_duckdb()
        logger.info(f"FTS build: committed {count} rows to {path} in {elapsed:.1f}s")

        return {
            "status": "success",
            "path": str(path),
            "rows": int(count),
            "rebuilt": True,
            "files_reindexed": len(sources),
            "elapsed_seconds": round(elapsed, 1),
            "message": (
                f"Built the full-text index over {int(count)} judgments in "
                f"{elapsed:.1f}s. Search now uses BM25 ranking."
            ),
        }

    def _update_fts_index(self) -> Optional[Dict[str, Any]]:
        """Re-index only changed Parquet files, in place.

        Returns ``None`` when the index predates integer per-file tracking (or
        is unreadable), so the caller does a full build instead.
        """
        path = self._fts_path()
        out = sqlite3.connect(str(path), timeout=300, isolation_level=None)
        try:
            try:
                recorded = {
                    p: (i, m)
                    for i, p, m in out.execute(
                        "SELECT id, path, mtime_ns FROM fts_sources"
                    ).fetchall()
                }
            except sqlite3.DatabaseError:
                return None
            current = self._metadata_files()
            changed = sorted(
                p for p, m in current.items() if recorded.get(p, (0, None))[1] != m
            )
            removed = sorted(set(recorded) - set(current))
            if not changed and not removed:
                count = out.execute("SELECT count(*) FROM corpus").fetchone()[0]
                return {
                    "status": "success",
                    "path": str(path),
                    "rows": int(count),
                    "rebuilt": False,
                    "files_reindexed": 0,
                    "message": "FTS index already covers every synced file.",
                }

            started = time.monotonic()
            # Keep every dirty page in memory until commit: a spill would
            # take the exclusive lock early and block searches for the whole
            # update instead of just the commit.
            out.execute("PRAGMA cache_spill=OFF")
            out.execute("BEGIN IMMEDIATE")
            try:
                ids = {}
                for p in changed:
                    if p in recorded:
                        ids[p] = recorded[p][0]
                        out.execute(
                            "UPDATE fts_sources SET mtime_ns = ? WHERE id = ?",
                            (current[p], ids[p]),
                        )
                    else:
                        ids[p] = out.execute(
                            "INSERT INTO fts_sources (path, mtime_ns) VALUES (?, ?)",
                            (p, current[p]),
                        ).lastrowid
                stale = [recorded[p][0] for p in changed if p in recorded]
                stale += [recorded[p][0] for p in removed]
                dropped, added = self._reindex_sources(out, stale, ids)
                out.executemany(
                    "DELETE FROM fts_sources WHERE path = ?",
                    [(p,) for p in removed],
                )
                out.execute("COMMIT")
            except BaseException:
                out.execute("ROLLBACK")
                raise
            count = out.execute("SELECT count(*) FROM corpus").fetchone()[0]
        finally:
            out.close()

        elapsed = time.monotonic() - started
        logger.info(
            f"FTS update: re-indexed {len(changed)} changed and {len(removed)} "
            f"removed files (-{dropped} +{added} rows) in {elapsed:.1f}s"
        )
        return {
            "status": "success",
            "path": str(path),
            "rows": int(count),
            "rebuilt": False,
            "files_reindexed": len(changed) + len(removed),
            "rows_added": added,
            "rows_removed": dropped,
            "elapsed_seconds": round(elapsed, 1),
            "message": (
                f"Updated the full-text index from {len(changed) + len(removed)} "
                f"changed metadata files in {elapsed:.1f}s."
            ),
        }

    def _reindex_sources(
        self, out: sqlite3.Connection, stale: List[int], ids: Dict[str, int]
    ) -> Tuple[int, int]:
        """Drop rows of the ``stale`` source ids, then load ``ids`` files anew.

        New rows get the next rowids, in date order within the batch, so
        newly synced judgments land at the newest end of the rowid order.
        """
        dropped = 0
        for source in stale:
            # An external-content index must be told the old values to unindex.
            out.execute(
                "INSERT INTO corpus_fts(corpus_fts, rowid, title, description, "
                "court_code) SELECT 'delete', id, title, description, "
                "court_code FROM corpus WHERE _source = ?",
                (source,),
            )
            dropped += out.execute(
                "DELETE FROM corpus WHERE _source = ?", (source,)
            ).rowcount
        if not ids:
            return dropped, 0

        sql, _globs = self._search_sql("all")
        first_new = (
            out.execute("SELECT coalesce(max(id), 0) FROM corpus").fetchone()[0] + 1
        )
        added = 0
        scan = self._scan()
        try:
            # A filter on the filename lets DuckDB prune the scan to the
            # changed Parquet files.
            cursor = scan.execute(
                f"SELECT * FROM ({sql}) WHERE _source IN "
                f"({', '.join('?' * len(ids))}) ORDER BY decision_date NULLS FIRST",
                list(ids),
            )
            added = self._insert_rows(out, cursor, ids, create=False)
        finally:
            scan.close()
        out.execute(
            "INSERT INTO corpus_fts(rowid, title, description, court_code) "
            "SELECT id, title, description, court_code FROM corpus WHERE id >= ?",
            (first_new,),
        )
        return dropped, added

    @staticmethod
    def _discard_build(building: Path) -> None:
        """Remove a side-file build and anything a crashed build left beside it."""
        building.unlink(missing_ok=True)
        for suffix in ("-journal", "-wal", "-shm", ".wal"):
            building.with_name(building.name + suffix).unlink(missing_ok=True)
        shutil.rmtree(building.with_name(building.name + ".tmp"), ignore_errors=True)

    @staticmethod
    def _container_memory_bytes() -> Optional[int]:
        """Best-effort total RAM the *container* is entitled to.

        Resolution order, first finite value wins:

        1. cgroup v2 ``memory.max`` - the real enforced limit, when one is set.
        2. ``/proc/meminfo`` ``MemTotal`` - in a PVE container this is
           lxcfs-backed and correctly reports the ``memory:`` allocation.
        3. ``sysconf`` - bare-metal fallback.

        ``sysconf`` alone is wrong in a container: it reports the *host's*
        pages (16 GB here) even though the container is allocated 4 GB. Because
        PVE does not necessarily set a hard cgroup cap, preferring it lets a
        build claim far more than the slice it was given and evict other tenants.
        """
        try:
            with open("/sys/fs/cgroup/memory.max", encoding="ascii") as fh:
                raw = fh.read().strip()
            if raw and raw != "max":
                return int(raw)
        except (OSError, ValueError):  # noqa: BLE001 - advisory probe
            pass

        try:
            with open("/proc/meminfo", encoding="ascii") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            return int(parts[1]) * 1024
        except (OSError, ValueError):  # noqa: BLE001 - advisory probe
            pass

        try:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (ValueError, OSError, AttributeError):  # pragma: no cover
            return None

    @staticmethod
    def _apply_duckdb_resource_guards(con: Any) -> None:
        """Bound a build connection's memory use; best-effort, never raises.

        Caps DuckDB at ~60% of the container's RAM (max 8 GB) when a size can
        be determined; on any failure the defaults stay in force.
        """
        total_bytes = OpenJudgmentsClient._container_memory_bytes()
        if not total_bytes or total_bytes <= 0:
            return
        limit_bytes = min(int(total_bytes * 0.6), 8 * 1024**3)
        try:
            con.execute(f"SET memory_limit='{limit_bytes // (1024**2)}MB'")
            con.execute("SET preserve_insertion_order=false")
            logger.info(
                f"FTS build: memory_limit="
                f"{limit_bytes // (1024**2)}MB of {total_bytes // (1024**2)}MB "
                f"container RAM, preserve_insertion_order=off"
            )
        except Exception as e:  # noqa: BLE001 - guards are advisory
            logger.warning(f"FTS build: could not apply resource guards: {e}")

    def _fts_row_count(self) -> Optional[int]:
        """Return the row count of an existing FTS corpus, or None on error."""
        try:
            con = self._connect_fts()
            row = con.execute("SELECT COUNT(*) FROM corpus").fetchone()
            return int(row[0]) if row is not None else 0
        except Exception:  # noqa: BLE001 - best-effort freshness probe
            return None

    def close(self) -> None:
        """Close every cached connection and the shared HTTP client.

        Safe to call more than once; connections are recreated on demand
        afterwards (the generation counter invalidates stale per-thread ones).
        """
        self._close_duckdb()

        if self._http is not None:
            try:
                asyncio.run(self._http.aclose())
            except RuntimeError:
                pass  # a loop is already running; leave cleanup to GC
            self._http = None

    async def aclose(self) -> None:
        """Async variant of :meth:`close` for use inside a running loop."""
        self._close_duckdb()

        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _close_duckdb_handles(self) -> None:
        """Close every cached DuckDB connection; safe to call repeatedly.

        Closing alone does not retire the per-thread caches, so this also
        bumps the generation: otherwise a later query would resurrect a handle
        that is no longer open.
        """
        self._generation += 1
        with self._conns_lock:
            conns = list(self._conns)
            self._conns.clear()
        for conn in conns:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - best-effort shutdown
                logger.debug("Could not close a DuckDB connection", exc_info=True)

    def _close_duckdb(self) -> None:
        """Retire cached DuckDB connections; see :meth:`_close_duckdb_handles`."""
        self._close_duckdb_handles()

    def _search_sql(
        self, scope: str, year: Optional[str] = None
    ) -> Tuple[str, List[str]]:
        """Build the UNION query covering the requested scope.

        Args:
            scope: ``"SC"``, a High Court code, or ``"all"``.
            year: Restrict to one year (``"NULL"`` for rows without one). The
                Supreme Court and High Court globs narrow to that ``year=``
                directory, so DuckDB never opens other years' files.

        Returns:
            ``(sql, globs_used)``. The SQL exposes one uniform column set.
        """
        parts: List[str] = []
        globs: List[str] = []

        want_sc = scope in ("SC", "all")
        want_hc = scope != "SC"
        part = f"year={year}" if year else "year=*"
        year_clause = ""
        if year == "NULL":
            year_clause = "year IS NULL"
        elif year:
            year_clause = f"CAST(year AS VARCHAR) = '{_sql_quote(year)}'"
        sc_glob = str(self.sc_metadata_dir / part / "metadata.parquet")
        hc_glob = str(
            self.hc_metadata_dir / part / "court=*" / "bench=*" / "metadata.parquet"
        )

        if want_sc and any(self.sc_metadata_dir.glob(f"{part}/metadata.parquet")):
            globs.append(sc_glob)
            parts.append(
                f"""
                SELECT
                    'SC'                       AS court_code,
                    CAST(year AS VARCHAR)      AS year,
                    NULL                       AS bench,
                    title,
                    COALESCE(description, '')  AS description,
                    COALESCE(judge, '')        AS judge,
                    citation,
                    nc_display                 AS neutral_citation,
                    cnr,
                    disposal_nature,
                    -- The Supreme Court release stores dates as DD-MM-YYYY
                    -- text, which will not cast to DATE. Normalise to ISO so
                    -- date filtering works instead of silently matching nothing.
                    COALESCE(
                        strftime(try_strptime(decision_date, '%d-%m-%Y'), '%Y-%m-%d'),
                        CAST(decision_date AS VARCHAR)
                    )                          AS decision_date,
                    path                       AS locator,
                    'od'                       AS src,
                    NULL                       AS source_url,
                    filename                   AS _source
                FROM read_parquet('{_sql_quote(sc_glob)}', hive_partitioning = true, union_by_name = true, filename = true)
                """
            )

        if want_hc and any(
            self.hc_metadata_dir.glob(f"{part}/court=*/bench=*/metadata.parquet")
        ):
            globs.append(hc_glob)
            court_filter = ""
            if scope not in ("all", "SC"):
                court_filter = f"WHERE court = '{_sql_quote(scope)}'"
            parts.append(
                f"""
                SELECT
                    court                      AS court_code,
                    CAST(year AS VARCHAR)      AS year,
                    bench,
                    title,
                    COALESCE(description, '')  AS description,
                    COALESCE(judge, '')        AS judge,
                    NULL                       AS citation,
                    NULL                       AS neutral_citation,
                    cnr,
                    disposal_nature,
                    CAST(decision_date AS VARCHAR) AS decision_date,
                    pdf_link                   AS locator,
                    'od'                       AS src,
                    NULL                       AS source_url,
                    filename                   AS _source
                FROM read_parquet('{_sql_quote(hc_glob)}', hive_partitioning = true, union_by_name = true, filename = true)
                {court_filter}
                """
            )

        # Digitized pre-1950 corpus harvested from the courts' own archives
        # (see scripts/scrape_bhc_archive.py). Only courts with historical data
        # are matched; scope "all" includes every such court.
        hist_courts = self._historical_courts()
        if hist_courts and (scope in ("all",) or scope in hist_courts):
            globs.append(self._historical_glob())
            hist_filter = self._where(
                f"court = '{_sql_quote(scope)}'" if scope not in ("all", "SC") else "",
                year_clause,
            )
            parts.append(
                f"""
                SELECT
                    court                      AS court_code,
                    CAST(year AS VARCHAR)      AS year,
                    bench,
                    title,
                    COALESCE(description, '')  AS description,
                    COALESCE(judge, '')        AS judge,
                    COALESCE(citation, '')     AS citation,
                    NULL                       AS neutral_citation,
                    NULL                       AS cnr,
                    NULL                       AS disposal_nature,
                    CAST(decision_date AS VARCHAR) AS decision_date,
                    pdf_link                   AS locator,
                    'hist'                     AS src,
                    source_url,
                    filename                   AS _source
                FROM read_parquet('{_sql_quote(self._historical_glob())}', union_by_name = true, filename = true)
                {hist_filter}
                """
            )

        # Recently-published judgments scraped from the courts' own sites to
        # bridge the lag of the open-data corpus (see scripts/scrape_recent.py).
        # Same per-court layout and scope semantics as the historical corpus.
        recent_courts = self._recent_courts()
        if recent_courts and (scope in ("all",) or scope in recent_courts):
            globs.append(self._recent_glob())
            recent_filter = self._where(
                f"court = '{_sql_quote(scope)}'" if scope not in ("all", "SC") else "",
                year_clause,
            )
            parts.append(
                f"""
                SELECT
                    court                      AS court_code,
                    CAST(year AS VARCHAR)      AS year,
                    bench,
                    title,
                    COALESCE(description, '')  AS description,
                    COALESCE(judge, '')        AS judge,
                    COALESCE(citation, '')     AS citation,
                    NULL                       AS neutral_citation,
                    NULL                       AS cnr,
                    NULL                       AS disposal_nature,
                    CAST(decision_date AS VARCHAR) AS decision_date,
                    pdf_link                   AS locator,
                    'recent'                   AS src,
                    source_url,
                    filename                   AS _source
                FROM read_parquet('{_sql_quote(self._recent_glob())}', union_by_name = true, filename = true)
                {recent_filter}
                """
            )

        if not parts:
            raise CorpusNotSynced(
                "No local case-law metadata for that scope. Run the "
                "'sync_case_law' tool first, e.g. courts=['Supreme Court', "
                "'Bombay High Court'], from_year=2015, to_year=2026."
            )

        return " UNION ALL ".join(parts), globs

    @staticmethod
    def _where(*clauses: str) -> str:
        """Join the non-empty clauses into a WHERE, or nothing."""
        kept = [c for c in clauses if c]
        return f"WHERE {' AND '.join(kept)}" if kept else ""

    def _historical_courts(self) -> set:
        """Court codes that have a digitized historical corpus locally."""
        courts: set = set()
        for meta in self.root.glob("historical/*/metadata.parquet"):
            con = self._connect()
            for (code,) in con.execute(
                f"SELECT DISTINCT court FROM read_parquet('{_sql_quote(str(meta))}')"
            ).fetchall():
                courts.add(code)
        return courts

    def _recent_courts(self) -> set:
        """Court codes that have a recent-judgments corpus locally."""
        courts: set = set()
        for meta in self.root.glob("recent/*/metadata.parquet"):
            con = self._connect()
            for (code,) in con.execute(
                f"SELECT DISTINCT court FROM read_parquet('{_sql_quote(str(meta))}')"
            ).fetchall():
                courts.add(code)
        return courts

    def _make_doc_id(self, row: Dict[str, Any]) -> str:
        """Build a stable, reversible document id for a metadata row."""
        code = row["court_code"]
        name = Path(row["locator"] or "").name
        if row.get("src") == "hist":
            return f"hist:{code}:{row['bench']}:{row['year']}:{name}"
        if row.get("src") == "recent":
            return f"rc:{code}:{row['bench']}:{row['year']}:{name}"
        if code == "SC":
            return f"sc:{row['year']}:{row['locator']}"
        return f"hc:{code}:{row['bench']}:{row['year']}:{name}"

    def _public_url(self, row: Dict[str, Any]) -> str:
        """Public HTTPS URL for the judgment PDF."""
        if row.get("src") == "hist":
            return row.get("source_url") or str(
                self.root / "historical" / (row.get("bench") or "") / "pdfs"
            )
        if row.get("src") == "recent":
            return row.get("source_url") or str(
                self.root / "recent" / (row.get("court_code") or "") / "pdfs"
            )
        code = row["court_code"]
        if code == "SC":
            # Supreme Court PDFs are grouped by language, with the English
            # release suffixed _EN: data/pdf/year=2024/english/<path>_EN.pdf
            return (
                f"{self._endpoint(self.sc_bucket)}/data/pdf/"
                f"year={row['year']}/english/{row['locator']}_EN.pdf"
            )
        name = Path(row["locator"] or "").name
        return (
            f"{self._endpoint(self.hc_bucket)}/data/pdf/"
            f"year={row['year']}/court={code}/bench={row['bench']}/{name}"
        )

    async def search(
        self,
        query: str,
        court: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        judge: Optional[str] = None,
        limit: int = 20,
        page: int = 0,
    ) -> List[SearchResult]:
        """Search synced case-law metadata.

        Matching is over case title, description and judge name - the fields the
        open dataset provides. Full judgment text is not indexed; open a
        judgment with :meth:`get_judgment` to read it.

        Args:
            query: Free-text terms. All terms must appear (AND semantics).
            court: Court name, alias or code. ``None`` searches everything synced.
            from_date: Inclusive lower bound, ``YYYY-MM-DD``.
            to_date: Inclusive upper bound, ``YYYY-MM-DD``.
            judge: Restrict to judgments by a judge whose name contains this.
            limit: Maximum results per page.
            page: Zero-based page number into the ranked result set.

        Returns:
            Ranked search results, most recent first.
        """
        scope = resolve_court(court) or "all"
        offset = max(0, page) * max(0, limit)

        if self._fts_available():
            try:
                hits = await self._search_fts(
                    scope, query, court, from_date, to_date, judge, limit, offset
                )
                if hits is not None:
                    return hits
            except Exception as exc:  # noqa: BLE001 - fall back to LIKE
                logger.warning("FTS search failed, falling back to LIKE scan: %s", exc)

        sql, _globs = self._search_sql(scope)

        conditions: List[str] = []
        params: List[Any] = []

        for term in [t for t in re.split(r"\s+", query.strip()) if t]:
            conditions.append("(lower(title) LIKE ? OR lower(description) LIKE ?)")
            like = f"%{term.lower()}%"
            params.extend([like, like])

        if judge:
            conditions.append("lower(judge) LIKE ?")
            params.append(f"%{judge.lower()}%")
        if from_date:
            conditions.append("try_cast(decision_date AS DATE) >= try_cast(? AS DATE)")
            params.append(from_date)
        if to_date:
            conditions.append("try_cast(decision_date AS DATE) <= try_cast(? AS DATE)")
            params.append(to_date)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        full_sql = f"""
            SELECT * FROM ({sql}) AS corpus
            {where}

            ORDER BY try_cast(decision_date AS DATE) DESC NULLS LAST
            LIMIT ?
            OFFSET ?
        """
        params.append(limit)
        params.append(offset)

        def _run() -> List[Dict[str, Any]]:
            con = self._connect()
            cursor = con.execute(full_sql, params)
            columns = [d[0] for d in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

        rows = await asyncio.to_thread(_run)
        return [self._row_to_result(row) for row in rows]

    async def _search_fts(
        self,
        scope: str,
        query: str,
        court: Optional[str],
        from_date: Optional[str],
        to_date: Optional[str],
        judge: Optional[str],
        limit: int,
        offset: int = 0,
    ) -> Optional["SearchResults"]:
        """BM25-ranked search over the built FTS5 index.

        Each plain word of three or more characters is an FTS5 prefix match
        restricted to title and description, a subset of the LIKE path's
        ``%term%`` test, so it needs no per-row re-check. Other terms are
        re-checked with LIKE on the narrowed candidates. Returns ``None`` when
        nothing in the query is indexable; the caller then falls back to the
        LIKE scan. Queries matching more than ``FTS_RANK_LIMIT`` judgments
        are listed newest first instead of ranked, flagged ``broad``.
        """
        conditions: List[str] = []
        params: List[Any] = []
        words: List[str] = []  # FTS5 terms; matched as prefixes when ranked
        common: List[str] = []  # stopwords, used only if nothing else is

        for term in [t for t in re.split(r"\s+", query.strip()) if t]:
            lowered = term.lower()
            parts = re.findall(r"\w+", lowered)
            longest = max(parts, key=len, default="")
            plain = len(parts) == 1 and parts[0] == lowered
            if plain and len(lowered) >= 3 and lowered not in _FTS_STOPWORDS:
                words.append(lowered)
                continue
            # Stopwords, very short terms and punctuated terms have doclists
            # spanning millions of rows ("of" alone matches most titles), or
            # tokenize differently from a substring test. Check them with the
            # LIKE path's exact test, on candidates the other terms narrowed.
            conditions.append("(lower(c.title) LIKE ? OR lower(c.description) LIKE ?)")
            like = f"%{lowered}%"
            params.extend([like, like])
            if not plain and len(longest) >= 3:
                words.append(longest)
            elif len(longest) >= 3:
                common.append(longest)
        # A query of nothing but common words ("state") still has to go
        # through FTS5: the LIKE fallback scans every row.
        words = words or common
        if not words:
            return None

        def match(prefix: bool) -> str:
            star = "*" if prefix else ""
            expr = (
                "{title description} : ("
                + " AND ".join(f'"{w}"{star}' for w in words)
                + ")"
            )
            if scope != "all":
                court_tokens = " ".join(re.findall(r"[A-Za-z0-9]+", scope))
                expr += f' AND court_code : "{court_tokens}"'
            return expr

        filtered = bool(judge or from_date or to_date)
        if judge:
            conditions.append("lower(c.judge) LIKE ?")
            params.append(f"%{judge.lower()}%")
        if from_date:
            conditions.append("date(c.decision_date) >= date(?)")
            params.append(from_date)
        if to_date:
            conditions.append("date(c.decision_date) <= date(?)")
            params.append(to_date)
        extra = "".join(f" AND {cond}" for cond in conditions)

        # Too broad to rank: BM25 scores every match (38s for "state", 10.7M
        # hits). Rowids follow decision date (see _full_build), so walking
        # exact-token matches by descending rowid lists the newest first in
        # milliseconds. A window past the page is re-sorted on the real date
        # to absorb the slight disorder incremental updates introduce.
        # ponytail: judge/date filters keep the ranked path, since a selective
        # filter could walk most of the corpus; bound the walk by rowid if
        # filtered broad queries turn out to be common.
        broad_sql = (
            "WITH cand AS MATERIALIZED (SELECT c.* FROM corpus_fts "
            "JOIN corpus c ON c.id = corpus_fts.rowid "
            f"WHERE corpus_fts MATCH ?{extra} "
            "ORDER BY corpus_fts.rowid DESC LIMIT ?) "
            "SELECT * FROM cand ORDER BY decision_date DESC, id DESC "
            "LIMIT ? OFFSET ?"
        )
        broad_params = [match(False), *params, offset + limit + 500, limit, offset]

        # Rank inside the FTS index and fetch corpus rows only for the page:
        # sorting on a corpus column (the old date tie-break) made SQLite read
        # the full row of every match, 91s for a one-word query. Row-level
        # filters still need the rows, so then the page is cut after them.
        hits = (
            "SELECT rowid AS id, bm25(corpus_fts, 1.0, 1.0, 0.0) AS score "
            "FROM corpus_fts WHERE corpus_fts MATCH ?"
        )
        order = "ORDER BY hits.score, hits.id DESC"
        if conditions:
            ranked_sql = (
                f"WITH hits AS ({hits}) SELECT c.* FROM hits "
                f"JOIN corpus c ON c.id = hits.id "
                f"WHERE {' AND '.join(conditions)} {order} LIMIT ? OFFSET ?"
            )
            ranked_params = [match(True), *params, limit, offset]
        else:
            ranked_sql = (
                f"WITH hits AS ({hits} ORDER BY score, id DESC LIMIT ? OFFSET ?) "
                f"SELECT c.* FROM hits JOIN corpus c ON c.id = hits.id {order}"
            )
            ranked_params = [match(True), limit, offset]

        def _run() -> Tuple[bool, List[Dict[str, Any]]]:
            con = self._connect_fts()
            broad = not filtered and (
                con.execute(
                    "SELECT count(*) FROM (SELECT 1 FROM corpus_fts "
                    "WHERE corpus_fts MATCH ? LIMIT ?)",
                    (match(False), FTS_RANK_LIMIT + 1),
                ).fetchone()[0]
                > FTS_RANK_LIMIT
            )
            sql, args = (
                (broad_sql, broad_params) if broad else (ranked_sql, ranked_params)
            )
            cursor = con.execute(sql, args)
            columns = [d[0] for d in cursor.description]
            return broad, [dict(zip(columns, row)) for row in cursor.fetchall()]

        broad, rows = await asyncio.to_thread(_run)
        results = SearchResults(self._row_to_result(row) for row in rows)
        results.broad = broad
        return results

    def _row_to_result(self, row: Dict[str, Any]) -> SearchResult:
        """Build a SearchResult from a metadata row dict."""
        description = (row.get("description") or "").strip()
        return SearchResult(
            doc_id=self._make_doc_id(row),
            title=(row.get("title") or "").strip(),
            court=court_label(row["court_code"]),
            date=(row.get("decision_date") or "")[:10] or None,
            snippet=description[:400],
            url=self._public_url(row),
            citation=row.get("citation"),
            neutral_citation=row.get("neutral_citation"),
            judge=(row.get("judge") or "").strip() or None,
            disposal=row.get("disposal_nature"),
            cnr=row.get("cnr"),
        )

    async def find_by_citation(self, citation: str) -> List[SearchResult]:
        """Look up Supreme Court judgments by S.C.R. or neutral citation.

        Only the Supreme Court dataset carries citation fields, so this is the
        authoritative check for ``[2024] 10 S.C.R. 108`` or ``2024INSC735``
        style references.

        Args:
            citation: Citation text to resolve.

        Returns:
            Matching results, usually zero or one.
        """
        if not any(self.sc_metadata_dir.glob("year=*/metadata.parquet")):
            raise CorpusNotSynced(
                "Supreme Court metadata is not synced, so citations cannot be "
                "verified against it. Run 'sync_case_law' with "
                "courts=['Supreme Court']."
            )

        # Strip every separator that varies between citation styles, so
        # "[2024] 10 S.C.R. 108" and "(2024) 10 SCR 108" collapse to one key.
        normalised = re.sub(r"[\s.\[\]()]+", "", citation).lower()
        sql = f"""
            SELECT
                'SC' AS court_code,
                CAST(year AS VARCHAR) AS year,
                NULL AS bench,
                title,
                COALESCE(description, '') AS description,
                COALESCE(judge, '') AS judge,
                citation,
                nc_display AS neutral_citation,
                cnr,
                disposal_nature,
                COALESCE(
                    strftime(try_strptime(decision_date, '%d-%m-%Y'), '%Y-%m-%d'),
                    CAST(decision_date AS VARCHAR)
                ) AS decision_date,
                path AS locator
            FROM read_parquet('{_sql_quote(self._sc_glob())}', hive_partitioning = true, union_by_name = true)
            WHERE regexp_replace(lower(COALESCE(citation, '')), '[\\s.\\[\\]()]+', '', 'g') = ?
               OR regexp_replace(lower(COALESCE(nc_display, '')), '[\\s.\\[\\]()]+', '', 'g') = ?
            LIMIT 5
        """

        def _run() -> List[Dict[str, Any]]:
            con = self._connect()
            cursor = con.execute(sql, [normalised, normalised])
            columns = [d[0] for d in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

        rows = await asyncio.to_thread(_run)
        return [
            SearchResult(
                doc_id=self._make_doc_id(row),
                title=(row.get("title") or "").strip(),
                court="Supreme Court of India",
                date=(row.get("decision_date") or "")[:10] or None,
                snippet=(row.get("description") or "")[:400],
                url=self._public_url(row),
                citation=row.get("citation"),
                neutral_citation=row.get("neutral_citation"),
                judge=(row.get("judge") or "").strip() or None,
                disposal=row.get("disposal_nature"),
                cnr=row.get("cnr"),
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def _parse_doc_id(self, doc_id: str) -> Dict[str, str]:
        """Split a document id back into its locating parts."""
        parts = doc_id.split(":")
        if parts[0] in ("hist", "rc") and len(parts) == 5:
            return {
                "source": parts[0],
                "court_code": parts[1],
                "bench": parts[2],
                "year": parts[3],
                "locator": parts[4],
            }
        if parts[0] == "sc" and len(parts) == 3:
            return {
                "court_code": "SC",
                "year": parts[1],
                "locator": parts[2],
                "bench": "",
            }
        if parts[0] == "hc" and len(parts) == 5:
            return {
                "court_code": parts[1],
                "bench": parts[2],
                "year": parts[3],
                "locator": parts[4],
            }
        raise SourceUnavailable(
            f"Malformed doc_id {doc_id!r}. Use an id returned by search_case_law."
        )

    async def get_judgment(self, doc_id: str) -> Judgment:
        """Download a judgment PDF and extract its text.

        The PDF is cached on disk, so re-opening the same judgment is free and
        offline.

        Args:
            doc_id: Identifier from :meth:`search`.

        Returns:
            The judgment with extracted text.
        """
        parts = self._parse_doc_id(doc_id)

        if parts.get("source") in ("hist", "rc"):
            # Digitized / recently-published corpus: the PDF may already live
            # on disk; otherwise point at the court's own publication URL.
            metadata = await self._lookup_metadata(doc_id, parts)
            rel_pdf = metadata.get("locator") or ""
            pdf = (self.root / rel_pdf) if rel_pdf else None
            if pdf is not None and pdf.exists():
                text = await asyncio.to_thread(self._extract_pdf_text, pdf)
            else:
                text = (
                    "[No local PDF synced. Open the official publication at "
                    f"{metadata.get('source_url') or doc_id}]"
                )
            return Judgment(
                doc_id=doc_id,
                title=metadata.get("title") or doc_id,
                court=court_label(parts["court_code"]),
                date=(metadata.get("decision_date") or "")[:10] or None,
                bench=parts.get("bench") or None,
                text=text,
                url=metadata.get("source_url") or (str(pdf) if pdf is not None else ""),
                citation=metadata.get("citation"),
                neutral_citation=metadata.get("neutral_citation"),
                disposal=metadata.get("disposal_nature"),
                cnr=metadata.get("cnr"),
            )

        url = self._public_url(parts)

        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", doc_id) + ".pdf"
        cached = self.pdf_cache_dir / safe_name

        if not cached.exists() or cached.stat().st_size == 0:
            cached.parent.mkdir(parents=True, exist_ok=True)
            client = self._http_client()
            response = await self._get_with_retry(client, url)
            if response.status_code == 404:
                raise SourceUnavailable(
                    f"No PDF published for {doc_id} at {url}. The metadata row "
                    "exists but the document was not part of the PDF release."
                )
            response.raise_for_status()
            cached.write_bytes(response.content)

        text = await asyncio.to_thread(self._extract_pdf_text, cached)
        metadata = await self._lookup_metadata(doc_id, parts)

        return Judgment(
            doc_id=doc_id,
            title=metadata.get("title") or doc_id,
            court=court_label(parts["court_code"]),
            date=(metadata.get("decision_date") or "")[:10] or None,
            bench=parts.get("bench") or None,
            text=text,
            url=url,
            citation=metadata.get("citation"),
            neutral_citation=metadata.get("neutral_citation"),
            disposal=metadata.get("disposal_nature"),
            cnr=metadata.get("cnr"),
        )

    @staticmethod
    def _extract_pdf_text(path: Path) -> str:
        """Extract text from a judgment PDF, flagging scanned documents."""
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise SourceUnavailable("pypdf is required to read judgment PDFs.") from exc

        reader = PdfReader(str(path))
        pages = [(page.extract_text() or "") for page in reader.pages]
        text = "\n\n".join(p.strip() for p in pages if p.strip())

        if not text.strip():
            return (
                "[No extractable text - this judgment appears to be a scanned "
                "image. The PDF is cached locally and can be OCR'd separately.]"
            )
        return text

    async def _lookup_metadata(
        self, doc_id: str, parts: Dict[str, str]
    ) -> Dict[str, Any]:
        """Fetch the metadata row for a document id, if it is synced."""
        try:
            sql, _ = self._search_sql(
                "SC" if parts["court_code"] == "SC" else parts["court_code"]
            )
        except CorpusNotSynced:
            return {}

        # Locators are bare names for the open-data release but full relative
        # paths for the digitized/recent corpora; match on the file tail.
        predicate = "ends_with(locator, ?)"
        params: List[Any] = [parts["locator"]]

        full_sql = f"SELECT * FROM ({sql}) AS corpus WHERE {predicate} LIMIT 1"

        def _run() -> Dict[str, Any]:
            con = self._connect()
            cursor = con.execute(full_sql, params)
            row = cursor.fetchone()
            if not row:
                return {}
            columns = [d[0] for d in cursor.description]
            return dict(zip(columns, row))

        try:
            return await asyncio.to_thread(_run)
        except Exception as exc:  # pragma: no cover - metadata is best-effort
            logger.warning(f"Could not read metadata for {doc_id}: {exc}")
            return {}

    def corpus_report(self) -> Dict[str, Any]:
        """Describe what is available locally, for the status tool."""
        synced = self.synced_courts()
        pdfs = (
            len(list(self.pdf_cache_dir.glob("*.pdf")))
            if self.pdf_cache_dir.exists()
            else 0
        )
        return {
            "synced": bool(synced),
            "courts": {court_label(code): years for code, years in synced.items()},
            "cached_pdfs": pdfs,
            "data_path": str(self.root),
            "cost": "free - anonymous public S3, no API key, no per-query charge",
            "attribution": ATTRIBUTION,
        }


_client: Optional[OpenJudgmentsClient] = None


def get_client() -> OpenJudgmentsClient:
    """Return the process-wide open-judgments client."""
    global _client
    if _client is None:
        _client = OpenJudgmentsClient()
    return _client


def reset_client() -> None:
    """Drop the cached client, closing its connections. Used by tests."""
    global _client
    if _client is not None:
        _client.close()
    _client = None


async def aclose_client() -> None:
    """Close and drop the shared client if one exists.

    Used by the server's lifespan shutdown so idle DuckDB connections and
    the sync HTTP client never outlive the process; a no-op when nothing
    was instantiated.
    """
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
