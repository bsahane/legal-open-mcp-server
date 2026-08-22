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
        """Persistent DuckDB file holding the FTS corpus table + index."""
        return self.root / "fts" / "corpus.duckdb"

    def _fts_available(self) -> bool:
        """Whether a fresh FTS index exists for the synced corpus.

        The index counts as stale once any metadata Parquet file is newer than
        it, because a sync may have added rows the index does not cover.
        """
        path = self._fts_path()
        if not path.is_file() or path.stat().st_size == 0:
            return False
        index_mtime = path.stat().st_mtime
        for pattern in (
            self.sc_metadata_dir.glob("year=*/metadata.parquet"),
            self.hc_metadata_dir.glob("year=*/court=*/bench=*/metadata.parquet"),
            self.root.glob("historical/*/metadata.parquet"),
            self.root.glob("recent/*/metadata.parquet"),
        ):
            for meta in pattern:
                if meta.stat().st_mtime > index_mtime:
                    return False
        return True

    def _connect_fts(self):
        """Thread-local read-only connection to the FTS corpus file."""
        entry = getattr(self._local, "fts_conn", None)
        if entry is None or entry[0] != self._generation:
            try:
                import duckdb
            except ImportError as exc:  # pragma: no cover - dependency declared
                raise SourceUnavailable(
                    "duckdb is required for open-data case law."
                ) from exc
            conn = duckdb.connect(str(self._fts_path()), read_only=True)
            # The `fts` extension registry is process-local: a fresh process
            # does not inherit LOAD fts from the process that built the index,
            # so every read connection must load it itself.
            conn.execute("LOAD fts")
            with self._conns_lock:
                self._conns.add(conn)
            self._local.fts_conn = (self._generation, conn)
            return conn
        return entry[1]

    def build_fts_index(self, force: bool = False) -> Dict[str, Any]:
        """Build the FTS index over synced metadata into a persistent file.

        The search tool transparently uses this index for BM25-ranked full-text
        search when it is present and fresh, falling back to the LIKE-based
        scan otherwise. Rebuild after every sync that changes the corpus.

        Args:
            force: Rebuild even when the index already looks fresh.

        Returns:
            Summary with the index path and row count.
        """
        sql, _globs = self._search_sql("all")
        path = self._fts_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not force and path.is_file() and path.stat().st_size > 0:
            count = self._fts_row_count()
            if count is not None:
                return {
                    "status": "success",
                    "path": str(path),
                    "rows": count,
                    "rebuilt": False,
                    "message": (
                        "FTS index already present and used by search. Use "
                        "force=True to rebuild it."
                    ),
                }

        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - dependency declared
            raise SourceUnavailable(
                "duckdb is required to build the open-data case-law index."
            ) from exc

        # `fts` ships with DuckDB but must be fetched once on first use.
        probe = duckdb.connect()
        try:
            probe.execute("INSTALL fts")
        except Exception:  # noqa: BLE001 - already present on later installs
            logger.debug("DuckDB FTS extension already installed")
        probe.close()

        con = duckdb.connect(str(path))
        started = time.monotonic()
        try:
            # Large builds (multi-million rows) spill aggressively; keep the
            # memory footprint bounded so containerised builds are not OOM
            # killed mid-write, and disable insertion-order preservation so
            # the corpus table streams straight to disk.
            self._apply_duckdb_resource_guards(con)
            con.execute("LOAD fts")
            logger.info("FTS build: dropping stale tables (if any)")
            # A previous index leaves catalog metadata behind even once its
            # backing tables are gone, and create_fts_index refuses to run
            # over it - remove it explicitly before anything else.
            try:
                con.execute("PRAGMA drop_fts_index('corpus')")
            except Exception as exc:  # noqa: BLE001 - none exists on first build
                logger.debug(f"No stale FTS index to drop: {exc}")
            # Drop leftovers from a previous build so the rebuild is clean.
            for name in (
                "corpus",
                "fts_main_corpus",
                "fts_main_corpus_data",
                "fts_main_corpus_docid",
                "fts_main_corpus_docs",
                "fts_main_corpus_terms",
            ):
                con.execute(f"DROP TABLE IF EXISTS {name}")
            logger.info("FTS build: scanning metadata Parquet into corpus table")
            con.execute(
                f"CREATE TABLE corpus AS "
                f"SELECT row_number() OVER () AS id, * FROM ({sql})"
            )
            count_row = con.execute("SELECT COUNT(*) FROM corpus").fetchone()
            if count_row is None:
                count_row = (0,)
            count = int(count_row[0])
            logger.info(
                f"FTS build: corpus table ready with {count} rows "
                f"in {time.monotonic() - started:.1f}s"
            )
            con.execute(
                "PRAGMA create_fts_index"
                "('corpus', 'id', 'title', 'description', 'judge')"
            )
            logger.info(
                f"FTS build: BM25 index created in "
                f"{time.monotonic() - started:.1f}s total; committing"
            )
        finally:
            con.close()

        elapsed = time.monotonic() - started
        # Invalidate any cached read-only connections to the file.
        self._close_duckdb()
        logger.info(f"FTS build: committed {count} rows to {path} in {elapsed:.1f}s")

        return {
            "status": "success",
            "path": str(path),
            "rows": int(count),
            "rebuilt": True,
            "elapsed_seconds": round(elapsed, 1),
            "message": (
                f"Built the full-text index over {int(count)} judgments in "
                f"{elapsed:.1f}s. Search now uses BM25 ranking."
            ),
        }

    @staticmethod
    def _apply_duckdb_resource_guards(con: Any) -> None:
        """Bound a build connection's memory use; best-effort, never raises.

        Caps DuckDB at ~60% of reported RAM (max 8 GB) when the OS exposes
        it; on any failure the defaults stay in force.
        """
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            page_count = os.sysconf("SC_PHYS_PAGES")
            total_bytes = page_size * page_count
        except (ValueError, OSError, AttributeError):  # pragma: no cover
            return
        limit_bytes = min(int(total_bytes * 0.6), 8 * 1024**3)
        try:
            con.execute(f"SET memory_limit='{limit_bytes // (1024**2)}MB'")
            con.execute("SET preserve_insertion_order=false")
            logger.info(
                f"FTS build: memory_limit="
                f"{limit_bytes // (1024**2)}MB, preserve_insertion_order=off"
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

    def _close_duckdb(self) -> None:
        """Drop every cached DuckDB connection; safe to call repeatedly."""
        self._generation += 1
        with self._conns_lock:
            conns = list(self._conns)
            self._conns.clear()
        for conn in conns:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - best-effort shutdown
                logger.debug("Could not close a DuckDB connection", exc_info=True)

    def _search_sql(self, scope: str) -> Tuple[str, List[str]]:
        """Build the UNION query covering the requested scope.

        Args:
            scope: ``"SC"``, a High Court code, or ``"all"``.

        Returns:
            ``(sql, globs_used)``. The SQL exposes one uniform column set.
        """
        parts: List[str] = []
        globs: List[str] = []

        want_sc = scope in ("SC", "all")
        want_hc = scope != "SC"

        if want_sc and any(self.sc_metadata_dir.glob("year=*/metadata.parquet")):
            globs.append(self._sc_glob())
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
                    NULL                       AS source_url
                FROM read_parquet('{_sql_quote(self._sc_glob())}', hive_partitioning = true, union_by_name = true)
                """
            )

        if want_hc and any(
            self.hc_metadata_dir.glob("year=*/court=*/bench=*/metadata.parquet")
        ):
            globs.append(self._hc_glob())
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
                    NULL                       AS source_url
                FROM read_parquet('{_sql_quote(self._hc_glob())}', hive_partitioning = true, union_by_name = true)
                {court_filter}
                """
            )

        # Digitized pre-1950 corpus harvested from the courts' own archives
        # (see scripts/scrape_bhc_archive.py). Only courts with historical data
        # are matched; scope "all" includes every such court.
        hist_courts = self._historical_courts()
        if hist_courts and (scope in ("all",) or scope in hist_courts):
            globs.append(self._historical_glob())
            hist_filter = ""
            if scope not in ("all", "SC"):
                hist_filter = f"WHERE court = '{_sql_quote(scope)}'"
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
                    source_url
                FROM read_parquet('{_sql_quote(self._historical_glob())}', union_by_name = true)
                {hist_filter}
                """
            )

        # Recently-published judgments scraped from the courts' own sites to
        # bridge the lag of the open-data corpus (see scripts/scrape_recent.py).
        # Same per-court layout and scope semantics as the historical corpus.
        recent_courts = self._recent_courts()
        if recent_courts and (scope in ("all",) or scope in recent_courts):
            globs.append(self._recent_glob())
            recent_filter = ""
            if scope not in ("all", "SC"):
                recent_filter = f"WHERE court = '{_sql_quote(scope)}'"
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
                    source_url
                FROM read_parquet('{_sql_quote(self._recent_glob())}', union_by_name = true)
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
                return await self._search_fts(
                    scope, query, court, from_date, to_date, judge, limit, offset
                )
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
    ) -> List[SearchResult]:
        """BM25-ranked search over the built FTS index.

        The FTS index narrows the candidate set; the same term-level AND
        filters as the LIKE path are re-applied so the two paths agree on what
        matches, differing only in ranking.
        """
        conditions: List[str] = []
        params: List[Any] = []

        terms = [t for t in re.split(r"\s+", query.strip()) if t]
        if terms:
            for term in terms:
                conditions.append("(lower(title) LIKE ? OR lower(description) LIKE ?)")
                like = f"%{term.lower()}%"
                params.extend([like, like])
            fts_query = " ".join(terms)
        else:
            fts_query = query

        if scope != "all":
            conditions.append("court_code = ?")
            params.append(scope)
        if judge:
            conditions.append("lower(judge) LIKE ?")
            params.append(f"%{judge.lower()}%")
        if from_date:
            conditions.append("try_cast(decision_date AS DATE) >= try_cast(? AS DATE)")
            params.append(from_date)
        if to_date:
            conditions.append("try_cast(decision_date AS DATE) <= try_cast(? AS DATE)")
            params.append(to_date)

        fts_where = "fts_main_corpus.match_bm25(c.id, ?) IS NOT NULL"
        if conditions:
            where = f"WHERE {fts_where} AND {' AND '.join(conditions)}"
        else:
            where = f"WHERE {fts_where}"
        full_sql = f"""
            SELECT c.*, fts_main_corpus.match_bm25(c.id, ?) AS _score
            FROM corpus c
            {where}
            ORDER BY _score DESC NULLS LAST,
                     try_cast(c.decision_date AS DATE) DESC NULLS LAST
            LIMIT ?
            OFFSET ?
        """
        params = [fts_query, fts_query, *params, limit, offset]

        def _run() -> List[Dict[str, Any]]:
            con = self._connect_fts()
            cursor = con.execute(full_sql, params)
            columns = [d[0] for d in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            for row in rows:
                row.pop("_score", None)
            return rows

        rows = await asyncio.to_thread(_run)
        return [self._row_to_result(row) for row in rows]

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
