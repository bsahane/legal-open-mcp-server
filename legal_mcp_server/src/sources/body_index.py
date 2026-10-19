"""Full-text (topical) search over extracted judgment text.

The metadata index (``fts/corpus.sqlite``) covers titles, parties, judges and
short descriptions, so a query by legal proposition finds nothing. This module
keeps a second, separate SQLite file, ``fts/body.sqlite``, holding an FTS5
index of the text extracted from judgment PDFs for a chosen set of courts
(the Supreme Court and the Bombay High Court by default).

It is separate from the metadata index because that file is swapped out
whole on a full rebuild and its rowids change on incremental updates; the
body index is keyed by the stable ``doc_id`` instead and only ever grows.
Each run extracts the newest not-yet-indexed judgments first and commits
every batch, so an interrupted build resumes where it stopped.

The FTS5 table is contentless (``content=''``): it stores only the inverted
index, about a third of the text's size, not the text itself. Search results
therefore carry the metadata description, not a matching passage; open the
judgment (or use search_within_judgment) to read the passage.

See docs/full-text-search.md for the measurements behind this design.
"""

from __future__ import annotations

import asyncio
import functools
import io
import itertools
import json
import re
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from legal_mcp_server.src.sources.open_judgments import (
    OpenJudgmentsClient,
    SourceUnavailable,
    court_label,
    resolve_court,
)
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()

DEFAULT_COURTS = ("SC", "27_1")

# Text shorter than this is a scanned image or an empty PDF, not a judgment.
MIN_TEXT_CHARS = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id INTEGER PRIMARY KEY,
    doc_id TEXT UNIQUE NOT NULL,
    court_code TEXT,
    decision_date TEXT,
    chars INTEGER NOT NULL,
    row TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS docs_court ON docs (court_code);
CREATE VIRTUAL TABLE IF NOT EXISTS body_fts USING fts5(
    body, content='', tokenize='porter unicode61 remove_diacritics 2'
);
"""


def index_path(client: OpenJudgmentsClient) -> Path:
    """Location of the body-text index, beside the metadata index."""
    return client.root / "fts" / "body.sqlite"


def version(client: OpenJudgmentsClient) -> str:
    """Token that changes whenever the body index changes."""
    try:
        return str(index_path(client).stat().st_mtime_ns)
    except OSError:
        return "0"


def _pdf_text(data: bytes) -> str:
    """Extract the text layer of a PDF; empty for scans and broken files."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:  # noqa: BLE001 - a broken PDF is recorded as empty
        return ""


async def _fetch_pdf(client: OpenJudgmentsClient, doc_id: str, url: str) -> bytes:
    """PDF bytes from the get_judgment cache, else from public S3.

    Downloads are not cached: the Bombay High Court alone is 88 GB of PDFs.
    A missing PDF (404) returns empty bytes so it is recorded and skipped.
    """
    cached = client.pdf_cache_dir / (re.sub(r"[^A-Za-z0-9_.-]", "_", doc_id) + ".pdf")
    if cached.is_file() and cached.stat().st_size:
        return cached.read_bytes()
    response = await client._get_with_retry(client._http_client(), url)
    if response.status_code == 404:
        return b""
    response.raise_for_status()
    return response.content


def _candidates(client: OpenJudgmentsClient, courts: List[str]) -> Any:
    """Metadata rows for ``courts`` from the metadata index, newest first."""
    con = sqlite3.connect(f"file:{client._fts_path()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    match = " OR ".join(
        f'court_code : "{" ".join(re.findall(r"[A-Za-z0-9]+", c))}"' for c in courts
    )
    try:
        cursor = con.execute(
            "SELECT c.* FROM corpus_fts JOIN corpus c ON c.id = corpus_fts.rowid "
            "WHERE corpus_fts MATCH ? ORDER BY corpus_fts.rowid DESC",
            (match,),
        )
        for row in cursor:
            item = dict(row)
            # "SC" tokens also match e.g. "SCI"; keep exact codes only.
            if item["court_code"] in courts:
                yield item
    finally:
        con.close()


async def build(
    client: OpenJudgmentsClient,
    courts: Optional[List[str]] = None,
    limit: Optional[int] = None,
    workers: int = 4,
    concurrency: int = 16,
    batch_size: int = 64,
) -> Dict[str, Any]:
    """Extract and index judgment text not yet in the body index.

    Args:
        client: Open-data client whose metadata index lists the judgments.
        courts: Court names or codes; defaults to the Supreme Court and Bombay.
        limit: Stop after this many new judgments (``None``: all of them).
        workers: Processes extracting PDF text in parallel.
        concurrency: Simultaneous PDF downloads.
        batch_size: Judgments per committed batch.

    Returns:
        Summary with the counts indexed, skipped and failed.
    """
    codes = [resolve_court(c) or c for c in (courts or DEFAULT_COURTS)]
    if not client._fts_available():
        raise SourceUnavailable(
            "Build the metadata index first (make fts); the body index takes "
            "its list of judgments from it."
        )
    path = index_path(client)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = sqlite3.connect(str(path), timeout=300)
    out.executescript(SCHEMA)
    started = time.monotonic()
    indexed = empty = failed = 0
    sem = asyncio.Semaphore(concurrency)
    loop = asyncio.get_running_loop()

    async def one(pool: ProcessPoolExecutor, row: Dict[str, Any]) -> Any:
        doc_id = client._make_doc_id(row)
        async with sem:
            try:
                data = await _fetch_pdf(client, doc_id, client._public_url(row))
            except Exception as exc:  # noqa: BLE001 - retried on the next run
                logger.warning(f"Body index: could not fetch {doc_id}: {exc}")
                return None
        text = await loop.run_in_executor(pool, _pdf_text, data) if data else ""
        return doc_id, row, text

    fresh = (
        row
        for row in _candidates(client, codes)
        if not out.execute(
            "SELECT 1 FROM docs WHERE doc_id = ?", (client._make_doc_id(row),)
        ).fetchone()
    )
    todo = itertools.islice(fresh, limit)
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            while batch := list(itertools.islice(todo, batch_size)):
                done = await asyncio.gather(*(one(pool, r) for r in batch))
                counts = _store(out, done)
                indexed, empty, failed = (
                    indexed + counts[0],
                    empty + counts[1],
                    failed + counts[2],
                )
                logger.info(f"Body index: {indexed} indexed, {empty} without text")
        total = out.execute("SELECT count(*) FROM docs WHERE chars > 0").fetchone()[0]
    finally:
        out.close()

    elapsed = time.monotonic() - started
    return {
        "status": "success",
        "path": str(path),
        "indexed": indexed,
        "without_text": empty,
        "failed": failed,
        "total_indexed": int(total),
        "elapsed_seconds": round(elapsed, 1),
        "message": (
            f"Indexed the text of {indexed} judgments in {elapsed:.1f}s "
            f"({empty} had no text layer, {failed} could not be fetched and "
            "will be retried on the next run)."
        ),
    }


def _store(out: sqlite3.Connection, done: List[Any]) -> tuple:
    """Write one batch of extracted judgments in a single transaction."""
    indexed = empty = failed = 0
    with out:
        for item in done:
            if item is None:
                failed += 1
                continue
            doc_id, row, text = item
            # Scans and missing PDFs are recorded with chars=0 so they are
            # not downloaded again on every run.
            chars = len(text) if len(text.strip()) >= MIN_TEXT_CHARS else 0
            meta = {k: v for k, v in row.items() if k not in ("id", "_source")}
            rowid = out.execute(
                "INSERT INTO docs (doc_id, court_code, decision_date, chars, row) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    doc_id,
                    row["court_code"],
                    row["decision_date"],
                    chars,
                    json.dumps(meta),
                ),
            ).lastrowid
            if chars:
                out.execute(
                    "INSERT INTO body_fts (rowid, body) VALUES (?, ?)", (rowid, text)
                )
                indexed += 1
            else:
                empty += 1
    return indexed, empty, failed


def _match(query: str) -> Optional[str]:
    """FTS5 expression: every quoted phrase and word must appear."""
    terms = [
        phrase or word for phrase, word in re.findall(r'"([^"]+)"|(\w+)', query.lower())
    ]
    terms = [" ".join(re.findall(r"\w+", t)) for t in terms]
    terms = [t for t in terms if t]
    if not terms:
        return None
    return " AND ".join(f'"{t}"' for t in terms)


def covered_courts(client: OpenJudgmentsClient) -> Dict[str, int]:
    """Judgments with indexed text, per court label; empty without an index.

    Cached per index version: the count is a full scan of ``docs``.
    """
    return dict(_covered(str(index_path(client)), version(client)))


@functools.lru_cache(maxsize=4)
def _covered(path: str, stamp: str) -> Tuple[Tuple[str, int], ...]:
    """Per-court counts for the index at ``path`` as of mtime ``stamp``."""
    if stamp == "0":
        return ()
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT court_code, count(*) FROM docs WHERE chars > 0 GROUP BY 1"
        ).fetchall()
    except sqlite3.DatabaseError:
        return ()
    finally:
        con.close()
    return tuple((court_label(code), int(n)) for code, n in rows)


async def search(
    client: OpenJudgmentsClient,
    query: str,
    court: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    judge: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
) -> List[Dict[str, Any]]:
    """BM25-ranked search over extracted judgment text.

    Words are stemmed (``granted`` matches ``grant``); a quoted phrase must
    appear as written. All terms must appear somewhere in the judgment.

    Args:
        client: Open-data client the index belongs to.
        query: Words and "quoted phrases".
        court: Court name, alias or code.
        from_date: Inclusive lower bound, ``YYYY-MM-DD``.
        to_date: Inclusive upper bound, ``YYYY-MM-DD``.
        judge: Restrict to a judge whose name contains this.
        limit: Maximum results per page.
        page: Zero-based page.

    Returns:
        Result dicts in the same shape as metadata search results.
    """
    path = index_path(client)
    if not path.is_file():
        raise SourceUnavailable(
            "The full-text index has not been built. Run "
            "scripts/build_body_index.py (make fts-body) on the server."
        )
    expr = _match(query)
    if expr is None:
        return []
    conditions = ["body_fts MATCH ?"]
    params: List[Any] = [expr]
    scope = resolve_court(court)
    if scope:
        conditions.append("d.court_code = ?")
        params.append(scope)
    if from_date:
        conditions.append("date(d.decision_date) >= date(?)")
        params.append(from_date)
    if to_date:
        conditions.append("date(d.decision_date) <= date(?)")
        params.append(to_date)
    if judge:
        conditions.append("lower(json_extract(d.row, '$.judge')) LIKE ?")
        params.append(f"%{judge.lower()}%")
    # ponytail: ranks every match; a term in most of the 2.4M judgments
    # ("court") takes seconds. Cap like the metadata index's FTS_RANK_LIMIT
    # if that shows up in practice.
    sql = (
        "SELECT d.row FROM body_fts JOIN docs d ON d.id = body_fts.rowid "
        f"WHERE {' AND '.join(conditions)} ORDER BY body_fts.rank LIMIT ? OFFSET ?"
    )
    params += [limit, max(0, page) * limit]

    def _run() -> List[Dict[str, Any]]:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        try:
            rows = con.execute(sql, params).fetchall()
        finally:
            con.close()
        return [client._row_to_result(json.loads(r[0])).to_dict() for r in rows]

    return await asyncio.to_thread(_run)
