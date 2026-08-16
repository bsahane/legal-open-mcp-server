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


def _case_law() -> dict:
    from legal_mcp_server.src.settings import settings
    from legal_mcp_server.src.sources import case_law
    from legal_mcp_server.src.sources import open_judgments

    if case_law.active_backend() != "open_data":
        return {"status": "skipped", "reason": f"backend is '{case_law.active_backend()}'"}

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


def main() -> int:
    report = {
        "date": date.today().isoformat(),
        "case_law": _case_law(),
        "statutes": _statutes(),
    }
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["case_law"].get("status") != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())