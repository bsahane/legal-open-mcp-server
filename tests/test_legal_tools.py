"""Tests for the MCP tool layer.

The contract every tool honours is checked here: a ``status`` key on every
response, an ``error`` status for bad input rather than an exception, and -
most importantly - a clear distinction between "the source said no" and "the
source could not be consulted".
"""

from unittest.mock import patch

import pytest

from legal_mcp_server.src.mcp import TOOL_GROUPS, LegalMCPServer
from legal_mcp_server.src.tools import (
    court_tools,
    deadline_tools,
    document_tools,
    drafting_tools,
    research_tools,
    statute_tools,
)


class TestToolRegistration:
    """Every declared tool group loads and registers."""

    @pytest.mark.asyncio
    async def test_server_registers_all_groups(self):
        """The server starts and exposes tools from every group."""
        server = LegalMCPServer()
        tools = await server.mcp.get_tools()
        assert len(tools) > 30

    def test_every_group_returns_callables(self):
        """Each group loader yields callables."""
        for name, loader in TOOL_GROUPS.items():
            tools = loader()
            assert tools, f"group '{name}' is empty"
            assert all(callable(t) for t in tools)

    def test_tool_names_are_unique(self):
        """No two groups export the same tool name."""
        names = [t.__name__ for loader in TOOL_GROUPS.values() for t in loader()]
        assert len(names) == len(set(names))

    def test_every_tool_has_structured_docstring(self):
        """Tool selection depends on the structured docstring header."""
        for loader in TOOL_GROUPS.values():
            for tool in loader():
                doc = tool.__doc__ or ""
                for marker in ("TOOL_NAME=", "USECASE=", "OUTPUT_DESCRIPTION="):
                    assert marker in doc, f"{tool.__name__} is missing {marker}"

    def test_server_instructions_mention_the_new_codes(self):
        """The persona brief carries the BNS commencement date."""
        from legal_mcp_server.src.mcp import SERVER_INSTRUCTIONS

        assert "1 July 2024" in SERVER_INSTRUCTIONS
        assert "verify_all_citations" in SERVER_INSTRUCTIONS


class TestStatuteTools:
    """Bare-Act lookup and the criminal-code concordance."""

    def test_get_section_authentic_text(self):
        """A fully bundled Act returns authentic statutory text."""
        result = statute_tools.get_section("NI Act", "138")
        assert result["status"] == "success"
        assert result["text_kind"] == "authentic"
        assert "cheque" in result["text"].lower()

    def test_get_section_summary_is_labelled(self):
        """A curated summary is never presented as statutory text."""
        result = statute_tools.get_section("Indian Contract Act, 1872", "27")
        assert result["status"] == "success"
        assert result["text_kind"] == "summary"
        assert "caveat" in result
        assert "SUMMARY" in result["message"]

    def test_missing_section_in_complete_act(self):
        """A gap in a complete Act means the section does not exist."""
        result = statute_tools.get_section("NI Act", "9999")
        assert result["status"] == "not_found"
        assert "fully bundled" in result["message"]

    def test_missing_section_in_partial_act_is_not_a_denial(self):
        """A gap in a partial Act must not be reported as non-existence."""
        result = statute_tools.get_section("Indian Contract Act, 1872", "999")
        assert result["status"] == "not_found"
        assert "NOT a finding" in result["message"]

    def test_unknown_act(self):
        """An Act outside the corpus is reported as unchecked."""
        result = statute_tools.get_section("Fictitious Widgets Act, 1999", "5")
        assert result["status"] == "not_found"
        assert "indiacode.nic.in" in result["message"]

    def test_search_statute_finds_section_138(self):
        """Subject search locates the governing provision."""
        result = statute_tools.search_statute("dishonour of cheque")
        assert result["status"] == "success"
        assert any(r["section"] == "138" for r in result["results"])

    def test_which_code_applies_boundary(self):
        """The commencement boundary is handled exactly."""
        assert (
            statute_tools.which_criminal_code_applies("2024-06-30")["regime"] == "old"
        )
        assert (
            statute_tools.which_criminal_code_applies("2024-07-01")["regime"] == "new"
        )

    def test_which_code_rejects_bad_date(self):
        """A malformed date is an error, not a silent default to today."""
        result = statute_tools.which_criminal_code_applies("30-06-2024")
        assert result["status"] == "error"

    def test_map_section_with_offence_date(self):
        """The mapping reports the governing regime alongside the equivalence."""
        result = statute_tools.map_criminal_code_section(
            "420", offence_date="2024-03-15"
        )
        assert result["status"] == "success"
        assert result["applicable_regime"]["regime"] == "old"

    def test_map_unknown_section_admits_gap(self):
        """An unmapped section says the concordance is partial."""
        result = statute_tools.map_criminal_code_section("9999")
        assert result["status"] == "not_found"
        assert "do not guess" in result["message"]

    def test_list_bundled_acts_reports_coverage(self):
        """Coverage is enumerable so partial Acts can be flagged."""
        result = statute_tools.list_bundled_acts()
        assert result["status"] == "success"
        assert result["act_count"] > 0
        assert "complete_acts" in result


class TestDeadlineTools:
    """Limitation and deadline tools."""

    def test_compute_limitation_success(self):
        """A known claim type computes an expiry and an urgency."""
        result = deadline_tools.compute_limitation(
            "breach_of_contract", "2023-04-10", as_on="2026-01-01"
        )
        assert result["status"] == "success"
        assert result["expiry_date"] == "2026-04-10"
        assert result["urgency"] in {"IN_TIME", "SOON", "CRITICAL", "EXPIRED"}

    def test_unknown_claim_type_suggests_alternatives(self):
        """An unknown claim type offers candidates rather than a default period."""
        result = deadline_tools.compute_limitation("money lent", "2023-04-10")
        assert result["status"] == "not_found"
        assert "money_lent" in result["suggestions"]

    def test_bad_date_format_rejected(self):
        """A non-ISO date is rejected explicitly."""
        result = deadline_tools.compute_limitation("breach_of_contract", "10/04/2023")
        assert result["status"] == "error"
        assert "YYYY-MM-DD" in result["error"]

    def test_expired_claim_flagged(self):
        """An out-of-time claim is reported as EXPIRED with the section 3 point."""
        result = deadline_tools.compute_limitation(
            "breach_of_contract", "2015-01-01", as_on="2026-01-01"
        )
        assert result["urgency"] == "EXPIRED"
        assert "Section 3" in result["message"]

    def test_calendar_confidence_attached(self):
        """Every computed deadline carries its calendar confidence."""
        result = deadline_tools.compute_limitation("breach_of_contract", "2023-04-10")
        assert "calendar_confidence" in result

    def test_cheque_timeline_tool(self):
        """The section 138 timeline is exposed with its urgency."""
        result = deadline_tools.compute_cheque_bounce_timeline("2026-07-15")
        assert result["status"] == "success"
        assert "NOT extendable" in result["message"]

    def test_compute_deadline_months(self):
        """Month arithmetic is calendar-based, then moved off a court closure.

        One month from 31 January 2026 is 28 February 2026, which is a
        Saturday, so section 4 carries it to the next working day.
        """
        result = deadline_tools.compute_deadline("2026-01-31", 1, unit="months")
        assert result["status"] == "success"
        assert result["moved_from"] == "2026-02-28"
        assert result["closure_reason"] == "Saturday"
        assert result["deadline"] == "2026-03-02"

    def test_compute_deadline_on_a_working_day_is_not_moved(self):
        """A deadline landing on a weekday is returned unchanged."""
        result = deadline_tools.compute_deadline("2026-08-03", 7)
        assert result["deadline"] == "2026-08-10"
        assert result["moved_from"] is None

    def test_working_days_only_rejects_month_unit(self):
        """Working-day counting is only meaningful in days."""
        result = deadline_tools.compute_deadline(
            "2026-01-01", 2, unit="months", working_days_only=True
        )
        assert result["status"] == "error"

    def test_find_limitation_rule(self):
        """Rules are discoverable by description."""
        result = deadline_tools.find_limitation_rule("unpaid invoice for goods")
        assert result["status"] == "success"
        assert result["candidate_count"] > 0

    def test_list_limitation_rules_states_it_is_curated(self):
        """The catalogue admits it is not the whole Schedule."""
        result = deadline_tools.list_limitation_rules()
        assert "curated" in result["message"]


class TestResearchTools:
    """Case-law tools on the free backend with nothing synced yet."""

    @pytest.mark.asyncio
    async def test_search_without_corpus_is_unavailable_not_empty(self, tmp_path):
        """An unsynced corpus must say 'unavailable', never 'no authority found'.

        This is the distinction that stops the model filling a gap from memory.
        """
        from legal_mcp_server.src.sources import open_judgments

        client = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with patch.object(open_judgments, "get_client", return_value=client):
            result = await research_tools.search_case_law("test query")

        assert result["status"] == "unavailable"
        assert "NOT a finding" in result["message"]

    @pytest.mark.asyncio
    async def test_statutory_citation_verified_offline(self):
        """Statutory citations verify without any paid call."""
        result = await research_tools.verify_citation(
            "Section 138 of the Negotiable Instruments Act, 1881"
        )
        assert result["verdict"] == research_tools.VERDICT_VERIFIED

    @pytest.mark.asyncio
    async def test_wrong_section_number_not_found(self):
        """A section that does not exist in a complete Act is NOT_FOUND."""
        result = await research_tools.verify_citation(
            "Section 9999 of the Negotiable Instruments Act, 1881"
        )
        assert result["verdict"] == research_tools.VERDICT_NOT_FOUND

    @pytest.mark.asyncio
    async def test_unknown_act_is_unchecked_not_rejected(self):
        """An Act outside the corpus is UNCHECKED, not falsely denied."""
        result = await research_tools.verify_citation(
            "Section 5 of the Fictitious Widgets Act, 1999"
        )
        assert result["verdict"] == research_tools.VERDICT_UNCHECKED

    @pytest.mark.asyncio
    async def test_unrecognised_format(self):
        """Text that is not a citation is reported as unrecognised."""
        result = await research_tools.verify_citation("not a citation at all")
        assert result["verdict"] == research_tools.VERDICT_UNCHECKED

    @pytest.mark.asyncio
    async def test_sweep_reports_unverified(self):
        """A sweep never reports all-clear when something is unverified."""
        text = (
            "As held in Fictional Ltd v. Nobody, (2099) 12 SCC 555, and under "
            "Section 138 of the Negotiable Instruments Act, 1881, the complaint lies."
        )
        result = await research_tools.verify_all_citations(text)
        assert result["all_verified"] is False
        assert result["unverified"]
        assert "UNVERIFIED" in result["message"]

    @pytest.mark.asyncio
    async def test_sweep_with_no_citations(self):
        """Prose with no citations is handled without claiming verification."""
        result = await research_tools.verify_all_citations("The parties met twice.")
        assert result["citation_count"] == 0

    def test_status_reports_unsynced_corpus_plainly(self, tmp_path):
        """Status must state that nothing is searchable until a sync happens."""
        from legal_mcp_server.src.sources import open_judgments

        client = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with patch.object(open_judgments, "get_client", return_value=client):
            result = research_tools.case_law_status()

        assert result["status"] == "success"
        assert result["backend"] == "open_data"
        assert result["available"] is False
        assert "sync_case_law" in result["message"]

    def test_status_reports_the_free_cost_model(self, tmp_path):
        """The active backend must be reported as free, so no one expects a bill."""
        from legal_mcp_server.src.sources import open_judgments

        client = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with patch.object(open_judgments, "get_client", return_value=client):
            result = research_tools.case_law_status()

        assert "free" in result["cost"]
        assert "no API key" in result["cost"]


class TestDraftingTools:
    """Template rendering and draft review."""

    def test_list_templates(self):
        """Templates are enumerable with their required parameters."""
        result = drafting_tools.list_templates()
        assert result["status"] == "success"
        keys = {t["key"] for t in result["templates"]}
        assert "ni_138_notice" in keys

    def test_missing_parameters_refuses_to_draft(self):
        """A template will not render with placeholders in place of facts."""
        result = drafting_tools.draft_document("ni_138_notice", {"sender_name": "X"})
        assert result["status"] == "incomplete"
        assert result["missing_parameters"]
        assert "Do not" in result["message"]

    def test_unknown_template(self):
        """An unknown template lists the real ones rather than improvising."""
        result = drafting_tools.draft_document("no_such_template", {})
        assert result["status"] == "not_found"
        assert result["available"]

    def test_render_rti_application(self):
        """A complete parameter set renders a usable document."""
        result = drafting_tools.draft_document(
            "rti_application",
            {
                "public_authority": "Municipal Corporation of Greater Mumbai",
                "authority_address": "Fort, Mumbai 400001",
                "application_date": "2026-08-02",
                "information_sought": ["Copy of the building plan for CTS 123"],
                "applicant_name": "B Sahane",
                "applicant_address": "Andheri, Mumbai",
            },
        )
        assert result["status"] == "success"
        assert "Right to Information Act, 2005" in result["draft"]
        assert result["checklist"]

    def test_indian_digit_grouping(self):
        """Amounts use Indian grouping, not Western."""
        assert drafting_tools.inr(200000) == "2,00,000"
        assert drafting_tools.inr(1500) == "1,500"
        assert drafting_tools.inr(10000000) == "1,00,00,000"
        assert drafting_tools.inr(999) == "999"

    def test_inr_passes_through_non_numeric(self):
        """A non-numeric value is returned unchanged rather than crashing."""
        assert drafting_tools.inr("not a number") == "not a number"

    def test_review_draft_catches_placeholder(self):
        """An unfilled placeholder is high severity."""
        result = drafting_tools.review_draft("To, [INSERT NAME]\nDated: 2 August 2026")
        assert result["status"] == "success"
        assert result["high_severity_count"] >= 1

    def test_review_pleading_requires_verification(self):
        """A pleading without a verification clause is flagged."""
        result = drafting_tools.review_draft(
            "COMPLAINT before the District Commission. Dated: 2 August 2026."
        )
        issues = " ".join(i["issue"] for i in result["issues"])
        assert "verification" in issues.lower()

    def test_draft_document_defaults_to_english(self):
        """With no language, a template renders in English."""
        result = drafting_tools.draft_document(
            "rti_application",
            {
                "public_authority": "Municipal Corporation of Greater Mumbai",
                "authority_address": "Fort, Mumbai 400001",
                "application_date": "2026-08-02",
                "information_sought": ["Copy of the building plan for CTS 123"],
                "applicant_name": "B Sahane",
                "applicant_address": "Andheri, Mumbai",
            },
        )
        assert result["status"] == "success"
        assert result["language"] == "en"

    def test_draft_document_accepts_language(self):
        """A supported language renders the static text translated."""
        result = drafting_tools.draft_document(
            "ni_138_notice",
            {
                "sender_name": "F",
                "sender_address": "M",
                "notice_date": "2026-08-16",
                "recipient_name": "E",
                "recipient_address": "A",
                "client_name": "F",
                "client_address": "B",
                "liability_description": "goods",
                "cheque_number": "1",
                "cheque_date": "2026-06-01",
                "cheque_amount": 200000,
                "amount_in_words": "Two Lakh Only",
                "drawee_bank": "SBI",
                "drawee_branch": "Andheri",
                "payee_bank": "HDFC",
                "payee_branch": "Fort",
                "presentation_date": "2026-06-02",
                "dishonour_reason": "Insufficient Funds",
                "dishonour_memo_date": "2026-06-03",
                "dishonour_date": "2026-06-03",
            },
            language="hi",
        )
        assert result["status"] == "success"
        assert result["language"] == "hi"
        assert any("\u0900" <= ch <= "\u097F" for ch in result["draft"])

    def test_draft_document_rejects_unsupported_language(self):
        """A language a template does not support is refused, not silently
        ignored."""
        result = drafting_tools.draft_document(
            "ni_138_notice",
            {"sender_name": "X"},
            language="ta",
        )
        assert result["status"] == "unsupported_language"
        assert result["supported_languages"] == ["en", "hi"]

    def test_get_document_languages(self):
        """The supported languages of a template are reported."""
        result = drafting_tools.get_document_languages("writ_petition")
        assert result["status"] == "success"
        assert "en" in result["languages"]
        assert "hi" in result["languages"]

    def test_translate_document_is_rule_based(self):
        """Known static clauses are translated, user values preserved."""
        result = drafting_tools.draft_document(
            "ni_138_notice",
            {
                "sender_name": "F",
                "sender_address": "M",
                "notice_date": "2026-08-16",
                "recipient_name": "E",
                "recipient_address": "A",
                "client_name": "F",
                "client_address": "B",
                "liability_description": "goods",
                "cheque_number": "1",
                "cheque_date": "2026-06-01",
                "cheque_amount": 200000,
                "amount_in_words": "Two Lakh Only",
                "drawee_bank": "SBI",
                "drawee_branch": "Andheri",
                "payee_bank": "HDFC",
                "payee_branch": "Fort",
                "presentation_date": "2026-06-02",
                "dishonour_reason": "Insufficient Funds",
                "dishonour_memo_date": "2026-06-03",
                "dishonour_date": "2026-06-03",
            },
        )
        translated = drafting_tools.translate_document(
            result["draft"], target_language="hi"
        )
        assert translated["status"] == "success"
        assert translated["sentences_translated"] > 0
        assert any(
            "\u0900" <= ch <= "\u097F" for ch in translated["translated_draft"]
        )
        # user-supplied facts survive verbatim
        assert "SBI" in translated["translated_draft"]

    def test_translate_document_same_language_returns_unchanged(self):
        """Translating into the source language is a no-op."""
        result = drafting_tools.translate_document("Some draft text.", target_language="en")
        assert result["status"] == "success"
        assert result["translated_draft"] == "Some draft text."

    def test_new_court_templates_render(self):
        """The court-format templates render fully with no Jinja leftovers."""
        for key, params in [
            (
                "writ_petition",
                {
                    "court_place": "BOMBAY",
                    "petitioner_name": "A",
                    "petitioner_address": "Mumbai",
                    "respondent_name": "State",
                    "respondent_address": "Mumbai",
                    "petition_number": "1",
                    "year": "2026",
                    "facts": ["Fact"],
                    "grounds": ["Ground"],
                    "reliefs": ["Relief"],
                    "filing_date": "2026-08-16",
                    "advocate_name": "X",
                },
            ),
            (
                "civil_appeal",
                {
                    "court_place": "BOMBAY",
                    "appellant_name": "A",
                    "appellant_address": "Mumbai",
                    "respondent_name": "B",
                    "respondent_address": "Mumbai",
                    "appeal_number": "1",
                    "year": "2026",
                    "impugned_date": "2026-01-01",
                    "lower_court": "District Court",
                    "lower_court_place": "Thane",
                    "lower_court_case_no": "CS 1/2025",
                    "facts": ["Fact"],
                    "grounds": ["Ground"],
                    "filing_date": "2026-08-16",
                    "advocate_name": "X",
                },
            ),
            (
                "slp",
                {
                    "petitioner_name": "A",
                    "petitioner_address": "Delhi",
                    "respondent_name": "Union of India",
                    "respondent_address": "New Delhi",
                    "petition_number": "1",
                    "year": "2026",
                    "impugned_date": "2026-01-01",
                    "impugned_court": "High Court of Bombay",
                    "impugned_court_place": "Mumbai",
                    "impugned_court_case_no": "WP 1/2025",
                    "impugned_disposal": "Dismissed",
                    "facts": ["Fact"],
                    "grounds": ["Ground"],
                    "filing_date": "2026-08-16",
                    "advocate_name": "X",
                },
            ),
        ]:
            result = drafting_tools.draft_document(key, params)
            assert result["status"] == "success", key
            assert "{{" not in result["draft"], key
            assert result["checklist"], key


class TestDocumentTools:
    """Chunking and offline contract review."""

    def test_chunking_splits_on_clause_boundaries(self):
        """Substantial numbered clauses become separate chunks."""
        body = "This clause sets out the obligations of the parties in detail. " * 6
        text = f"PREAMBLE {body}\n\n1. TERM\n{body}\n\n2. PAYMENT\n{body}\n"
        chunks = document_tools.chunk_text(text)
        assert len(chunks) >= 3
        assert any("TERM" in (c["heading_path"] or "") for c in chunks)

    def test_chunking_merges_fragments_below_the_minimum(self):
        """Very short segments are merged rather than left as noise chunks."""
        text = "PREAMBLE.\n\n1. TERM\nShort.\n\n2. PAYMENT\nAlso short.\n"
        chunks = document_tools.chunk_text(text)
        assert len(chunks) == 1

    def test_chunking_handles_unstructured_text(self):
        """Prose with no structure still produces at least one chunk."""
        chunks = document_tools.chunk_text("Just a sentence with no headings.")
        assert len(chunks) == 1

    def test_review_contract_flags_and_disclaims(self):
        """The review flags issues and states its own limits."""
        text = (
            "The Consultant shall indemnify the Company against all claims. "
            "For 24 months after termination the Consultant shall not compete."
        )
        result = document_tools.review_contract(text)
        assert result["status"] == "success"
        assert result["high_severity_count"] >= 1
        assert "disclaimer" in result

    def test_review_contract_rejects_empty(self):
        """Empty input is an error, not an all-clear."""
        assert document_tools.review_contract("")["status"] == "error"

    def test_extract_clauses_reports_omissions(self):
        """Missing expected clauses are surfaced."""
        result = document_tools.extract_clauses(
            "This agreement is between A and B for payment of Rs 100."
        )
        assert result["status"] == "success"
        assert "missing_expected_clauses" in result

    @pytest.mark.asyncio
    async def test_ingest_rejects_missing_file(self):
        """A path that does not exist is an error with a clear message."""
        result = await document_tools.ingest_document("/no/such/file.pdf")
        assert result["status"] == "error"


class TestCourtTools:
    """Court status, directory and jurisdiction."""

    @pytest.mark.asyncio
    async def test_case_status_manual_mode_returns_instructions(self):
        """Manual mode returns steps rather than pretending to fetch."""
        result = await court_tools.get_case_status(cnr="MHMU010123452026")
        assert result["status"] == "manual_action_required"
        assert "CAPTCHA" in result["message"]
        assert result["steps"]

    @pytest.mark.asyncio
    async def test_case_status_requires_an_identifier(self):
        """Neither CNR nor case number is an error."""
        result = await court_tools.get_case_status()
        assert result["status"] == "error"

    def test_court_directory_admits_incompleteness(self):
        """The directory says it is not exhaustive."""
        result = court_tools.court_directory()
        assert result["status"] == "success"
        assert "not a complete list" in result["message"]

    def test_directory_filter(self):
        """Filtering by type returns only that type."""
        result = court_tools.court_directory(court_type="tribunal")
        assert set(result["courts"]) == {"tribunal"}

    def test_jurisdiction_cheque_uses_section_142(self):
        """A cheque matter is routed by section 142(2)(a)."""
        result = court_tools.determine_jurisdiction("dishonoured cheque", 200000)
        assert "142(2)(a)" in result["territorial_rule"]

    def test_jurisdiction_consumer(self):
        """A consumer matter is routed to the Commissions."""
        result = court_tools.determine_jurisdiction("defective product", 45000)
        assert "Consumer" in result["forum"]

    def test_jurisdiction_default_is_civil_court(self):
        """An unrecognised subject falls back to the CPC rules, and says so."""
        result = court_tools.determine_jurisdiction("some unusual dispute")
        assert "Code of Civil Procedure" in result["basis"]

    def test_jurisdiction_carries_pecuniary_caution(self):
        """Pecuniary limits are flagged as untracked."""
        result = court_tools.determine_jurisdiction("dishonoured cheque")
        assert "notification" in result["caution"]


class TestErrorContract:
    """Every tool returns a status rather than raising."""

    def test_sync_tools_return_status_on_bad_input(self):
        """Bad input yields an error response, not an exception."""
        cases = [
            lambda: statute_tools.get_section("", ""),
            lambda: statute_tools.search_statute(""),
            lambda: deadline_tools.find_limitation_rule(""),
            lambda: drafting_tools.review_draft(""),
            lambda: document_tools.extract_clauses(""),
            lambda: court_tools.determine_jurisdiction(""),
        ]
        for call in cases:
            result = call()
            assert "status" in result
            assert result["status"] in {"error", "not_found", "unavailable"}
