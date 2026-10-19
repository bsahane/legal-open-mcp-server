#!/usr/bin/env python3
"""Hourly health check for an unattended Legal MCP deployment.

Checks that the server answers ``/health``, that the data disk has room, and
that last night's ``daily_sync.py`` ran and every step succeeded. Problems
are printed, logged to syslog at error priority, and - when
``LEGAL_MCP_ALERT_URL`` is set in ``.env`` - POSTed there as plain text (an ntfy.sh topic
URL works as-is). The same set of problems is announced at most once a day,
so an hourly cron does not page every hour.

Run from the project root, e.g. from cron::

    15 * * * * cd /opt/legal-mcp && .venv/bin/python scripts/healthcheck.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DISK_ALERT_PERCENT = 90
REPORT_MAX_AGE_DAYS = 2
REPEAT_AFTER_SECONDS = 86400


def check_health(url: str) -> Optional[str]:
    """Return a problem if the server's /health endpoint is not healthy."""
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # nosec B310
            body = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001 - any failure is the finding
        return f"server health check failed: {exc}"
    if body.get("status") != "healthy":
        return f"server reports {body.get('status')!r}"
    return None


def check_disk(path: Path, limit: int = DISK_ALERT_PERCENT) -> Optional[str]:
    """Return a problem if the filesystem holding ``path`` is nearly full."""
    usage = shutil.disk_usage(path)
    used = round(100 * usage.used / usage.total)
    if used >= limit:
        free_gb = usage.free / 1024**3
        return f"disk {used}% full at {path} ({free_gb:.1f} GB free)"
    return None


def check_report(path: Path, today: date) -> List[str]:
    """Return problems found in the nightly sync report."""
    try:
        report = json.loads(path.read_text())
    except FileNotFoundError:
        return [f"no nightly sync report at {path}"]
    except ValueError as exc:
        return [f"nightly sync report unreadable: {exc}"]
    problems = []
    ran = date.fromisoformat(report.get("date", "1970-01-01"))
    if today - ran > timedelta(days=REPORT_MAX_AGE_DAYS):
        problems.append(f"nightly sync last ran {ran}")
    for step, outcome in report.items():
        if isinstance(outcome, dict) and outcome.get("status") == "error":
            detail = outcome.get("error") or outcome.get("stderr") or ""
            problems.append(f"nightly {step} failed: {str(detail)[-300:]}")
    return problems


def should_notify(problems: List[str], state: Path, now: float) -> bool:
    """True when these problems are new, or were last sent a day ago."""
    key = "\n".join(sorted(problems))
    try:
        last = json.loads(state.read_text())
    except (FileNotFoundError, ValueError):
        last = {}
    if last.get("key") == key and now - last.get("at", 0) < REPEAT_AFTER_SECONDS:
        return False
    state.write_text(json.dumps({"key": key, "at": now}))
    return True


def notify(problems: List[str], url: Optional[str]) -> None:
    """Log to syslog and, if configured, POST to the alert URL."""
    text = "legal-mcp: " + "; ".join(problems)
    subprocess.run(  # nosec B603 B607 - fixed argv, no shell
        ["logger", "-p", "user.err", "-t", "legal-mcp-health", text], check=False
    )
    if url:
        req = urllib.request.Request(url, data=text.encode(), method="POST")
        try:
            urllib.request.urlopen(req, timeout=10).close()  # nosec B310
        except Exception as exc:  # noqa: BLE001 - alerting must not crash
            print(f"alert POST failed: {exc}", file=sys.stderr)


def main() -> int:
    """Run every check; return 1 if anything is wrong."""
    from legal_mcp_server.src.settings import settings

    data = Path(settings.LEGAL_DATA_PATH)
    problems = [
        p
        for p in (
            check_health(f"http://127.0.0.1:{settings.MCP_PORT}/health"),
            check_disk(Path(settings.CASE_LAW_DATA_PATH)),
        )
        if p
    ]
    problems += check_report(data / "daily_sync_report.json", date.today())
    if not problems:
        print("ok")
        return 0
    print("\n".join(problems))
    if should_notify(problems, data / ".healthcheck_state.json", time.time()):
        notify(problems, settings.LEGAL_MCP_ALERT_URL)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
