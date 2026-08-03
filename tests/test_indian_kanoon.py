"""Tests for the optional, paid Indian Kanoon client.

This backend is opt-in only (``CASE_LAW_SOURCE=indian_kanoon``); the default is
the free open-data corpus covered by ``test_open_judgments.py``. Every call here
is billed, so the spend ledger, the cache and the failure modes matter as much
as the parsing. The HTTP layer is stubbed at ``_post`` so no request is made.
"""

from datetime import date, timedelta
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from legal_mcp_server.src.sources import indian_kanoon as ik

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
