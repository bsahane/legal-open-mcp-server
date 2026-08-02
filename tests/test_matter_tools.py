"""Tests for the matter, hearing and document tools against a fake store.

These tools are thin wrappers over SQL. A real PostgreSQL instance is not
needed to verify what matters here: that the right statement is issued, that
rows are shaped correctly on the way out, that validation rejects bad input
before it reaches the database, and that an unreachable database produces an
honest "nothing was written" response rather than a silent success.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from legal_mcp_server.src.tools import document_tools, matter_tools

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


class FakeRecord(dict):
    """Stands in for an asyncpg Record, which behaves like a mapping."""


class FakeStore:
    """Records the SQL it is asked to run and replays canned results."""

    def __init__(
        self,
        row: Optional[Dict[str, Any]] = None,
        rows: Optional[List[Dict[str, Any]]] = None,
        value: Any = 1,
    ):
        self.row = FakeRecord(row) if row is not None else None
        self.rows = [FakeRecord(r) for r in (rows or [])]
        self.value = value
        self.queries: List[str] = []
        self.args: List[tuple] = []
        self.vector_enabled = True

    async def fetchrow(self, query: str, *args: Any):
        self.queries.append(query)
        self.args.append(args)
        return self.row

    async def fetch(self, query: str, *args: Any):
        self.queries.append(query)
        self.args.append(args)
        return self.rows

    async def fetchval(self, query: str, *args: Any):
        self.queries.append(query)
        self.args.append(args)
        return self.value

    async def execute(self, query: str, *args: Any):
        self.queries.append(query)
        self.args.append(args)
        return "OK"


class DeadStore(FakeStore):
    """A store that cannot reach PostgreSQL."""

    async def fetchrow(self, query: str, *args: Any):
        raise ConnectionError("PostgreSQL connection failed")

    async def fetch(self, query: str, *args: Any):
        raise ConnectionError("PostgreSQL connection failed")

    async def fetchval(self, query: str, *args: Any):
        raise ConnectionError("PostgreSQL connection failed")

    async def execute(self, query: str, *args: Any):
        raise ConnectionError("PostgreSQL connection failed")


MATTER_ROW = {
    "id": 3,
    "reference": "RD/2026/41",
    "title": "Cheque dishonour - Sharma Traders",
    "matter_type": "cheque_bounce",
    "status": "open",
    "court": None,
    "case_number": None,
    "cnr": None,
    "parties": '[{"name": "Sharma Traders", "role": "accused"}]',
    "cause_of_action_date": date(2026, 7, 15),
    "filing_date": None,
    "limitation_expiry": date(2026, 9, 8),
    "claim_value": Decimal("200000"),
    "opposing_counsel": None,
    "notes": None,
    "created_at": NOW,
    "updated_at": NOW,
}


def use_store(store: FakeStore):
    """Patch both tool modules to use the given fake store."""
    return patch.multiple(
        "legal_mcp_server.src.tools.matter_tools",
        get_store=lambda: store,
    )


class TestCreateMatter:
    """Matter creation and its validation."""

    @pytest.mark.asyncio
    async def test_creates_and_serialises_row(self):
        """A created matter comes back with dates and JSON decoded."""
        store = FakeStore(row=MATTER_ROW)
        with use_store(store):
            result = await matter_tools.create_matter(
                "Cheque dishonour - Sharma Traders", "cheque_bounce"
            )
        assert result["status"] == "success"
        matter = result["matter"]
        assert matter["id"] == 3
        assert matter["cause_of_action_date"] == "2026-07-15"
        assert matter["parties"] == [{"name": "Sharma Traders", "role": "accused"}]
        assert matter["claim_value"] == 200000.0
        assert "INSERT INTO matters" in store.queries[0]

    @pytest.mark.asyncio
    async def test_rejects_unknown_matter_type(self):
        """An unsupported matter type is rejected before touching the database."""
        store = FakeStore(row=MATTER_ROW)
        with use_store(store):
            result = await matter_tools.create_matter("X", "not_a_type")
        assert result["status"] == "error"
        assert store.queries == []

    @pytest.mark.asyncio
    async def test_rejects_empty_title(self):
        """An empty title is rejected."""
        store = FakeStore(row=MATTER_ROW)
        with use_store(store):
            result = await matter_tools.create_matter("   ", "civil_suit")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_rejects_bad_date(self):
        """A malformed date is rejected with a clear message."""
        store = FakeStore(row=MATTER_ROW)
        with use_store(store):
            result = await matter_tools.create_matter(
                "X", "civil_suit", cause_of_action_date="15/07/2026"
            )
        assert result["status"] == "error"
        assert "YYYY-MM-DD" in result["error"]

    @pytest.mark.asyncio
    async def test_prompts_for_limitation_when_absent(self):
        """Creating without a limitation date produces an explicit next step."""
        store = FakeStore(row=MATTER_ROW)
        with use_store(store):
            result = await matter_tools.create_matter("X", "civil_suit")
        assert result["next_step"] and "compute_limitation" in result["next_step"]

    @pytest.mark.asyncio
    async def test_database_down_reports_nothing_written(self):
        """An unreachable database must not look like a successful save."""
        with use_store(DeadStore()):
            result = await matter_tools.create_matter("X", "civil_suit")
        assert result["status"] == "unavailable"
        assert "nothing was read or written" in result["message"]


class TestUpdateMatter:
    """Partial updates only write the fields supplied."""

    @pytest.mark.asyncio
    async def test_only_supplied_fields_are_written(self):
        """Omitted fields are left alone rather than nulled."""
        store = FakeStore(row=MATTER_ROW)
        with use_store(store):
            result = await matter_tools.update_matter(
                3, status="in_court", case_number="CC/1234/2026"
            )
        assert result["status"] == "success"
        assert result["fields_changed"] == ["case_number", "status"]
        assert "title" not in store.queries[0]

    @pytest.mark.asyncio
    async def test_no_fields_is_an_error(self):
        """An update with nothing to change is rejected."""
        store = FakeStore(row=MATTER_ROW)
        with use_store(store):
            result = await matter_tools.update_matter(3)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_invalid_status_rejected(self):
        """An unsupported status value is rejected."""
        store = FakeStore(row=MATTER_ROW)
        with use_store(store):
            result = await matter_tools.update_matter(3, status="vibing")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_missing_matter_reported(self):
        """Updating a matter that does not exist is reported, not faked."""
        store = FakeStore(row=None)
        with use_store(store):
            result = await matter_tools.update_matter(999, status="closed")
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_negative_id_rejected(self):
        """A non-positive id is rejected."""
        store = FakeStore(row=MATTER_ROW)
        with use_store(store):
            result = await matter_tools.update_matter(-1, status="closed")
        assert result["status"] == "error"


class TestListMatters:
    """Listing and the limitation alert."""

    @pytest.mark.asyncio
    async def test_limitation_alert_for_imminent_expiry(self):
        """A matter expiring soon is surfaced in limitation_alerts."""
        soon = date.today().replace()
        row = {**MATTER_ROW, "limitation_expiry": soon}
        store = FakeStore(rows=[row])
        with use_store(store):
            result = await matter_tools.list_matters()
        assert result["status"] == "success"
        assert result["limitation_alerts"]
        assert "limitation date within 60 days" in result["message"]

    @pytest.mark.asyncio
    async def test_closed_matters_do_not_raise_alerts(self):
        """A disposed matter is not flagged for limitation."""
        row = {
            **MATTER_ROW,
            "status": "disposed",
            "limitation_expiry": date(2020, 1, 1),
        }
        store = FakeStore(rows=[row])
        with use_store(store):
            result = await matter_tools.list_matters()
        assert result["limitation_alerts"] == []

    @pytest.mark.asyncio
    async def test_filters_are_parameterised(self):
        """Filters become bound parameters, not string interpolation."""
        store = FakeStore(rows=[])
        with use_store(store):
            await matter_tools.list_matters(status="open", matter_type="civil_suit")
        assert "status = $1" in store.queries[0]
        assert "matter_type = $2" in store.queries[0]
        assert store.args[0][:2] == ("open", "civil_suit")


class TestGetMatter:
    """Loading a matter with its related records."""

    @pytest.mark.asyncio
    async def test_missing_matter(self):
        """A missing matter is reported as not found."""
        store = FakeStore(row=None)
        with use_store(store):
            result = await matter_tools.get_matter(1)
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_limitation_status_computed(self):
        """An expired limitation date is flagged on load."""
        row = {**MATTER_ROW, "limitation_expiry": date(2020, 1, 1)}
        store = FakeStore(row=row, rows=[])
        with use_store(store):
            result = await matter_tools.get_matter(3)
        assert result["limitation_status"]["expired"] is True
        assert result["limitation_status"]["urgency"] == "EXPIRED"


class TestHearingsAndEvents:
    """Hearings, events and the merged chronology."""

    @pytest.mark.asyncio
    async def test_add_hearing_requires_existing_matter(self):
        """A hearing cannot be attached to a matter that does not exist."""
        store = FakeStore(value=None)
        with use_store(store):
            result = await matter_tools.add_hearing(99, "2026-09-12")
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_add_hearing_serialises_dates(self):
        """Dates come back as ISO strings."""
        row = {
            "id": 1,
            "matter_id": 3,
            "hearing_date": date(2026, 9, 12),
            "purpose": "Framing of charge",
            "bench": None,
            "outcome": None,
            "next_date": date(2026, 10, 20),
            "created_at": NOW,
        }
        store = FakeStore(row=row, value=1)
        with use_store(store):
            result = await matter_tools.add_hearing(
                3, "2026-09-12", purpose="Framing of charge", next_date="2026-10-20"
            )
        assert result["status"] == "success"
        assert result["hearing"]["hearing_date"] == "2026-09-12"
        assert result["hearing"]["next_date"] == "2026-10-20"

    @pytest.mark.asyncio
    async def test_upcoming_hearings_flags_imminent(self):
        """Listings within a week are separated out."""
        listed = date.today()
        store = FakeStore(
            rows=[
                {
                    "id": 1,
                    "matter_id": 3,
                    "title": "Matter",
                    "case_number": None,
                    "court": None,
                    "listed_date": listed,
                    "purpose": "Hearing",
                    "bench": None,
                }
            ]
        )
        with use_store(store):
            result = await matter_tools.list_upcoming_hearings(days=30)
        assert result["imminent"]
        assert result["hearings"][0]["days_away"] == 0

    @pytest.mark.asyncio
    async def test_log_event_requires_description(self):
        """An empty description is rejected."""
        store = FakeStore(value=1)
        with use_store(store):
            result = await matter_tools.log_matter_event(3, "notice_sent", "  ")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_timeline_merges_and_sorts(self):
        """Cause of action, events and hearings merge into one ordered list."""
        store = FakeStore(
            row={
                "id": 3,
                "title": "Matter",
                "cause_of_action_date": date(2026, 7, 15),
                "filing_date": date(2026, 9, 1),
            },
            rows=[],
        )
        with use_store(store):
            result = await matter_tools.get_matter_timeline(3)
        dates = [e["date"] for e in result["chronology"]]
        assert dates == sorted(dates)
        assert "2026-07-15" in dates


class TestDocumentToolsWithFakeStore:
    """Document listing, retrieval and search against a fake store."""

    @pytest.mark.asyncio
    async def test_get_document_truncates_and_says_so(self):
        """A truncated document reports the truncation."""
        store = FakeStore(
            row={
                "id": 5,
                "title": "Vendor agreement",
                "doc_type": "contract",
                "matter_id": 3,
                "page_count": 12,
                "char_count": 50000,
                "source_path": "/tmp/x.pdf",
                "full_text": "x" * 50000,
            }
        )
        with patch(
            "legal_mcp_server.src.tools.document_tools.get_store", lambda: store
        ):
            result = await document_tools.get_document(5, max_chars=100)
        assert result["truncated"] is True
        assert len(result["text"]) == 100
        assert "truncated" in result["message"]

    @pytest.mark.asyncio
    async def test_get_missing_document(self):
        """A missing document id is reported."""
        store = FakeStore(row=None)
        with patch(
            "legal_mcp_server.src.tools.document_tools.get_store", lambda: store
        ):
            result = await document_tools.get_document(404)
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_list_documents_reports_embedding_status(self):
        """The listing states whether semantic search is even available."""
        store = FakeStore(rows=[])
        with patch(
            "legal_mcp_server.src.tools.document_tools.get_store", lambda: store
        ):
            result = await document_tools.list_my_documents()
        assert result["status"] == "success"
        assert "embedding_status" in result

    @pytest.mark.asyncio
    async def test_search_falls_back_to_fulltext_and_discloses_it(self):
        """With embeddings off, search reports fulltext_only rather than hiding it."""
        store = FakeStore(
            rows=[
                {
                    "id": 1,
                    "document_id": 5,
                    "chunk_index": 0,
                    "heading_path": "3. INDEMNITY",
                    "content": "The Consultant shall indemnify...",
                    "title": "Vendor agreement",
                    "doc_type": "contract",
                    "matter_id": 3,
                    "score": 0.9,
                }
            ]
        )
        store.vector_enabled = False
        with patch(
            "legal_mcp_server.src.tools.document_tools.get_store", lambda: store
        ):
            result = await document_tools.search_my_documents("indemnity")
        assert result["status"] == "success"
        assert result["search_mode"] == "fulltext_only"
        assert result["results"][0]["matched_by"] == ["fulltext"]

    @pytest.mark.asyncio
    async def test_search_rejects_empty_query(self):
        """An empty query is rejected."""
        result = await document_tools.search_my_documents("")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_ingest_rejects_unsupported_type(self, tmp_path):
        """An unsupported extension is rejected before any database work."""
        target = tmp_path / "notes.rtf"
        target.write_text("hello")
        result = await document_tools.ingest_document(str(target))
        assert result["status"] == "error"
        assert "Unsupported file type" in result["message"]

    @pytest.mark.asyncio
    async def test_ingest_detects_duplicate(self, tmp_path):
        """Re-ingesting the same bytes is reported as a duplicate, not re-indexed."""
        target = tmp_path / "agreement.txt"
        target.write_text("1. TERM\nThis agreement runs for two years.\n")
        store = FakeStore(row={"id": 5, "title": "agreement"})
        with patch(
            "legal_mcp_server.src.tools.document_tools.get_store", lambda: store
        ):
            result = await document_tools.ingest_document(str(target))
        assert result["duplicate"] is True
        assert result["document_id"] == 5

    @pytest.mark.asyncio
    async def test_ingest_text_file_end_to_end(self, tmp_path):
        """A plain text file is chunked and written without embeddings."""
        target = tmp_path / "agreement.txt"
        body = "This clause sets out the obligations of the parties. " * 8
        target.write_text(f"1. TERM\n{body}\n\n2. PAYMENT\n{body}\n")

        store = FakeStore(row=None, value=7)
        store.vector_enabled = False
        with patch(
            "legal_mcp_server.src.tools.document_tools.get_store", lambda: store
        ):
            result = await document_tools.ingest_document(
                str(target), doc_type="contract", matter_id=3
            )
        assert result["status"] == "success"
        assert result["document_id"] == 7
        assert result["chunk_count"] >= 2
        assert result["embeddings_generated"] is False
        assert any("INSERT INTO document_chunks" in q for q in store.queries)

    def test_extract_text_rejects_empty_file(self, tmp_path):
        """An empty file is an error rather than an empty index entry."""
        target = tmp_path / "empty.txt"
        target.write_text("")
        with pytest.raises(ValueError):
            document_tools.extract_text(target)
