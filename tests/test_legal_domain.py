"""Tests for the criminal-code concordance, court calendar and clause rules."""

from datetime import date

from legal_mcp_server.src.domain import clause_rules, holidays
from legal_mcp_server.src.domain import new_criminal_codes as ncc


class TestApplicableCode:
    """Which criminal code governs an offence, by date."""

    def test_offence_before_commencement_is_ipc(self):
        """An offence on 30 June 2024 remains an IPC offence."""
        result = ncc.applicable_code(date(2024, 6, 30))
        assert result["regime"] == "old"
        assert result["penal_code"] == ncc.CODE_IPC
        assert result["procedure_code"] == ncc.CODE_CRPC

    def test_offence_on_commencement_is_bns(self):
        """An offence on 1 July 2024 is a BNS offence."""
        result = ncc.applicable_code(date(2024, 7, 1))
        assert result["regime"] == "new"
        assert result["penal_code"] == ncc.CODE_BNS

    def test_old_regime_carries_procedural_caveat(self):
        """Pending-proceeding savings are flagged, not assumed away."""
        result = ncc.applicable_code(date(2023, 1, 1))
        assert "savings" in result["caveat"]


class TestConcordance:
    """Old-to-new and new-to-old section mapping."""

    def test_ipc_420_maps_to_bns_318(self):
        """Cheating maps from IPC 420 to BNS 318(4)."""
        mappings = ncc.map_old_to_new("420", domain="penal")
        assert mappings and mappings[0].new_section == "318(4)"

    def test_reverse_lookup_by_bare_number(self):
        """BNS 318 resolves back even without the sub-section."""
        assert ncc.map_new_to_old("318", domain="penal")

    def test_crpc_482_maps_to_bnss_528(self):
        """The quashing jurisdiction maps from CrPC 482 to BNSS 528."""
        mappings = ncc.map_old_to_new("482", domain="procedure")
        assert mappings and mappings[0].new_section == "528"

    def test_evidence_65b_carries_substantive_note(self):
        """The 65B to BSA 63 change is flagged as substantive."""
        mappings = ncc.map_old_to_new("65B", domain="evidence")
        assert mappings and mappings[0].note

    def test_unknown_section_returns_empty(self):
        """An unmapped section returns nothing rather than a guess."""
        assert ncc.map_old_to_new("9999") == []

    def test_domain_filter_disambiguates(self):
        """A number used in two codes is separated by domain."""
        penal = ncc.map_old_to_new("34", domain="penal")
        assert all(m.domain == "penal" for m in penal)

    def test_search_by_subject(self):
        """Mappings can be found by describing the offence."""
        results = ncc.search_by_subject("criminal breach of trust")
        assert any("breach of trust" in m.subject.lower() for m in results)

    def test_coverage_reported(self):
        """Coverage counts are available so gaps can be stated honestly."""
        coverage = ncc.coverage()
        assert coverage["total"] == sum(
            coverage[k] for k in ("penal", "procedure", "evidence")
        )


class TestHolidays:
    """Court closures and calendar confidence."""

    def test_sunday_is_closed(self):
        """Sundays are always closures."""
        assert holidays.is_court_closed(date(2026, 8, 2))

    def test_republic_day_is_closed(self):
        """Fixed-date national holidays are known without a calendar file."""
        assert holidays.holiday_reason(date(2026, 1, 26)) == "Republic Day"

    def test_ordinary_weekday_is_open(self):
        """A plain Tuesday is not a known closure."""
        assert not holidays.is_court_closed(date(2026, 8, 4))

    def test_next_working_day_skips_closures(self):
        """The next working day skips a weekend."""
        # 2026-08-01 is a Saturday.
        assert holidays.next_working_day(date(2026, 8, 1)) == date(2026, 8, 3)

    def test_confidence_warns_when_no_calendar_installed(self):
        """A missing calendar produces an explicit caveat, not silence."""
        confidence = holidays.calendar_confidence(date(2026, 8, 4))
        if not confidence["year_covered"]:
            assert confidence["caveat"]
            assert "festival" in confidence["caveat"]

    def test_add_working_days(self):
        """Working-day arithmetic skips weekends."""
        # Monday 3 Aug 2026 + 5 working days = Monday 10 Aug 2026.
        assert holidays.add_working_days(date(2026, 8, 3), 5) == date(2026, 8, 10)

    def test_known_closures_excludes_weekends(self):
        """The closure list reports occasions, not every Saturday."""
        closures = holidays.known_closures(2026)
        assert closures
        assert all("occasion" in c for c in closures)


SAMPLE_CONTRACT = """
CONSULTANCY AGREEMENT between Acme Pvt Ltd and Mr B Sharma.
WHEREAS the Consultant has agreed to provide services.

1. TERM
This Agreement shall remain in force for 24 months and shall automatically
renew for successive periods of 12 months unless either party gives notice.

2. PAYMENT
The consideration payable shall be Rs 1,50,000 per month against invoice.

3. INDEMNITY
The Consultant shall indemnify and hold harmless the Company against all
claims, losses, damages and liabilities arising out of the services.

4. NON-COMPETE
For a period of 24 months after termination of this Agreement, the Consultant
shall not directly or indirectly compete with the Company.

6. DISPUTE RESOLUTION
Any dispute shall be referred to arbitration. The venue shall be Mumbai.

7. JURISDICTION
The courts at Mumbai shall have exclusive jurisdiction.
"""


class TestClauseRules:
    """Clause classification and India-specific risk rules."""

    def test_classifies_known_clauses(self):
        """Standard clause types are located in the text."""
        found = clause_rules.classify_clauses(SAMPLE_CONTRACT)
        assert "indemnity" in found
        assert "non_compete" in found
        assert "arbitration" in found

    def test_missing_expected_clauses_reported(self):
        """A missing governing-law clause is surfaced."""
        missing = {
            c.key for c in clause_rules.missing_expected_clauses(SAMPLE_CONTRACT)
        }
        assert "governing_law" in missing

    def test_post_termination_non_compete_is_high_severity(self):
        """The section 27 point is caught and cited."""
        flags = {f.rule: f for f in clause_rules.assess_risks(SAMPLE_CONTRACT)}
        flag = flags["post_termination_non_compete"]
        assert flag.severity is clause_rules.Severity.HIGH
        assert "section 27" in (flag.authority or "")

    def test_arbitration_seat_missing_flagged(self):
        """Venue without a seat is flagged as high severity."""
        flags = {f.rule for f in clause_rules.assess_risks(SAMPLE_CONTRACT)}
        assert "arbitration_seat_unclear" in flags

    def test_uncapped_liability_flagged(self):
        """An indemnity with no cap anywhere is flagged."""
        flags = {f.rule for f in clause_rules.assess_risks(SAMPLE_CONTRACT)}
        assert "uncapped_liability" in flags

    def test_auto_renewal_flagged(self):
        """Automatic renewal is surfaced so the notice date can be diarised."""
        flags = {f.rule for f in clause_rules.assess_risks(SAMPLE_CONTRACT)}
        assert "auto_renewal" in flags

    def test_flags_sorted_by_severity(self):
        """High-severity flags come first."""
        flags = clause_rules.assess_risks(SAMPLE_CONTRACT)
        order = [f.severity for f in flags]
        assert order == sorted(
            order,
            key=lambda s: {"high": 0, "medium": 1, "low": 2, "info": 3}[s.value],
        )

    def test_seated_arbitration_not_flagged(self):
        """A properly seated arbitration clause is not flagged."""
        text = (
            "Any dispute shall be referred to arbitration by a sole arbitrator. "
            "The seat of arbitration shall be Mumbai. This Agreement is governed "
            "by the laws of India and is duly stamped. Either party may terminate "
            "on notice sent to the address below. Aggregate liability shall be "
            "capped at the fees paid."
        )
        flags = {f.rule for f in clause_rules.assess_risks(text)}
        assert "arbitration_seat_unclear" not in flags
        assert "uncapped_liability" not in flags

    def test_empty_text_yields_no_positive_flags(self):
        """Empty input does not produce pattern-match flags."""
        assert not [f for f in clause_rules.assess_risks("") if f.position >= 0]
