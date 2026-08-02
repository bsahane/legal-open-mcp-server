"""Tests for the Indian Kanoon client and the research tools built on it.

Every call to this API is billed, so the spend ledger, the cache and the
failure modes are as important as the parsing. The HTTP layer is stubbed at
``_post`` so no request is ever made.
"""

from datetime import date, timedelta
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from legal_mcp_server.src.sources import indian_kanoon as ik
from legal_mcp_server.src.tools import research_tools

SEARCH_PAYLOAD: Dict[str, Any] = {
    "found": "42",
    "docs": [
        {
            "tid": 1766147,
            "title": "Dashrath Rupsingh Rathod vs <b>State</b> Of Maharashtra",
            "docsource": "Supreme Court of India",
            "publishdate": "2014-08-01",
            "headline": "cheque <b>dishonour</b> ... territorial jurisdiction<br>more",
        },
        {
            "tid": 59736,
            "title": "K. Bhaskaran vs Sankaran Vaidhyan Balan",
            "docsource": "Supreme Court of India",
            "publishdate": "1999-09-29",
            "headline": "section <b>138</b> five components",
        },
    ],
}

DOC_PAYLOAD: Dict[str, Any] = {
    "title": "Dashrath Rupsingh Rathod vs State Of Maharashtra",
    "docsource": "Supreme Court of India",
    "publishdate": "2014-08-01",
    "author": "T.S. Thakur",
    "doc": "<p>The <b>appeal</b> is allowed.</p>",
    "citeList": [{"tid": 59736, "title": "K. Bhaskaran"}],
    "citedbyList": [{"tid": 111, "title": "Later Case"}],
}


class StubClient(ik.IndianKanoonClient):
    """Client with the HTTP layer replaced by canned payloads."""

    def __init__(self, payload: Dict[str, Any]):
        super().__init__(api_key="test-token")
        self.payload = payload
        self.calls: List[str] = []

    async def _post(self, path: str, cost_inr: float) -> Dict[str, Any]:
        self.calls.append(path)
        self.ledger.check(cost_inr, 100.0)
        self.ledger.record(cost_inr)
        return self.payload


class TestStripHtml:
    """Indian Kanoon returns markup that must not reach the model."""

    def test_removes_tags_and_breaks(self):
        """Bold tags and line breaks are stripped, whitespace collapsed."""
        assert ik._strip_html("a <b>bold</b><br>word") == "a bold word"

    def test_handles_none(self):
        """A missing field becomes an empty string."""
        assert ik._strip_html(None) == ""


class TestSpendLedger:
    """The daily budget cap."""

    def test_records_spend(self):
        """Recorded calls accumulate."""
        ledger = ik.SpendLedger()
        ledger.record(0.5)
        ledger.record(0.2)
        assert ledger.spent_inr == pytest.approx(0.7)
        assert ledger.calls == 2

    def test_check_raises_over_budget(self):
        """A call that would breach the cap is refused before it is made."""
        ledger = ik.SpendLedger()
        ledger.record(99.8)
        with pytest.raises(ik.BudgetExceeded):
            ledger.check(0.5, 100.0)

    def test_check_allows_within_budget(self):
        """A call inside the cap is permitted."""
        ledger = ik.SpendLedger()
        ledger.check(0.5, 100.0)

    def test_rolls_over_at_midnight(self):
        """Yesterday's spend does not count against today's budget."""
        ledger = ik.SpendLedger()
        ledger.day = date.today() - timedelta(days=1)
        ledger.spent_inr = 999.0
        ledger.check(0.5, 100.0)
        assert ledger.spent_inr == 0.0

    def test_snapshot_reports_remaining(self):
        """The snapshot exposes remaining budget for tool output."""
        ledger = ik.SpendLedger()
        ledger.record(1.0)
        snapshot = ledger.snapshot()
        assert snapshot["spent_inr"] == 1.0
        assert snapshot["calls"] == 1


class TestClientAvailability:
    """Refusing to pretend when the source cannot be consulted."""

    @pytest.mark.asyncio
    async def test_missing_key_raises_source_unavailable(self):
        """No API key produces SourceUnavailable, not an empty result."""
        client = ik.IndianKanoonClient(api_key=None)
        assert client.available is False
        with pytest.raises(ik.SourceUnavailable) as excinfo:
            await client.search("anything")
        assert "INDIAN_KANOON_API_KEY" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_zero_budget_disables_calls(self):
        """A zero budget blocks paid calls explicitly."""
        client = ik.IndianKanoonClient(api_key="k")
        with patch.object(ik.settings, "INDIAN_KANOON_DAILY_BUDGET_INR", 0.0):
            assert client.available is False
            with pytest.raises(ik.BudgetExceeded):
                await client.search("anything")


class TestSearchParsing:
    """Search results are normalised into clean records."""

    @pytest.mark.asyncio
    async def test_parses_results(self):
        """Titles and snippets are stripped and ids carried through."""
        client = StubClient(SEARCH_PAYLOAD)
        result = await client.search("cheque dishonour")
        assert result["found"] == "42"
        first = result["results"][0]
        assert first["doc_id"] == 1766147
        assert "<b>" not in first["title"]
        assert first["url"] == "https://indiankanoon.org/doc/1766147/"

    @pytest.mark.asyncio
    async def test_filters_are_encoded_into_the_query(self):
        """Court and date filters become Indian Kanoon query operators."""
        client = StubClient(SEARCH_PAYLOAD)
        result = await client.search(
            "cheque", court="bombay", from_date="01-01-2020", to_date="31-12-2024"
        )
        assert "doctypes:bombay" in result["query"]
        assert "fromdate:01-01-2020" in result["query"]

    @pytest.mark.asyncio
    async def test_skips_records_without_an_id(self):
        """A malformed record is dropped rather than crashing the search."""
        client = StubClient({"docs": [{"title": "no id here"}], "found": "1"})
        result = await client.search("x")
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_search_is_billed(self):
        """A search costs the published search price."""
        client = StubClient(SEARCH_PAYLOAD)
        await client.search("x")
        assert client.ledger.spent_inr == pytest.approx(ik.COST_SEARCH_INR)


class TestDocumentParsing:
    """Judgment retrieval."""

    @pytest.mark.asyncio
    async def test_parses_judgment(self):
        """Text is stripped of markup and the citation graph is carried through."""
        client = StubClient(DOC_PAYLOAD)
        judgment = await client.get_document(1766147)
        assert judgment.doc_id == 1766147
        assert "<b>" not in judgment.text
        assert judgment.cited_by == [{"tid": 111, "title": "Later Case"}]

    @pytest.mark.asyncio
    async def test_metadata_is_cheaper_than_full_document(self):
        """Metadata uses the cheaper endpoint price."""
        client = StubClient(DOC_PAYLOAD)
        await client.get_metadata(1766147)
        assert client.ledger.spent_inr == pytest.approx(ik.COST_METADATA_INR)

    @pytest.mark.asyncio
    async def test_fragments_normalise_a_string_headline(self):
        """A single headline string is treated as a one-element list."""
        client = StubClient({"title": "X", "headline": "one <b>match</b>"})
        result = await client.get_fragments(1, "match")
        assert result["fragments"] == ["one match"]


class TestResearchToolsWithStub:
    """The tool layer over a working client."""

    @pytest.mark.asyncio
    async def test_search_tool_returns_results(self):
        """search_case_law surfaces results and the running spend."""
        client = StubClient(SEARCH_PAYLOAD)
        with patch(
            "legal_mcp_server.src.tools.research_tools.get_client", lambda: client
        ):
            result = await research_tools.search_case_law("cheque dishonour")
        assert result["status"] == "success"
        assert result["result_count"] == 2
        assert "spend" in result

    @pytest.mark.asyncio
    async def test_search_tool_rejects_empty_query(self):
        """An empty query never reaches the paid API."""
        client = StubClient(SEARCH_PAYLOAD)
        with patch(
            "legal_mcp_server.src.tools.research_tools.get_client", lambda: client
        ):
            result = await research_tools.search_case_law("   ")
        assert result["status"] == "error"
        assert client.calls == []

    @pytest.mark.asyncio
    async def test_get_judgment_truncates_on_request(self):
        """Truncation is applied and disclosed."""
        client = StubClient(DOC_PAYLOAD)
        with patch(
            "legal_mcp_server.src.tools.research_tools.get_client", lambda: client
        ):
            result = await research_tools.get_judgment(1766147, max_chars=5)
        assert result["truncated"] is True
        assert len(result["text"]) == 5

    @pytest.mark.asyncio
    async def test_get_judgment_rejects_bad_id(self):
        """A non-positive document id is rejected."""
        result = await research_tools.get_judgment(0)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_search_within_judgment(self):
        """Passage search returns the fragments and their count."""
        client = StubClient({"title": "X", "headline": ["frag one", "frag two"]})
        with patch(
            "legal_mcp_server.src.tools.research_tools.get_client", lambda: client
        ):
            result = await research_tools.search_within_judgment(1, "jurisdiction")
        assert result["fragment_count"] == 2

    @pytest.mark.asyncio
    async def test_empty_fragments_explain_themselves(self):
        """No match prompts a synonym retry rather than implying silence."""
        client = StubClient({"title": "X", "headline": []})
        with patch(
            "legal_mcp_server.src.tools.research_tools.get_client", lambda: client
        ):
            result = await research_tools.search_within_judgment(1, "nothing")
        assert "synonym" in result["message"]

    @pytest.mark.asyncio
    async def test_find_citing_cases_warns_about_interpretation(self):
        """A citing list is not the same as still-good-law, and says so."""
        client = StubClient(DOC_PAYLOAD)
        with patch(
            "legal_mcp_server.src.tools.research_tools.get_client", lambda: client
        ):
            result = await research_tools.find_citing_cases(1766147)
        assert result["cited_by_count"] == 1
        assert "overrule" in result["message"]

    @pytest.mark.asyncio
    async def test_case_citation_not_found(self):
        """A citation with no matching judgment is NOT_FOUND."""
        client = StubClient({"docs": [], "found": "0"})
        with patch(
            "legal_mcp_server.src.tools.research_tools.get_client", lambda: client
        ):
            result = await research_tools.verify_citation("(2099) 12 SCC 555")
        assert result["verdict"] == research_tools.VERDICT_NOT_FOUND

    @pytest.mark.asyncio
    async def test_case_citation_verified_on_exact_match(self):
        """A single result containing the citation verifies."""
        payload = {
            "found": "1",
            "docs": [
                {
                    "tid": 1,
                    "title": "Some Case, (2014) 9 SCC 129",
                    "docsource": "Supreme Court of India",
                    "publishdate": "2014-08-01",
                    "headline": "text",
                }
            ],
        }
        client = StubClient(payload)
        with patch(
            "legal_mcp_server.src.tools.research_tools.get_client", lambda: client
        ):
            result = await research_tools.verify_citation("(2014) 9 SCC 129")
        assert result["verdict"] == research_tools.VERDICT_VERIFIED

    @pytest.mark.asyncio
    async def test_case_citation_ambiguous_on_name_only_match(self):
        """Results that do not contain the citation are only an approximate match."""
        client = StubClient(SEARCH_PAYLOAD)
        with patch(
            "legal_mcp_server.src.tools.research_tools.get_client", lambda: client
        ):
            result = await research_tools.verify_citation("(2014) 9 SCC 129")
        assert result["verdict"] == research_tools.VERDICT_AMBIGUOUS
        assert "confirm" in result["note"].lower()

    @pytest.mark.asyncio
    async def test_verification_disabled_says_so(self):
        """With verification off, the tool does not imply a citation checks out."""
        with patch.object(
            research_tools.settings, "ENABLE_CITATION_VERIFICATION", False
        ):
            result = await research_tools.verify_citation("(2014) 9 SCC 129")
        assert result["verdict"] == research_tools.VERDICT_UNCHECKED
        assert "no lookup was" in result["note"]

    @pytest.mark.asyncio
    async def test_sweep_respects_max_citations(self):
        """Citations beyond the cap are reported as unchecked, not silently dropped."""
        client = StubClient({"docs": [], "found": "0"})
        text = "(2014) 9 SCC 129 and (2013) 9 SCC 32 and (2019) 5 SCC 266"
        with patch(
            "legal_mcp_server.src.tools.research_tools.get_client", lambda: client
        ):
            result = await research_tools.verify_all_citations(text, max_citations=1)
        assert result["skipped_for_budget"] == 2
        assert result["citation_count"] == 3

    @pytest.mark.asyncio
    async def test_build_research_memo_gathers_and_instructs(self):
        """The memo builder returns an evidence base plus drafting instructions."""
        client = StubClient(SEARCH_PAYLOAD)
        with patch(
            "legal_mcp_server.src.tools.research_tools.get_client", lambda: client
        ):
            result = await research_tools.build_research_memo(
                "Is a post-termination non-compete enforceable?",
                queries=["section 27 restraint of trade"],
            )
        assert result["status"] == "success"
        assert result["authority_count"] == 2
        assert "not a memo" in result["message"]
        assert "verify_all_citations" in result["drafting_instructions"]

    @pytest.mark.asyncio
    async def test_build_research_memo_rejects_empty_issue(self):
        """An empty issue is rejected."""
        result = await research_tools.build_research_memo("")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_budget_status_with_key(self):
        """With a key configured, case law reports as available."""
        client = StubClient(SEARCH_PAYLOAD)
        with patch(
            "legal_mcp_server.src.tools.research_tools.get_client", lambda: client
        ):
            result = research_tools.get_research_budget_status()
        assert result["case_law_available"] is True


class TestClientSingleton:
    """The shared client keeps the cache and ledger effective."""

    def test_get_client_is_stable(self):
        """Repeated calls return the same instance."""
        ik.reset_client()
        assert ik.get_client() is ik.get_client()

    def test_reset_client_clears_it(self):
        """Reset produces a fresh instance."""
        first = ik.get_client()
        ik.reset_client()
        assert ik.get_client() is not first


class TestCourtResolution:
    """Friendly court names map to Indian Kanoon filter tokens."""

    def test_known_alias(self):
        """'supreme court' maps to the API's token."""
        assert research_tools._resolve_court("Supreme Court") == "supremecourt"

    def test_unknown_court_passed_through_lowercased(self):
        """An unrecognised name is passed through rather than dropped."""
        assert research_tools._resolve_court("Sikkim") == "sikkim"

    def test_none_stays_none(self):
        """No filter means no filter."""
        assert research_tools._resolve_court(None) is None
