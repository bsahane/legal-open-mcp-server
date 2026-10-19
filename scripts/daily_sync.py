#!/usr/bin/env python3
"""Daily data pull for the Legal MCP Server.

Scheduled to run every day at 12:00 AM IST (via cron on the LXC host).
Pulls newly published judgment metadata into the local case-law corpus and
refreshes the bundled bare-Acts corpus, so search keeps covering the latest
published judgments.

Safe to run any number of times - files already present are skipped, so an
incremental daily run only downloads what is new.

Run from the project root (settings load ``.env`` relative to CWD)::

    python scripts/daily_sync.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("daily_sync")

# The open-data corpus begins in 1950; the nightly job re-checks the entire
# range through the current year so newly published judgments are picked up
# regardless of their year. Files already present are skipped, so this stays
# cheap even though the range grows over time.
FIRST_AVAILABLE_YEAR = 1950

# Written under LEGAL_DATA_PATH after every run; read by scripts/healthcheck.py.
REPORT_NAME = "daily_sync_report.json"


def _case_law() -> dict:
    from legal_mcp_server.src.settings import settings
    from legal_mcp_server.src.sources import case_law, open_judgments

    if case_law.active_backend() != "open_data":
        return {
            "status": "skipped",
            "reason": f"backend is '{case_law.active_backend()}'",
        }

    courts = ["Supreme Court", f"{settings.DEFAULT_HIGH_COURT} High Court"]
    to_year = date.today().year
    from_year = FIRST_AVAILABLE_YEAR
    log.info("Syncing case law for %s, %d-%d", courts, from_year, to_year)
    client = open_judgments.get_client()
    summary = asyncio.run(
        client.sync(courts=courts, from_year=from_year, to_year=to_year)
    )
    log.info(
        "Case law sync: %d new files, %d MB, %d skipped",
        summary["files"],
        summary["megabytes"],
        summary["skipped"],
    )
    return {"status": "ok", **summary}


def _statutes() -> dict:
    log.info("Refreshing bare-Acts corpus")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "fetch_corpus.py")],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        log.error("Statute corpus refresh failed:\n%s", proc.stderr[-2000:])
        return {
            "status": "error",
            "returncode": proc.returncode,
            "stderr": proc.stderr[-2000:],
        }
    log.info("Statute corpus refreshed")
    return {"status": "ok", "returncode": 0}


def _historical() -> dict:
    """Re-scrape the digitized Bombay High Court archive (pre-1950 corpus).

    The Court digitizes more volumes over time; the scraper is incremental, so
    a nightly run only downloads PDFs that are not already on disk and rewrites
    the historical metadata parquet.
    """
    scraper = ROOT / "scripts" / "scrape_bhc_archive.py"
    if not scraper.exists():
        return {"status": "skipped", "reason": "scraper not present"}
    log.info("Scraping Bombay High Court archive for new digitized judgments")
    proc = subprocess.run(
        [sys.executable, str(scraper), "--download"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        log.error("Archive scrape failed:\n%s", proc.stderr[-2000:])
        return {
            "status": "error",
            "returncode": proc.returncode,
            "stderr": proc.stderr[-2000:],
        }
    log.info("Archive scrape finished")
    return {"status": "ok", "returncode": 0}


def _recent() -> dict:
    """Harvest recently-published judgments from the courts' own sites.

    The open-data corpus refreshes every two months; this bridges the lag so
    searches cover judgments decided in the last few weeks. Incremental: only
    PDFs not already on disk are downloaded.
    """
    scraper = ROOT / "scripts" / "scrape_recent.py"
    if not scraper.exists():
        return {"status": "skipped", "reason": "scraper not present"}
    log.info("Scraping recent judgments from court websites")
    proc = subprocess.run(
        [sys.executable, str(scraper), "--download"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        log.error("Recent-judgments scrape failed:\n%s", proc.stderr[-2000:])
        return {
            "status": "error",
            "returncode": proc.returncode,
            "stderr": proc.stderr[-2000:],
        }
    log.info("Recent-judgments scrape finished")
    return {"status": "ok", "returncode": 0}


def _fts_rebuild() -> dict:
    """Bring the FTS index up to date with the freshly synced corpus.

    Search silently falls back to a slower LIKE scan whenever any synced
    metadata parquet is newer than ``data/case_law/fts/corpus.sqlite``, so
    the nightly job must refresh the index or every search the next day
    pays the fallback cost until someone runs ``make fts`` by hand. Runs
    after all judgment sources (open data + archives) are final so a single
    update covers them. The update re-indexes only the Parquet files the
    sync changed, in place, so it takes seconds and needs no spare disk for
    a second copy of the index.

    The build logs its own progress to stderr (parquet scan, corpus table,
    index creation, commit), so an unattended failure always leaves a trail.
    """
    started = time.monotonic()
    try:
        from legal_mcp_server.src.sources import case_law, open_judgments

        if case_law.active_backend() != "open_data":
            return {
                "status": "skipped",
                "reason": f"backend is '{case_law.active_backend()}'",
            }
        client = open_judgments.get_client()
        if client._fts_available():
            log.info("FTS index already fresh; skipping rebuild")
            return {"status": "ok", "rebuilt": False}
        log.info("Updating FTS index from the synced corpus")
        summary = client.build_fts_index()
        elapsed = round(time.monotonic() - started, 1)
        rows = summary.get("rows")
        path = summary.get("path")
        files = summary.get("files_reindexed")
        log.info(
            "FTS index updated: %s files re-indexed, %s rows in %.1fs at %s",
            files,
            rows,
            elapsed,
            path,
        )
        return {
            "status": "ok",
            "rebuilt": True,
            "full_rebuild": bool(summary.get("rebuilt")),
            "files_reindexed": files,
            "rows": rows,
            "path": path,
            "elapsed_seconds": elapsed,
        }
    except Exception as exc:
        log.exception("FTS rebuild failed after %.1fs", time.monotonic() - started)
        return {
            "status": "error",
            "error": str(exc),
            "elapsed_seconds": round(time.monotonic() - started, 1),
        }


# Judgments whose text one nightly run extracts at most: about ten minutes
# at the ~40/s measured with downloads, several times the ~1,000 judgments
# a day Bombay and the Supreme Court publish, so a backlog drains over a few
# nights instead of one run going on for hours.
BODY_INDEX_NIGHTLY_LIMIT = 20_000


def _body_index() -> dict:
    """Extract the text of newly synced judgments into the full-text index.

    Runs after ``_fts_rebuild`` because it reads the list of judgments from
    the metadata index. Skipped while full-text search is switched off, and
    until the first build, which is a deliberate manual step
    (``make fts-body``, see docs/full-text-search.md).
    """
    started = time.monotonic()
    try:
        from legal_mcp_server.src.settings import settings
        from legal_mcp_server.src.sources import body_index, case_law, open_judgments

        if case_law.active_backend() != "open_data":
            return {
                "status": "skipped",
                "reason": f"backend is '{case_law.active_backend()}'",
            }
        if not settings.CASE_LAW_FULL_TEXT_SEARCH:
            return {"status": "skipped", "reason": "CASE_LAW_FULL_TEXT_SEARCH is off"}
        # A client of its own: the shared one's HTTP session belongs to the
        # case-law sync's event loop, closed by now.
        client = open_judgments.OpenJudgmentsClient()
        if not body_index.index_path(client).is_file():
            return {"status": "skipped", "reason": "not built yet (make fts-body)"}

        async def run() -> dict:
            try:
                return await body_index.build(client, limit=BODY_INDEX_NIGHTLY_LIMIT)
            finally:
                await client.aclose()

        log.info("Extracting new judgment text into the full-text index")
        summary = asyncio.run(run())
        log.info(summary["message"])
        return {
            "status": "ok",
            **{
                k: summary[k]
                for k in ("indexed", "without_text", "failed", "total_indexed")
            },
            "limit": BODY_INDEX_NIGHTLY_LIMIT,
            "elapsed_seconds": round(time.monotonic() - started, 1),
        }
    except Exception as exc:
        log.exception(
            "Full-text index update failed after %.1fs", time.monotonic() - started
        )
        return {
            "status": "error",
            "error": str(exc),
            "elapsed_seconds": round(time.monotonic() - started, 1),
        }


def main() -> int:
    """Run every sync step and print a JSON report of the outcomes.

    Returns:
        0 unless the open-data case-law sync itself failed; failures in the
        other steps are reported in the JSON but do not change the exit code.
    """
    report: dict = {
        "date": date.today().isoformat(),
        "case_law": _case_law(),
        "historical": _historical(),
        "recent": _recent(),
        "fts_index": _fts_rebuild(),
        "body_index": _body_index(),
        "statutes": _statutes(),
    }
    text = json.dumps(report, indent=2, default=str)
    print(text)
    # A fixed location for scripts/healthcheck.py, which alerts on any failed
    # step: the exit code below only covers the case-law sync.
    try:
        from legal_mcp_server.src.settings import settings

        (Path(settings.LEGAL_DATA_PATH) / REPORT_NAME).write_text(text)
    except OSError:
        log.exception("Could not write the sync report for the healthcheck")
    return 0 if report["case_law"].get("status") != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
