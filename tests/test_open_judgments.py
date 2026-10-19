"""Tests for the free open-data case-law backend and the research tools.

No network access and no API key. A small Parquet fixture is written to a temp
directory and queried through DuckDB exactly as the real corpus is, so the SQL,
the citation matching and the doc-id round trip are all genuinely exercised.
"""

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from legal_mcp_server.src.domain import citations as cit
from legal_mcp_server.src.sources import case_law, open_judgments
from legal_mcp_server.src.tools import research_tools

SC_ROWS: List[Dict[str, Any]] = [
    {
        "title": "VIJAY SINGH versus THE STATE OF BIHAR",
        "petitioner": "VIJAY SINGH",
        "respondent": "THE STATE OF BIHAR",
        "description": "Appeal against conviction under sections 302/34 IPC.",
        "judge": "BELA M. TRIVEDI",
        "citation": "[2024] 10 S.C.R. 108",
        "cnr": "SCIN010001112024",
        "decision_date": "25-09-2024",
        "disposal_nature": "Allowed",
        "court": "Supreme Court of India",
        "nc_display": "2024INSC735",
        "path": "2024_10_108_125",
        "year": "2024",
    },
    {
        "title": "SUNITA DEVI versus THE STATE OF BIHAR",
        "petitioner": "SUNITA DEVI",
        "respondent": "THE STATE OF BIHAR",
        "description": "Bail matter concerning territorial jurisdiction.",
        "judge": "SUDHANSHU DHULIA",
        "citation": "[2024] 5 S.C.R. 629",
        "cnr": "SCIN010002222024",
        "decision_date": "12-05-2024",
        "disposal_nature": "Dismissed",
        "court": "Supreme Court of India",
        "nc_display": "2024INSC448",
        "path": "2024_5_629_729",
        "year": "2024",
    },
]

HC_ROWS: List[Dict[str, Any]] = [
    {
        "court_code": "27_1",
        "title": "MCA/130/2024 of ANGELA PEREIRA Vs VILAS NAIK",
        "description": "Miscellaneous civil application for substituted service.",
        "judge": "REGISTRAR",
        "pdf_link": "court/cnrorders/hcbgoa/orders/HCBM05000392_1_2024-04-25.pdf",
        "cnr": "HCBM050003922024",
        "date_of_registration": "2024-01-02",
        "decision_date": "2024-04-25",
        "disposal_nature": "Allowed",
        "court": "27_1",
        "raw_html": "",
        "pdf_exists": True,
    }
]


def _write_parquet(rows: List[Dict[str, Any]], target: Path) -> None:
    """Write rows to a Parquet file using DuckDB, mirroring the real layout."""
    import duckdb

    target.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        columns = list(rows[0].keys())
        selects = []
        for row in rows:
            literals = []
            for col in columns:
                value = row[col]
                if isinstance(value, bool):
                    literals.append("TRUE" if value else "FALSE")
                elif value is None:
                    literals.append("NULL")
                else:
                    escaped = str(value).replace("'", "''")
                    literals.append(f"'{escaped}'")
            selects.append(
                "SELECT "
                + ", ".join(f"{lit} AS {col}" for lit, col in zip(literals, columns))
            )
        con.execute(
            f"COPY ({' UNION ALL '.join(selects)}) TO '{target}' (FORMAT PARQUET)"
        )
    finally:
        con.close()


@pytest.fixture
def corpus(tmp_path: Path):
    """A synced-looking local corpus with one SC year and one HC bench."""
    _write_parquet(
        SC_ROWS, tmp_path / "sc" / "metadata" / "year=2024" / "metadata.parquet"
    )
    _write_parquet(
        HC_ROWS,
        tmp_path
        / "hc"
        / "metadata"
        / "year=2024"
        / "court=27_1"
        / "bench=hcbgoa"
        / "metadata.parquet",
    )

    client = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
    with patch.object(open_judgments, "get_client", return_value=client):
        yield client


class TestCourtResolution:
    """Court names, aliases and codes all have to land on the same code."""

    def test_supreme_court_aliases(self):
        for name in ["Supreme Court", "supreme court of india", "SC", "sci"]:
            assert open_judgments.resolve_court(name) == "SC"

    def test_bombay_aliases(self):
        for name in ["Bombay", "bombay high court", "Mumbai", "27_1"]:
            assert open_judgments.resolve_court(name) == "27_1"

    def test_none_means_all_courts(self):
        assert open_judgments.resolve_court(None) is None

    def test_unknown_court_is_rejected_not_guessed(self):
        with pytest.raises(open_judgments.SourceUnavailable) as exc:
            open_judgments.resolve_court("Atlantis High Court")
        assert "Unknown court" in str(exc.value)

    def test_court_label_is_human_readable(self):
        assert open_judgments.court_label("SC") == "Supreme Court of India"
        assert open_judgments.court_label("27_1") == "Bombay High Court"


class TestSyncState:
    """An unsynced corpus must say so rather than look empty."""

    def test_unsynced_reports_not_synced(self, tmp_path: Path):
        client = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        assert client.is_synced() is False
        assert client.corpus_report()["synced"] is False

    def test_synced_lists_courts_and_years(self, corpus):
        synced = corpus.synced_courts()
        assert synced["SC"] == [2024]
        assert synced["27_1"] == [2024]

    def test_report_names_courts_and_states_it_is_free(self, corpus):
        report = corpus.corpus_report()
        assert report["synced"] is True
        assert "Supreme Court of India" in report["courts"]
        assert "free" in report["cost"]

    def test_year_ranges_collapse_runs_and_keep_gaps(self):
        assert open_judgments.year_ranges([1953, 1950, 1952, 1954, 2026]) == (
            "1950, 1952-1954, 2026"
        )
        assert open_judgments.year_ranges([]) == ""

    @pytest.mark.asyncio
    async def test_search_without_sync_raises_corpus_not_synced(self, tmp_path: Path):
        client = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with pytest.raises(open_judgments.CorpusNotSynced) as exc:
            await client.search("anything")
        assert "sync_case_law" in str(exc.value)

    @pytest.mark.asyncio
    async def test_sync_rejects_reversed_year_range(self, tmp_path: Path):
        client = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with pytest.raises(open_judgments.SourceUnavailable):
            await client.sync(["Supreme Court"], from_year=2026, to_year=2020)


class TestSearch:
    """Search runs real SQL over the fixture Parquet."""

    @pytest.mark.asyncio
    async def test_finds_by_party_name(self, corpus):
        results = await corpus.search("Vijay Singh")
        assert len(results) == 1
        assert "VIJAY SINGH" in results[0].title
        assert results[0].citation == "[2024] 10 S.C.R. 108"
        assert results[0].neutral_citation == "2024INSC735"

    @pytest.mark.asyncio
    async def test_all_terms_must_match(self, corpus):
        assert await corpus.search("Vijay Bihar") != []
        assert await corpus.search("Vijay Kerala") == []

    @pytest.mark.asyncio
    async def test_matches_description_text(self, corpus):
        results = await corpus.search("territorial jurisdiction")
        assert len(results) == 1
        assert "SUNITA DEVI" in results[0].title

    @pytest.mark.asyncio
    async def test_court_filter_scopes_results(self, corpus):
        assert len(await corpus.search("Bihar", court="Supreme Court")) == 2
        assert await corpus.search("Bihar", court="Bombay High Court") == []

    @pytest.mark.asyncio
    async def test_high_court_rows_are_searchable(self, corpus):
        results = await corpus.search("PEREIRA", court="Bombay High Court")
        assert len(results) == 1
        assert results[0].court == "Bombay High Court"

    @pytest.mark.asyncio
    async def test_judge_filter(self, corpus):
        assert len(await corpus.search("Bihar", judge="Trivedi")) == 1
        assert await corpus.search("Bihar", judge="Nonexistent") == []

    @pytest.mark.asyncio
    async def test_date_bounds(self, corpus):
        assert len(await corpus.search("Bihar", from_date="2024-06-01")) == 1
        assert len(await corpus.search("Bihar", to_date="2024-06-01")) == 1

    @pytest.mark.asyncio
    async def test_limit_is_respected(self, corpus):
        assert len(await corpus.search("Bihar", limit=1)) == 1

    @pytest.mark.asyncio
    async def test_doc_ids_round_trip(self, corpus):
        for result in await corpus.search("Bihar"):
            parsed = corpus._parse_doc_id(result.doc_id)
            assert parsed["court_code"] == "SC"

    @pytest.mark.asyncio
    async def test_urls_point_at_public_bucket(self, corpus):
        results = await corpus.search("Vijay Singh")
        url = results[0].url
        assert url.startswith("https://indian-supreme-court-judgments.s3.")
        assert url.endswith("_EN.pdf")

    @pytest.mark.asyncio
    async def test_quote_in_query_does_not_break_sql(self, corpus):
        assert await corpus.search("O'Brien") == []


class TestCitationLookup:
    """Citation verification is the anti-hallucination guardrail."""

    @pytest.mark.asyncio
    async def test_official_scr_citation_matches(self, corpus):
        results = await corpus.find_by_citation("[2024] 10 S.C.R. 108")
        assert len(results) == 1
        assert "VIJAY SINGH" in results[0].title

    @pytest.mark.asyncio
    async def test_citation_matching_ignores_punctuation_style(self, corpus):
        for form in [
            "[2024] 10 S.C.R. 108",
            "(2024) 10 SCR 108",
            "2024 10 SCR 108",
        ]:
            assert len(await corpus.find_by_citation(form)) == 1, form

    @pytest.mark.asyncio
    async def test_neutral_citation_matches(self, corpus):
        results = await corpus.find_by_citation("2024INSC735")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_fabricated_citation_finds_nothing(self, corpus):
        assert await corpus.find_by_citation("[2024] 99 S.C.R. 9999") == []
        assert await corpus.find_by_citation("2024INSC999999") == []

    @pytest.mark.asyncio
    async def test_unsynced_sc_cannot_silently_pass_a_citation(self, tmp_path: Path):
        client = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with pytest.raises(open_judgments.CorpusNotSynced):
            await client.find_by_citation("[2024] 10 S.C.R. 108")


class TestCitationParsing:
    """The parser must recognise the formats the free corpus actually uses."""

    def test_square_bracket_scr_is_parsed(self):
        parsed = cit.parse_citation("[2024] 10 S.C.R. 108")
        assert parsed is not None
        assert parsed.kind is cit.CitationKind.CASE
        assert parsed.year == 2024

    def test_compact_neutral_citation_is_parsed(self):
        parsed = cit.parse_citation("2024INSC735")
        assert parsed is not None
        assert parsed.normalized == "2024INSC735"
        assert parsed.year == 2024

    def test_traditional_scc_still_parses(self):
        parsed = cit.parse_citation("(2019) 5 SCC 266")
        assert parsed is not None
        assert parsed.reporter == "SCC"


class TestBackendSelection:
    """The default must be the free backend, and 'disabled' must be honoured."""

    def test_default_backend_is_open_data(self):
        assert case_law.active_backend() == "open_data"

    @pytest.mark.asyncio
    async def test_disabled_backend_refuses_clearly(self):
        with patch.object(case_law.settings, "CASE_LAW_SOURCE", "disabled"):
            with pytest.raises(case_law.CaseLawDisabled):
                await case_law.search("anything")

    def test_status_reports_free_cost_model(self, corpus):
        status = case_law.status()
        assert status["backend"] == "open_data"
        assert "free" in status["cost"]


class TestResearchTools:
    """Tool-level contract: shape, honesty, and no silent gaps."""

    @pytest.mark.asyncio
    async def test_search_tool_cache_misses_after_a_sync(self, corpus, tmp_path):
        """A sync adds judgments; the cached pre-sync answer must not win."""
        from legal_mcp_server.src import cache as cache_mod

        with patch.object(
            open_judgments.settings, "LEGAL_DATA_PATH", str(tmp_path / "cache")
        ):
            cache_mod._get_cache.cache_clear()
            try:
                first = await research_tools.search_case_law("Zebra")
                zebra = dict(SC_ROWS[0], title="ZEBRA versus STATE", path="z_9")
                _write_parquet(
                    [zebra], corpus.sc_metadata_dir / "year=2025" / "metadata.parquet"
                )
                second = await research_tools.search_case_law("Zebra")
            finally:
                cache_mod._get_cache.cache_clear()

        assert first["result_count"] == 0
        assert second["cached"] is False
        assert second["result_count"] == 1

    @pytest.mark.asyncio
    async def test_search_tool_returns_results_and_cost(self, corpus):
        result = await research_tools.search_case_law("Vijay Singh")
        assert result["status"] == "success"
        assert result["result_count"] == 1
        assert result["backend"] == "open_data"
        assert "free" in result["cost"]
        assert "scope_note" in result

    @pytest.mark.asyncio
    async def test_search_tool_rejects_empty_query(self, corpus):
        result = await research_tools.search_case_law("   ")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_unsynced_search_is_unavailable_not_empty(self, tmp_path: Path):
        client = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with patch.object(open_judgments, "get_client", return_value=client):
            result = await research_tools.search_case_law("anything")
        assert result["status"] == "unavailable"
        assert "do not substitute recalled case law" in result["message"]

    @pytest.mark.asyncio
    async def test_verify_real_citation(self, corpus):
        result = await research_tools.verify_citation("[2024] 10 S.C.R. 108")
        assert result["verdict"] == "VERIFIED"
        assert result["matches"]

    @pytest.mark.asyncio
    async def test_verify_fabricated_citation(self, corpus):
        result = await research_tools.verify_citation("[2024] 99 S.C.R. 9999")
        assert result["verdict"] == "NOT_FOUND"
        assert "unverified" in result["note"].lower()

    @pytest.mark.asyncio
    async def test_not_found_note_mentions_sync_coverage(self, corpus):
        result = await research_tools.verify_citation("[2024] 99 S.C.R. 9999")
        assert "synced" in result["note"]

    @pytest.mark.asyncio
    async def test_verification_disabled_says_so(self, corpus):
        with patch.object(
            research_tools.settings, "ENABLE_CITATION_VERIFICATION", False
        ):
            result = await research_tools.verify_citation("[2024] 10 S.C.R. 108")
        assert result["verdict"] == "UNCHECKED"
        assert "no lookup was" in result["note"]

    @pytest.mark.asyncio
    async def test_status_tool_reports_coverage(self, corpus):
        result = research_tools.case_law_status()
        assert result["status"] == "success"
        assert result["backend"] == "open_data"
        assert "Supreme Court of India" in result["courts"]

    @pytest.mark.asyncio
    async def test_sync_tool_refuses_on_paid_backend(self):
        with patch.object(case_law.settings, "CASE_LAW_SOURCE", "indian_kanoon"):
            result = await research_tools.sync_case_law()
        assert result["status"] == "error"
        assert "open-data" in result["message"]

    @pytest.mark.asyncio
    async def test_memo_gathers_and_refuses_to_draft(self, corpus):
        result = await research_tools.build_research_memo(
            "Conviction under section 302 IPC", queries=["Vijay Singh"]
        )
        assert result["status"] == "success"
        assert result["authority_count"] == 1
        assert "evidence base, not a memo" in result["message"]

    @pytest.mark.asyncio
    async def test_memo_rejects_empty_issue(self, corpus):
        result = await research_tools.build_research_memo("")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_related_proceedings_is_not_presented_as_a_citator(self, corpus):
        judgment = open_judgments.Judgment(
            doc_id="sc:2024:2024_10_108_125",
            title="VIJAY SINGH versus THE STATE OF BIHAR",
            court="Supreme Court of India",
            date="2024-09-25",
            bench=None,
            text="text",
            url="https://example.invalid/x.pdf",
        )
        with patch.object(corpus, "get_judgment", return_value=judgment):
            result = await research_tools.find_related_proceedings(
                "sc:2024:2024_10_108_125"
            )
        assert result["status"] == "success"
        assert result["is_citator"] is False
        assert "NOT a citator" in result["message"]

    @pytest.mark.asyncio
    async def test_malformed_doc_id_is_rejected(self, corpus):
        result = await research_tools.get_judgment("not-a-real-id")
        assert result["status"] in ("error", "unavailable")


class TestToolWrappers:
    """The tool layer's own contract: validation, shape and honest messages."""

    @pytest.mark.asyncio
    async def test_get_judgment_returns_text_and_cost(self, corpus):
        judgment = open_judgments.Judgment(
            doc_id="sc:2024:2024_10_108_125",
            title="VIJAY SINGH versus THE STATE OF BIHAR",
            court="Supreme Court of India",
            date="2024-09-25",
            bench=None,
            text="A" * 500,
            url="https://example.invalid/x.pdf",
            citation="[2024] 10 S.C.R. 108",
        )
        with patch.object(corpus, "get_judgment", return_value=judgment):
            result = await research_tools.get_judgment("sc:2024:2024_10_108_125")

        assert result["status"] == "success"
        assert result["truncated"] is False
        assert "free" in result["cost"]
        assert result["citation"] == "[2024] 10 S.C.R. 108"

    @pytest.mark.asyncio
    async def test_get_judgment_discloses_truncation(self, corpus):
        judgment = open_judgments.Judgment(
            doc_id="sc:2024:x",
            title="T",
            court="Supreme Court of India",
            date="2024-01-01",
            bench=None,
            text="B" * 5000,
            url="https://example.invalid/x.pdf",
        )
        with patch.object(corpus, "get_judgment", return_value=judgment):
            result = await research_tools.get_judgment("sc:2024:x", max_chars=100)

        assert result["truncated"] is True
        assert len(result["text"]) == 100
        assert "truncated" in result["message"]

    @pytest.mark.asyncio
    async def test_get_judgment_rejects_blank_id(self, corpus):
        assert (await research_tools.get_judgment("   "))["status"] == "error"

    @pytest.mark.asyncio
    async def test_search_within_judgment_finds_passages(self, corpus):
        judgment = open_judgments.Judgment(
            doc_id="sc:2024:x",
            title="T",
            court="Supreme Court of India",
            date="2024-01-01",
            bench=None,
            text="The question of territorial jurisdiction arises here.",
            url="https://example.invalid/x.pdf",
        )
        with patch.object(corpus, "get_judgment", return_value=judgment):
            result = await research_tools.search_within_judgment(
                "sc:2024:x", "jurisdiction"
            )

        assert result["status"] == "success"
        assert result["match_count"] == 1
        assert "jurisdiction" in result["passages"][0]["passage"]

    @pytest.mark.asyncio
    async def test_search_within_judgment_explains_no_match(self, corpus):
        judgment = open_judgments.Judgment(
            doc_id="sc:2024:x",
            title="T",
            court="Supreme Court of India",
            date="2024-01-01",
            bench=None,
            text="Nothing relevant here.",
            url="https://example.invalid/x.pdf",
        )
        with patch.object(corpus, "get_judgment", return_value=judgment):
            result = await research_tools.search_within_judgment(
                "sc:2024:x", "arbitration"
            )

        assert result["match_count"] == 0
        assert "try a synonym" in result["message"]

    @pytest.mark.asyncio
    async def test_search_within_judgment_validates_inputs(self, corpus):
        assert (await research_tools.search_within_judgment("", "x"))[
            "status"
        ] == "error"
        assert (await research_tools.search_within_judgment("sc:2024:x", "  "))[
            "status"
        ] == "error"

    @pytest.mark.asyncio
    async def test_sync_tool_defaults_to_sc_plus_default_high_court(self, corpus):
        captured = {}

        async def fake_sync(courts, from_year, to_year, force):
            captured["courts"] = courts
            return {
                "courts": {},
                "files": 0,
                "bytes": 0,
                "skipped": 0,
                "megabytes": 0.0,
            }

        with patch.object(corpus, "sync", side_effect=fake_sync):
            result = await research_tools.sync_case_law()

        assert result["status"] == "success"
        assert "Supreme Court" in captured["courts"]
        assert any("High Court" in c for c in captured["courts"])

    @pytest.mark.asyncio
    async def test_sync_tool_passes_explicit_courts_and_years(self, corpus):
        captured = {}

        async def fake_sync(courts, from_year, to_year, force):
            captured.update(courts=courts, from_year=from_year, to_year=to_year)
            return {
                "courts": {},
                "files": 2,
                "bytes": 10,
                "skipped": 0,
                "megabytes": 0.1,
            }

        with patch.object(corpus, "sync", side_effect=fake_sync):
            result = await research_tools.sync_case_law(
                courts=["Delhi"], from_year=2020, to_year=2021
            )

        assert captured["courts"] == ["Delhi"]
        assert (captured["from_year"], captured["to_year"]) == (2020, 2021)
        assert result["files"] == 2

    @pytest.mark.asyncio
    async def test_sync_tool_surfaces_unknown_court(self, corpus):
        async def boom(**_kw):
            raise open_judgments.SourceUnavailable("Unknown court 'Nowhere'")

        with patch.object(corpus, "sync", side_effect=boom):
            result = await research_tools.sync_case_law(courts=["Nowhere"])

        assert result["status"] == "unavailable"


class TestFullTextIndex:
    """BM25 index: buildable, transparently used, and honestly reported stale."""

    def _build(self, corpus):
        try:
            return corpus.build_fts_index()
        except Exception as exc:  # noqa: BLE001 - extension may be unavailable
            pytest.skip(f"SQLite FTS5 not usable here: {exc}")

    def test_fts_unavailable_before_build(self, corpus):
        assert corpus._fts_available() is False

    def test_build_index_reports_rows(self, corpus):
        result = self._build(corpus)
        assert result["status"] == "success"
        assert result["rebuilt"] is True
        assert result["rows"] == 3  # 2 SC + 1 HC fixture rows
        assert corpus._fts_available() is True
        assert corpus._fts_row_count() == 3

    def test_rebuild_without_force_is_a_noop(self, corpus):
        self._build(corpus)
        result = corpus.build_fts_index()
        assert result["rebuilt"] is False
        assert result["rows"] == 3

    def test_forced_rebuild_over_existing_index_succeeds(self, corpus):
        """Rebuilding twice must not trip over the previous index.

        Regression: create_fts_index refuses to run while catalog metadata
        from the old index lingers; a stale-index drop has to happen first.
        """
        first = self._build(corpus)
        assert first["rebuilt"] is True

        try:
            second = corpus.build_fts_index(force=True)
        except Exception as exc:  # noqa: BLE001 - extension may be unavailable
            pytest.skip(f"SQLite FTS5 not usable here: {exc}")

        assert second["status"] == "success"
        assert second["rebuilt"] is True
        assert second["rows"] == 3
        assert "elapsed_seconds" in second
        assert corpus._fts_available() is True

    def test_rebuild_while_reader_holds_live_file(self, corpus):
        """A held reader must not block a rebuild, and must see the new index.

        Regression: the nightly cron rebuilt in place and hit the lock held by
        the running server. The rebuild now writes a side file and swaps it
        in; readers reopen on the new inode.
        """
        import sqlite3

        self._build(corpus)
        old_reader = corpus._connect_fts()
        outside = sqlite3.connect(f"file:{corpus._fts_path()}?mode=ro", uri=True)
        outside.execute("SELECT count(*) FROM corpus").fetchone()
        try:
            result = corpus.build_fts_index(force=True)
        finally:
            outside.close()

        assert result["rebuilt"] is True
        assert not corpus._fts_path().with_name("corpus.sqlite.building").exists()
        reader = corpus._connect_fts()
        assert reader is not old_reader
        hits = reader.execute(
            "SELECT count(*) FROM corpus_fts WHERE corpus_fts MATCH 'bihar'"
        ).fetchone()
        assert hits[0] >= 1

    def test_swap_closes_idle_threads_handles(self, corpus):
        """After a rebuild from another process, no thread pins the old file."""
        import threading

        self._build(corpus)
        idle = {}
        thread = threading.Thread(target=lambda: idle.update(c=corpus._connect_fts()))
        thread.start()
        thread.join()
        corpus._connect_fts()  # this thread's handle, same inode

        # Simulate the nightly cron: a rebuild in another client instance.
        other = open_judgments.OpenJudgmentsClient(data_path=str(corpus.root))
        other.build_fts_index(force=True)
        corpus._connect_fts()  # first search after the swap

        assert idle["c"] not in corpus._conns
        with pytest.raises(Exception):
            idle["c"].execute("SELECT 1")  # closed, so the old inode is free

    def test_build_uses_temp_dir_and_clears_crash_leftovers(self, corpus, tmp_path):
        """A crashed build's journal and spill dir must not survive a rebuild."""
        live = corpus._fts_path()
        live.parent.mkdir(parents=True, exist_ok=True)
        journal = live.with_name("corpus.sqlite.building-journal")
        spill = live.with_name("corpus.sqlite.building.tmp")
        journal.write_bytes(b"stale")
        spill.mkdir()
        scratch = tmp_path / "scratch"

        with patch.object(open_judgments.settings, "FTS_BUILD_TEMP_DIR", str(scratch)):
            result = self._build(corpus)

        assert result["rebuilt"] is True
        assert scratch.is_dir()
        assert not journal.exists()
        assert not spill.exists()

    @pytest.mark.asyncio
    async def test_fts_court_filter_matches_like(self, corpus):
        """Court narrowing happens inside FTS5 and agrees with the LIKE path."""
        like = await corpus.search("Bihar", court="Supreme Court")
        self._build(corpus)
        with patch.object(corpus, "_connect", side_effect=AssertionError("LIKE")):
            fts = await corpus.search("Bihar", court="Supreme Court")
        assert {h.doc_id for h in fts} == {h.doc_id for h in like}
        assert fts and all(h.court == "Supreme Court of India" for h in fts)

    @pytest.mark.asyncio
    async def test_fts_prefix_term_matches_like(self, corpus):
        """A word fragment finds what the LIKE substring test finds."""
        like = await corpus.search("Bih")
        self._build(corpus)
        fts = await corpus.search("Bih")
        assert like
        assert {h.doc_id for h in fts} == {h.doc_id for h in like}

    @pytest.mark.asyncio
    async def test_stopwords_are_checked_exactly_on_fts_candidates(self, corpus):
        """ "State Bihar" ranks on Bihar in FTS5 and checks "state" with LIKE."""
        like = await corpus.search("State of Bihar")
        self._build(corpus)
        with patch.object(corpus, "_connect", side_effect=AssertionError("LIKE")):
            fts = await corpus.search("State of Bihar")
        assert like
        assert {h.doc_id for h in fts} == {h.doc_id for h in like}

    @pytest.mark.asyncio
    async def test_unindexable_query_falls_back_to_like(self, corpus):
        """Pure punctuation has no FTS5 tokens; the LIKE path answers instead."""
        self._build(corpus)
        with patch.object(corpus, "_connect", wraps=corpus._connect) as like_conn:
            await corpus.search("&")
        like_conn.assert_called()

    @pytest.mark.asyncio
    async def test_update_reindexes_only_new_file_in_place(self, corpus):
        """A synced file is indexed in place; a held reader sees it."""
        self._build(corpus)
        assert await corpus.search("Zebra") == []  # opens the cached reader
        inode = corpus._fts_path().stat().st_ino
        zebra = dict(SC_ROWS[0], title="ZEBRA CROSSING versus STATE", path="z_1")
        _write_parquet(
            [zebra], corpus.sc_metadata_dir / "year=2025" / "metadata.parquet"
        )
        assert corpus._fts_available() is False

        result = corpus.build_fts_index()

        assert result["rebuilt"] is False
        assert result["files_reindexed"] == 1
        assert result["rows_added"] == 1
        assert result["rows"] == 4
        assert corpus._fts_path().stat().st_ino == inode  # no side-file swap
        assert corpus._fts_available() is True
        with patch.object(corpus, "_connect", side_effect=AssertionError("LIKE")):
            hits = await corpus.search("Zebra")
        assert [h.doc_id for h in hits] == ["sc:2025:z_1"]

    @pytest.mark.asyncio
    async def test_update_replaces_changed_and_drops_removed_files(self, corpus):
        """A rewritten file swaps its rows; a deleted file's rows disappear."""
        self._build(corpus)
        sc_file = corpus.sc_metadata_dir / "year=2024" / "metadata.parquet"
        _write_parquet([dict(SC_ROWS[0], title="QUOKKA versus STATE")], sc_file)
        hc_file = next(corpus.hc_metadata_dir.rglob("metadata.parquet"))
        hc_file.unlink()

        result = corpus.build_fts_index()

        assert result["files_reindexed"] == 2
        assert result["rows_removed"] == 3  # 2 SC + 1 HC
        assert result["rows"] == 1
        with patch.object(corpus, "_connect", side_effect=AssertionError("LIKE")):
            assert [h.title for h in await corpus.search("Quokka")] == [
                "QUOKKA versus STATE"
            ]
            assert await corpus.search("Vijay") == []
            assert await corpus.search("Pereira") == []

    def test_index_without_file_tracking_gets_full_build(self, corpus):
        """An index from before per-file tracking cannot be patched."""
        import sqlite3

        self._build(corpus)
        con = sqlite3.connect(corpus._fts_path())
        con.execute("DROP TABLE fts_sources")
        con.commit()
        con.close()

        result = corpus.build_fts_index()

        assert result["rebuilt"] is True
        assert result["rows"] == 3

    def test_corpus_version_tracks_index_and_metadata(self, corpus):
        """The search-cache token moves on a sync and on an index update."""
        before = corpus.corpus_version()
        self._build(corpus)
        built = corpus.corpus_version()
        _write_parquet(
            SC_ROWS, corpus.sc_metadata_dir / "year=2025" / "metadata.parquet"
        )
        synced = corpus.corpus_version()
        corpus.build_fts_index()
        updated = corpus.corpus_version()
        assert len({before, built, synced, updated}) == 4

    def test_rowids_follow_decision_date_and_sources_are_ids(self, corpus):
        """Rowid order is date order, which broad queries walk newest first."""
        import sqlite3

        self._build(corpus)
        con = sqlite3.connect(corpus._fts_path())
        dates = [
            d for (d,) in con.execute("SELECT decision_date FROM corpus ORDER BY id")
        ]
        sources = {type(s) for (s,) in con.execute("SELECT _source FROM corpus")}
        con.close()
        assert dates == sorted(dates)
        assert sources == {int}

    def test_build_orders_rows_across_years(self, corpus):
        """Years are loaded oldest first, each sorted, so rowids stay in order."""
        import sqlite3

        older = dict(SC_ROWS[0], decision_date="01-02-2019", path="old_1")
        _write_parquet(
            [older], corpus.sc_metadata_dir / "year=2019" / "metadata.parquet"
        )
        year_sql, _ = corpus._search_sql("all", "2019")
        assert "year=2019" in year_sql and "year=*" not in year_sql

        self._build(corpus)
        con = sqlite3.connect(corpus._fts_path())
        dates = [
            d for (d,) in con.execute("SELECT decision_date FROM corpus ORDER BY id")
        ]
        con.close()
        assert dates[0] == "2019-02-01"
        assert dates == sorted(dates)

    @pytest.mark.asyncio
    async def test_broad_query_lists_newest_first(self, corpus):
        """Past the rank limit, matches come back by date and are flagged."""
        self._build(corpus)
        with (
            patch.object(open_judgments, "FTS_RANK_LIMIT", 1),
            patch.object(corpus, "_connect", side_effect=AssertionError("LIKE")),
        ):
            hits = await corpus.search("Bihar")
            page2 = await corpus.search("Bihar", limit=1, page=1)
        assert hits.broad is True
        assert [h.date for h in hits] == ["2024-09-25", "2024-05-12"]
        assert [h.date for h in page2] == ["2024-05-12"]

    @pytest.mark.asyncio
    async def test_broad_query_date_filters_become_rowid_bounds(self, corpus):
        """from/to dates bound the newest-first walk, including later appends."""
        self._build(corpus)
        appended = dict(SC_ROWS[1], decision_date="01-01-2020", path="tail_1")
        _write_parquet(
            [appended], corpus.sc_metadata_dir / "year=2020" / "metadata.parquet"
        )
        corpus.build_fts_index()  # incremental: lands above the dated span

        with patch.object(open_judgments, "FTS_RANK_LIMIT", 1):
            after = await corpus.search("Bihar", from_date="2024-06-01")
            before = await corpus.search("Bihar", to_date="2024-06-01")
            window = await corpus.search(
                "Bihar", from_date="2024-01-01", to_date="2024-06-30"
            )
        assert after.broad and before.broad and window.broad
        assert [h.date for h in after] == ["2024-09-25"]
        assert [h.date for h in before] == ["2024-05-12", "2020-01-01"]
        assert [h.date for h in window] == ["2024-05-12"]

    @pytest.mark.asyncio
    async def test_index_without_date_order_record_stays_ranked(self, corpus):
        """An index built before fts_meta existed cannot bound by rowid."""
        import sqlite3

        self._build(corpus)
        con = sqlite3.connect(corpus._fts_path())
        con.execute("DROP TABLE fts_meta")
        con.commit()
        con.close()
        corpus._close_duckdb_handles()
        with patch.object(open_judgments, "FTS_RANK_LIMIT", 1):
            hits = await corpus.search("Bihar")
        assert hits.broad is False
        assert len(hits) == 2

    @pytest.mark.asyncio
    async def test_judge_filter_narrows_inside_fts(self, corpus):
        """Judge names match in FTS5; prefixes work; the LIKE check still applies."""
        self._build(corpus)
        with patch.object(corpus, "_connect", side_effect=AssertionError("LIKE")):
            full = await corpus.search("Bihar", judge="Trivedi")
            prefix = await corpus.search("Bihar", judge="Triv")
            initials = await corpus.search("Bihar", judge="Bela M. Trivedi")
            other = await corpus.search("Bihar", judge="Chandrachud")
        assert [h.judge for h in full] == ["BELA M. TRIVEDI"]
        assert [h.judge for h in prefix] == ["BELA M. TRIVEDI"]
        assert [h.judge for h in initials] == ["BELA M. TRIVEDI"]
        assert other == []

    @pytest.mark.asyncio
    async def test_judge_filtered_broad_query_walks_newest_first(self, corpus):
        """A judge filter no longer forces the slow ranked path."""
        self._build(corpus)
        with patch.object(open_judgments, "FTS_RANK_LIMIT", 0):
            hits = await corpus.search("Bihar", judge="Dhulia")
        assert hits.broad is True
        assert [h.judge for h in hits] == ["SUDHANSHU DHULIA"]

    def test_index_without_judge_column_gets_full_build(self, corpus):
        """An index from before the judge column cannot be patched in place."""
        import sqlite3

        self._build(corpus)
        con = sqlite3.connect(corpus._fts_path())
        con.execute("DROP TABLE corpus_fts")
        con.execute(
            "CREATE VIRTUAL TABLE corpus_fts USING fts5(title, description, "
            "court_code, content='corpus', content_rowid='id')"
        )
        con.commit()
        con.close()

        result = corpus.build_fts_index()

        assert result["rebuilt"] is True

    @pytest.mark.asyncio
    async def test_common_word_only_query_uses_fts(self, corpus):
        """ "state" alone used to fall through to the full LIKE scan."""
        like = await corpus.search("state")
        self._build(corpus)
        with patch.object(corpus, "_connect", side_effect=AssertionError("LIKE")):
            fts = await corpus.search("state")
        assert like
        assert {h.doc_id for h in fts} == {h.doc_id for h in like}

    @pytest.mark.asyncio
    async def test_search_tool_reports_newest_first_ordering(self, corpus, tmp_path):
        """The tool tells the caller results are not ranked, and how to narrow."""
        from legal_mcp_server.src import cache as cache_mod

        self._build(corpus)
        with (
            patch.object(
                open_judgments.settings, "LEGAL_DATA_PATH", str(tmp_path / "cache")
            ),
            patch.object(open_judgments, "FTS_RANK_LIMIT", 1),
        ):
            cache_mod._get_cache.cache_clear()
            try:
                broad = await research_tools.search_case_law("Bihar")
                narrow = await research_tools.search_case_law("Vijay")
            finally:
                cache_mod._get_cache.cache_clear()
        assert broad["ordering"] == "newest_first"
        assert "newest matches" in broad["message"]
        assert narrow["ordering"] == "relevance"
        assert "notice" not in narrow

    def test_stale_after_newer_metadata(self, corpus):
        self._build(corpus)
        assert corpus._fts_available() is True
        fresh = corpus.sc_metadata_dir / "year=2025" / "metadata.parquet"
        _write_parquet(SC_ROWS, fresh)
        assert corpus._fts_available() is False

    @pytest.mark.asyncio
    async def test_fts_search_matches_like_search(self, corpus):
        self._build(corpus)
        fts_hits = await corpus.search("State Bihar", court="Supreme Court")
        assert len(fts_hits) == 2
        assert {h.doc_id for h in fts_hits} == {
            "sc:2024:2024_10_108_125",
            "sc:2024:2024_5_629_729",
        }

    @pytest.mark.asyncio
    async def test_fts_search_honours_and_semantics(self, corpus):
        self._build(corpus)
        # Both terms must appear; only VIJAY SINGH carries "Appeal".
        hits = await corpus.search("Appeal Bihar", court="Supreme Court")
        assert [h.doc_id for h in hits] == ["sc:2024:2024_10_108_125"]


def _pagination_rows(count: int) -> List[Dict[str, Any]]:
    """Build SC-shaped rows whose dates sort in a known order."""
    rows: List[Dict[str, Any]] = []
    for i in range(1, count + 1):
        rows.append(
            {
                "title": f"PAGINATION MATTER {i} versus THE STATE",
                "petitioner": f"PAGINATION MATTER {i}",
                "respondent": "THE STATE",
                "description": f"Pagination fixture judgment number {i}.",
                "judge": "TEST JUDGE",
                "citation": f"[2024] 1 S.C.R. {i}",
                "cnr": f"SCIN010000{i:02d}2024",
                "decision_date": f"{i:02d}-01-2024",
                "disposal_nature": "Allowed",
                "court": "Supreme Court of India",
                "nc_display": f"2024INSC10{i:02d}",
                "path": f"2024_1_{i}_{i}",
                "year": "2024",
            }
        )
    return rows


@pytest.fixture
def paged_corpus(tmp_path: Path):
    """A synced-looking SC-only corpus with five matching judgments."""
    _write_parquet(
        _pagination_rows(5),
        tmp_path / "sc" / "metadata" / "year=2024" / "metadata.parquet",
    )
    client = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
    with patch.object(open_judgments, "get_client", return_value=client):
        yield client


class TestPagination:
    """Deep result sets are reachable page by page on the free backend."""

    @pytest.mark.asyncio
    async def test_like_pages_are_disjoint_windows(self, paged_corpus):
        """Pages tile the ranked results without overlap or gaps."""
        pages = [
            await paged_corpus.search("pagination matter", limit=2, page=p)
            for p in range(3)
        ]
        after_last = await paged_corpus.search("pagination matter", limit=2, page=3)

        assert [r.doc_id for r in pages[0]] == [
            "sc:2024:2024_1_5_5",
            "sc:2024:2024_1_4_4",
        ]
        ids = [r.doc_id for page in pages for r in page]
        assert len(ids) == 5
        assert len(set(ids)) == 5
        assert after_last == []

    @pytest.mark.asyncio
    async def test_fts_pages_are_disjoint_windows(self, paged_corpus):
        """The BM25 path paginates identically to the LIKE fallback."""
        try:
            build = paged_corpus.build_fts_index(force=True)
        except Exception as exc:  # noqa: BLE001 - extension may be unavailable
            pytest.skip(f"SQLite FTS5 not usable here: {exc}")
        assert build["status"] == "success"

        pages = [
            await paged_corpus.search("pagination matter", limit=2, page=p)
            for p in range(3)
        ]
        ids = [r.doc_id for page in pages for r in page]
        assert len(ids) == 5
        assert len(set(ids)) == 5

    @pytest.mark.asyncio
    async def test_negative_page_clamps_to_first(self, paged_corpus):
        """A negative page is treated as the first page, not an error."""
        negative = await paged_corpus.search("pagination matter", limit=2, page=-3)
        first = await paged_corpus.search("pagination matter", limit=2, page=0)
        assert [r.doc_id for r in negative] == [r.doc_id for r in first]

    @pytest.mark.asyncio
    async def test_facade_passes_page_through(self, paged_corpus):
        """The backend-agnostic layer reports and honours the requested page."""
        payload = await case_law.search("pagination matter", limit=2, page=1)

        assert payload["page"] == 1
        direct = await paged_corpus.search("pagination matter", limit=2, page=1)
        assert [r["doc_id"] for r in payload["results"]] == [r.doc_id for r in direct]


class TestShutdown:
    """Resource release must be total and repeatable."""

    @staticmethod
    def _client_with_fakes():
        """A client holding one fake DuckDB conn and one fake HTTP client."""
        from unittest.mock import MagicMock

        client = open_judgments.OpenJudgmentsClient(data_path="/tmp/never-used")
        fake_conn = MagicMock()
        client._conns.add(fake_conn)
        fake_http = MagicMock()
        fake_http.aclose = AsyncMock(return_value=None)
        client._http = fake_http
        return client, fake_conn, fake_http

    @pytest.mark.asyncio
    async def test_aclose_closes_conns_and_http(self):
        """aclose() drops every DuckDB conn and awaits the HTTP client close."""
        client, fake_conn, fake_http = self._client_with_fakes()

        await client.aclose()

        fake_conn.close.assert_called_once()
        fake_http.aclose.assert_awaited_once()
        assert len(client._conns) == 0
        assert client._http is None

    @pytest.mark.asyncio
    async def test_aclose_is_repeatable_and_tolerant(self):
        """Closing twice, or with a broken connection, never raises."""
        client, fake_conn, _http = self._client_with_fakes()
        fake_conn.close.side_effect = RuntimeError("already closed")

        await client.aclose()
        await client.aclose()

        assert len(client._conns) == 0

    @pytest.mark.asyncio
    async def test_module_aclose_client_noop_when_never_created(self):
        """The shutdown helper is a no-op when no singleton exists."""
        with patch.object(open_judgments, "_client", None):
            await open_judgments.aclose_client()
            assert open_judgments._client is None

    @pytest.mark.asyncio
    async def test_module_aclose_client_closes_singleton(self):
        """The shutdown helper closes and clears the shared client."""
        client, fake_conn, fake_http = self._client_with_fakes()
        with patch.object(open_judgments, "_client", client):
            await open_judgments.aclose_client()
            fake_conn.close.assert_called_once()
            fake_http.aclose.assert_awaited_once()
            assert open_judgments._client is None
