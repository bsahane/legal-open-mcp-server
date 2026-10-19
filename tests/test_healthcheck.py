"""Tests for scripts/healthcheck.py: findings and alert de-duplication."""

import importlib.util
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_healthcheck():
    """Import scripts/healthcheck.py as a module without package machinery."""
    spec = importlib.util.spec_from_file_location(
        "healthcheck_under_test", ROOT / "scripts" / "healthcheck.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hc = _load_healthcheck()


def _report(tmp_path: Path, **steps) -> Path:
    path = tmp_path / "daily_sync_report.json"
    path.write_text(json.dumps({"date": "2026-10-19", **steps}))
    return path


def test_clean_report_has_no_problems(tmp_path):
    path = _report(tmp_path, case_law={"status": "ok"}, fts_index={"status": "ok"})
    assert hc.check_report(path, date(2026, 10, 20)) == []


def test_failed_step_and_stale_report_are_flagged(tmp_path):
    path = _report(tmp_path, fts_index={"status": "error", "error": "disk full"})
    problems = hc.check_report(path, date(2026, 10, 25))
    assert any("last ran 2026-10-19" in p for p in problems)
    assert any("fts_index failed: disk full" in p for p in problems)


def test_missing_report_is_flagged(tmp_path):
    assert hc.check_report(tmp_path / "nope.json", date(2026, 10, 20))


def test_disk_threshold(tmp_path):
    assert hc.check_disk(tmp_path, limit=101) is None
    assert "full" in hc.check_disk(tmp_path, limit=0)


def test_same_problems_notify_once_a_day(tmp_path):
    state = tmp_path / "state.json"
    assert hc.should_notify(["a"], state, now=1000) is True
    assert hc.should_notify(["a"], state, now=2000) is False
    assert hc.should_notify(["a", "b"], state, now=2001) is True
    assert hc.should_notify(["a", "b"], state, now=2001 + 86400) is True


def test_unreachable_server_is_flagged():
    assert "failed" in hc.check_health("http://127.0.0.1:9/health")


def test_notify_posts_to_alert_url(monkeypatch):
    sent = {}

    class _Resp:
        def close(self):
            pass

    def fake_urlopen(req, timeout):
        sent["url"], sent["body"] = req.full_url, req.data.decode()
        return _Resp()

    monkeypatch.setattr(hc.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(hc.urllib.request, "urlopen", fake_urlopen)
    hc.notify(["disk 95% full"], "https://ntfy.example/topic")
    assert sent == {
        "url": "https://ntfy.example/topic",
        "body": "legal-mcp: disk 95% full",
    }
