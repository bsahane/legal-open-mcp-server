"""Tests for the store, the eCourts adapter, embeddings and the calendar loader.

These are the pieces that decide what happens when something is missing - no
database, no API key, no installed calendar. Getting the failure path right
matters more here than the happy path, because a silent wrong answer in any of
them looks exactly like a correct one.
"""

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from legal_mcp_server.src.domain import holidays
from legal_mcp_server.src.sources import ecourts
from legal_mcp_server.src.sources import embeddings as emb
from legal_mcp_server.src.storage import legal_store


class TestLegalStore:
    """Pool lifecycle and configuration guards."""

    @pytest.mark.asyncio
    async def test_missing_configuration_is_refused(self):
        """An unconfigured database fails fast with a readable message."""
        store = legal_store.LegalStore()
        with patch.object(legal_store.settings, "POSTGRES_HOST", None):
            with pytest.raises(ConnectionError) as excinfo:
                await store.connect()
        assert "POSTGRES_HOST" in str(excinfo.value)
        assert store.last_error is not None

    @pytest.mark.asyncio
    async def test_health_when_disconnected(self):
        """Health reports disconnected rather than raising."""
        store = legal_store.LegalStore()
        health = await store.health()
        assert health["connected"] is False
        assert health["vector_enabled"] is False

    @pytest.mark.asyncio
    async def test_health_when_connected(self):
        """A live pool reports healthy."""
        store = legal_store.LegalStore()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        store.pool = pool
        store.vector_enabled = True

        health = await store.health()
        assert health["connected"] is True
        assert health["vector_enabled"] is True

    @pytest.mark.asyncio
    async def test_health_surfaces_a_broken_pool(self):
        """A pool that errors on ping reports the error rather than 'connected'."""
        store = legal_store.LegalStore()
        pool = MagicMock()
        pool.acquire.side_effect = RuntimeError("pool is closed")
        store.pool = pool

        health = await store.health()
        assert health["connected"] is False
        assert "pool is closed" in health["error"]

    @pytest.mark.asyncio
    async def test_connect_is_idempotent(self):
        """Connecting twice does not rebuild an existing pool."""
        store = legal_store.LegalStore()
        store.pool = MagicMock()
        await store.connect()  # must return without touching asyncpg

    @pytest.mark.asyncio
    async def test_disconnect_closes_and_clears(self):
        """Disconnect closes the pool and drops the reference."""
        store = legal_store.LegalStore()
        pool = MagicMock()
        pool.close = AsyncMock()
        store.pool = pool
        await store.disconnect()
        pool.close.assert_awaited_once()
        assert store.pool is None

    def test_dsn_is_built_from_settings(self):
        """The DSN reflects the configured connection parameters."""
        store = legal_store.LegalStore()
        with (
            patch.object(legal_store.settings, "POSTGRES_USER", "u"),
            patch.object(legal_store.settings, "POSTGRES_PASSWORD", "p"),
            patch.object(legal_store.settings, "POSTGRES_HOST", "h"),
            patch.object(legal_store.settings, "POSTGRES_PORT", 6543),
            patch.object(legal_store.settings, "POSTGRES_DB", "d"),
        ):
            assert store._dsn() == "postgresql://u:p@h:6543/d"

    def test_singleton_is_stable(self):
        """The shared store is reused across calls."""
        first = legal_store.get_store()
        assert legal_store.get_store() is first

    def test_unavailable_response_shape(self):
        """The standard unavailable response never reads as a success."""
        payload = legal_store.unavailable_response("op", ConnectionError("down"))
        assert payload["status"] == "unavailable"
        assert payload["operation"] == "op"
        assert "nothing was read or written" in payload["message"]

    def test_schema_covers_every_table(self):
        """The schema creates each table the tools query."""
        combined = " ".join(legal_store.SCHEMA_STATEMENTS)
        for table in (
            "matters",
            "hearings",
            "matter_events",
            "documents",
            "document_chunks",
            "saved_research",
        ):
            assert f"CREATE TABLE IF NOT EXISTS {table}" in combined


class TestEcourtsAdapter:
    """Case-status adapters and the CAPTCHA boundary."""

    def test_cnr_instructions(self):
        """A CNR lookup returns the portal URL and the CNR in the steps."""
        result = ecourts.manual_case_status_instructions(cnr="MHMU010123452026")
        assert result["method"] == "cnr_lookup"
        assert any("MHMU010123452026" in step for step in result["steps"])
        assert any("CAPTCHA" in step for step in result["steps"])

    def test_case_number_instructions(self):
        """A case-number search names the court and asks for the CNR back."""
        result = ecourts.manual_case_status_instructions(
            case_number="CC/1234/2026", court="Pune"
        )
        assert result["method"] == "case_number_search"
        assert any("Pune" in step for step in result["steps"])
        assert "CNR number" in result["capture"]

    def test_adapter_status_manual(self):
        """Manual mode declares that it is not automated."""
        with patch.object(ecourts.settings, "ECOURTS_ADAPTER", "manual"):
            status = ecourts.adapter_status()
        assert status["automated"] is False
        assert "CAPTCHA" in status["note"]

    def test_adapter_status_disabled(self):
        """Disabled mode says so."""
        with patch.object(ecourts.settings, "ECOURTS_ADAPTER", "disabled"):
            assert "switched off" in ecourts.adapter_status()["note"]

    @pytest.mark.asyncio
    async def test_api_mode_requires_a_key(self):
        """API mode without a key raises rather than silently degrading."""
        with patch.object(ecourts.settings, "ECOURTS_API_KEY", None):
            with pytest.raises(ecourts.CourtDataUnavailable):
                await ecourts.fetch_case_status_via_api(cnr="X")

    @pytest.mark.asyncio
    async def test_api_mode_requires_an_identifier(self):
        """Neither CNR nor case number is refused."""
        with patch.object(ecourts.settings, "ECOURTS_API_KEY", "k"):
            with pytest.raises(ecourts.CourtDataUnavailable):
                await ecourts.fetch_case_status_via_api()


class TestEmbeddings:
    """Provider selection and its failure reporting."""

    def setup_method(self):
        """Start each test from a clean provider cache."""
        emb.reset_provider()

    def teardown_method(self):
        """Leave no cached provider behind."""
        emb.reset_provider()

    def test_disabled_returns_no_provider(self):
        """Disabled means no provider and no error."""
        with patch.object(emb.settings, "EMBEDDING_PROVIDER", "disabled"):
            assert emb.get_provider() is None

    def test_disabled_status_explains_the_limitation(self):
        """The status says plainly what full-text search cannot do."""
        with patch.object(emb.settings, "EMBEDDING_PROVIDER", "disabled"):
            status = emb.provider_status()
        assert status["semantic_search"] is False
        assert "conceptual queries" in status["note"]

    def test_voyage_without_key_raises(self):
        """Voyage without a key is an explicit configuration error."""
        with (
            patch.object(emb.settings, "EMBEDDING_PROVIDER", "voyage"),
            patch.object(emb.settings, "VOYAGE_API_KEY", None),
        ):
            with pytest.raises(emb.EmbeddingUnavailable) as excinfo:
                emb.get_provider()
            assert "VOYAGE_API_KEY" in str(excinfo.value)

    def test_provider_error_is_cached_and_reported(self):
        """A broken provider is reported in the status, not raised at callers."""
        with (
            patch.object(emb.settings, "EMBEDDING_PROVIDER", "voyage"),
            patch.object(emb.settings, "VOYAGE_API_KEY", None),
        ):
            with pytest.raises(emb.EmbeddingUnavailable):
                emb.get_provider()
            status = emb.provider_status()
        assert status["semantic_search"] is False
        assert "error" in status


class TestHolidayCalendarLoading:
    """Loading an installed calendar file."""

    def setup_method(self):
        """Clear the cached calendar between tests."""
        holidays.reload_calendar()

    def teardown_method(self):
        """Do not leak a test calendar into other tests."""
        holidays.reload_calendar()

    def _install(self, tmp_path, payload):
        reference = tmp_path / "reference"
        reference.mkdir(parents=True, exist_ok=True)
        (reference / holidays.CALENDAR_FILENAME).write_text(json.dumps(payload))
        return patch.object(holidays.settings, "LEGAL_DATA_PATH", str(tmp_path))

    def test_loads_installed_calendar(self, tmp_path):
        """A festival holiday from the calendar is treated as a closure."""
        payload = {
            "Bombay High Court": {
                "2026": [{"date": "2026-10-20", "occasion": "Diwali"}]
            }
        }
        with self._install(tmp_path, payload):
            holidays.reload_calendar()
            assert holidays.holiday_reason(date(2026, 10, 20)) == "Diwali"
            assert holidays.covered_years() == [2026]
            assert holidays.has_calendar_for(date(2026, 10, 20)) is True

    def test_confidence_has_no_caveat_when_covered(self, tmp_path):
        """A covered year drops the warning."""
        payload = {"Bombay High Court": {"2026": []}}
        with self._install(tmp_path, payload):
            holidays.reload_calendar()
            confidence = holidays.calendar_confidence(date(2026, 5, 5))
        assert confidence["year_covered"] is True
        assert confidence["caveat"] is None

    def test_malformed_entries_are_skipped_not_fatal(self, tmp_path):
        """A bad date in the file does not take the calendar down."""
        payload = {
            "Bombay High Court": {
                "2026": [
                    {"date": "not-a-date", "occasion": "Nonsense"},
                    {"date": "2026-10-20", "occasion": "Diwali"},
                ],
                "notayear": [],
            }
        }
        with self._install(tmp_path, payload):
            holidays.reload_calendar()
            assert holidays.holiday_reason(date(2026, 10, 20)) == "Diwali"

    def test_unreadable_file_degrades_to_empty(self, tmp_path):
        """Invalid JSON yields an empty calendar rather than an exception."""
        reference = tmp_path / "reference"
        reference.mkdir(parents=True)
        (reference / holidays.CALENDAR_FILENAME).write_text("{not json")
        with patch.object(holidays.settings, "LEGAL_DATA_PATH", str(tmp_path)):
            holidays.reload_calendar()
            assert holidays.load_calendar() == {}

    def test_known_closures_merges_calendar_and_fixed_dates(self, tmp_path):
        """Both sources appear in the closure list, sorted."""
        payload = {
            "Bombay High Court": {
                "2026": [{"date": "2026-10-20", "occasion": "Diwali"}]
            }
        }
        with self._install(tmp_path, payload):
            holidays.reload_calendar()
            closures = holidays.known_closures(2026)
        occasions = {c["occasion"] for c in closures}
        assert "Diwali" in occasions
        assert "Republic Day" in occasions
        assert [c["date"] for c in closures] == sorted(c["date"] for c in closures)

    def test_working_days_between(self):
        """Working days in a range exclude the weekend."""
        # Mon 3 Aug 2026 to Mon 10 Aug 2026 spans five working days.
        assert holidays.working_days_between(date(2026, 8, 3), date(2026, 8, 10)) == 5

    def test_working_days_between_rejects_inverted_range(self):
        """An end before the start counts zero rather than looping."""
        assert holidays.working_days_between(date(2026, 8, 10), date(2026, 8, 3)) == 0
