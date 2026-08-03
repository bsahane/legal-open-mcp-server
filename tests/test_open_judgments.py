"""Tests for the free open-data case-law backend and the research tools.

No network access and no API key. A small Parquet fixture is written to a temp
directory and queried through DuckDB exactly as the real corpus is, so the SQL,
the citation matching and the doc-id round trip are all genuinely exercised.
"""

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

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
            selects.append("SELECT " + ", ".join(
                f"{lit} AS {col}" for lit, col in zip(literals, columns)
            ))
        con.execute(
            f"COPY ({' UNION ALL '.join(selects)}) TO '{target}' (FORMAT PARQUET)"
        )
    finally:
        con.close()


@pytest.fixture
def corpus(tmp_path: Path):
    """A synced-looking local corpus with one SC year and one HC bench."""
    _write_parquet(SC_ROWS, tmp_path / "sc" / "metadata" / "year=2024" / "metadata.parquet")
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
            result = await research_tools.search_within_judgment("sc:2024:x", "arbitration")

        assert result["match_count"] == 0
        assert "try a synonym" in result["message"]

    @pytest.mark.asyncio
    async def test_search_within_judgment_validates_inputs(self, corpus):
        assert (await research_tools.search_within_judgment("", "x"))["status"] == "error"
        assert (
            await research_tools.search_within_judgment("sc:2024:x", "  ")
        )["status"] == "error"

    @pytest.mark.asyncio
    async def test_sync_tool_defaults_to_sc_plus_default_high_court(self, corpus):
        captured = {}

        async def fake_sync(courts, from_year, to_year, force):
            captured["courts"] = courts
            return {"courts": {}, "files": 0, "bytes": 0, "skipped": 0, "megabytes": 0.0}

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
            return {"courts": {}, "files": 2, "bytes": 10, "skipped": 0, "megabytes": 0.1}

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
