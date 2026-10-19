"""Tests for the nightly data-sync script's index steps.

The steps run unattended under cron, so their contract is: skip cleanly
when the index is fresh, report rows and elapsed time when it rebuilds,
and fail loudly (with timing) when the build blows up.
"""

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent


def _load_daily_sync():
    """Import scripts/daily_sync.py as a module without package machinery."""
    spec = importlib.util.spec_from_file_location(
        "daily_sync_under_test", ROOT / "scripts" / "daily_sync.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _patch_sources(backend="open_data", fresh=False, summary=None, boom=None):
    """Patch the case_law/open_judgments lookups used by _fts_rebuild."""
    client = MagicMock()
    client._fts_available.return_value = fresh
    if boom is not None:
        client.build_fts_index.side_effect = boom
    else:
        client.build_fts_index.return_value = summary or {
            "status": "success",
            "rows": 1234,
            "path": "/data/fts/corpus.sqlite",
            "rebuilt": True,
        }
    return (
        patch(
            "legal_mcp_server.src.sources.case_law.active_backend", return_value=backend
        ),
        patch(
            "legal_mcp_server.src.sources.open_judgments.get_client",
            return_value=client,
        ),
        client,
    )


class TestFtsRebuild:
    """The nightly FTS rebuild step."""

    def test_skips_when_index_fresh(self):
        """A fresh index is left alone and reported as such."""
        daily_sync = _load_daily_sync()
        p_backend, p_client, client = _patch_sources(fresh=True)
        with p_backend, p_client:
            result = daily_sync._fts_rebuild()

        assert result == {"status": "ok", "rebuilt": False}
        client.build_fts_index.assert_not_called()

    def test_rebuilds_when_stale_and_reports_timing(self):
        """A stale index triggers an incremental update with rows and duration."""
        daily_sync = _load_daily_sync()
        p_backend, p_client, client = _patch_sources(fresh=False)
        with p_backend, p_client:
            result = daily_sync._fts_rebuild()

        client.build_fts_index.assert_called_once_with()
        assert result["status"] == "ok"
        assert result["rebuilt"] is True
        assert result["rows"] == 1234
        assert isinstance(result["elapsed_seconds"], float)

    def test_reports_error_with_elapsed_time(self):
        """A failed build surfaces the error plus how long it took."""
        daily_sync = _load_daily_sync()
        p_backend, p_client, _client = _patch_sources(
            boom=RuntimeError("duckdb exploded")
        )
        with p_backend, p_client:
            result = daily_sync._fts_rebuild()

        assert result["status"] == "error"
        assert "duckdb exploded" in result["error"]
        assert isinstance(result["elapsed_seconds"], float)

    def test_skips_for_non_open_data_backend(self):
        """Other backends own their indexing; nothing to do here."""
        daily_sync = _load_daily_sync()
        p_backend, p_client, client = _patch_sources(backend="indian_kanoon")
        with p_backend, p_client:
            result = daily_sync._fts_rebuild()

        assert result["status"] == "skipped"
        client.build_fts_index.assert_not_called()


class TestBodyIndex:
    """The nightly full-text index step."""

    def _run(self, tmp_path, enabled=True, built=True, boom=None, backend="open_data"):
        daily_sync = _load_daily_sync()
        from legal_mcp_server.src.settings import settings
        from legal_mcp_server.src.sources import body_index

        if built:
            (tmp_path / "fts").mkdir()
            (tmp_path / "fts" / "body.sqlite").write_bytes(b"x")
        summary = {
            "indexed": 5,
            "without_text": 1,
            "failed": 0,
            "total_indexed": 105,
            "message": "Indexed 5.",
        }
        build = AsyncMock(side_effect=boom, return_value=summary)
        with (
            patch.object(settings, "CASE_LAW_FULL_TEXT_SEARCH", enabled),
            patch.object(settings, "CASE_LAW_DATA_PATH", str(tmp_path)),
            patch(
                "legal_mcp_server.src.sources.case_law.active_backend",
                return_value=backend,
            ),
            patch.object(body_index, "build", build),
        ):
            return daily_sync._body_index(), build

    def test_updates_with_a_nightly_cap(self, tmp_path):
        result, build = self._run(tmp_path)
        assert result["status"] == "ok"
        assert result["indexed"] == 5
        assert result["total_indexed"] == 105
        assert build.call_args.kwargs["limit"] == result["limit"]

    def test_skips_when_disabled(self, tmp_path):
        result, build = self._run(tmp_path, enabled=False)
        assert result["status"] == "skipped"
        build.assert_not_called()

    def test_skips_before_the_first_manual_build(self, tmp_path):
        result, build = self._run(tmp_path, built=False)
        assert result["status"] == "skipped"
        assert "make fts-body" in result["reason"]
        build.assert_not_called()

    def test_skips_for_non_open_data_backend(self, tmp_path):
        result, build = self._run(tmp_path, backend="disabled")
        assert result["status"] == "skipped"
        build.assert_not_called()

    def test_reports_error(self, tmp_path):
        result, _ = self._run(tmp_path, boom=RuntimeError("disk full"))
        assert result["status"] == "error"
        assert result["error"] == "disk full"
