"""Tests for limitation computation under the Limitation Act, 1963.

These are the highest-consequence calculations in the server, so the cases
below are worked from the provisions rather than from the implementation.
"""

from datetime import date

import pytest

from legal_mcp_server.src.domain import limitation


class TestAddPeriod:
    """Calendar arithmetic for limitation periods."""

    def test_days(self):
        """Days are added literally."""
        assert limitation.add_period(date(2026, 1, 1), 30, "days") == date(2026, 1, 31)

    def test_months_are_calendar_based(self):
        """One month from 31 January is 28 February, not 3 March."""
        assert limitation.add_period(date(2026, 1, 31), 1, "months") == date(
            2026, 2, 28
        )

    def test_years_handle_leap_day(self):
        """One year from 29 February lands on 28 February."""
        assert limitation.add_period(date(2024, 2, 29), 1, "years") == date(2025, 2, 28)

    def test_unknown_unit_rejected(self):
        """An unrecognised unit raises rather than silently defaulting."""
        with pytest.raises(ValueError):
            limitation.add_period(date(2026, 1, 1), 1, "fortnights")


class TestSection12StartingDay:
    """Section 12(1): the day the period runs from is excluded."""

    def test_starting_day_excluded(self):
        """A three-year period from 10 April 2023 expires on 10 April 2026."""
        result = limitation.compute("breach_of_contract", date(2023, 4, 10))
        assert result.adjusted_expiry == date(2026, 4, 10)

    def test_reasoning_names_the_provision(self):
        """The reasoning states which provision produced the start date."""
        result = limitation.compute("breach_of_contract", date(2023, 4, 10))
        assert any("Section 12(1)" in line for line in result.reasoning)


class TestSection12CopyTime:
    """Section 12(2): time to obtain a certified copy is excluded."""

    def test_copy_time_extends_expiry(self):
        """Fifteen days of copy time push the expiry out by fifteen days."""
        result = limitation.compute(
            "appeal_hc_decree",
            date(2026, 5, 2),
            copy_application_date=date(2026, 5, 5),
            copy_ready_date=date(2026, 5, 20),
        )
        assert (result.adjusted_expiry - result.base_expiry).days == 15
        assert any(e["provision"] == "section 12(2)" for e in result.exclusions)

    def test_ready_before_application_rejected(self):
        """Copy dates in the wrong order are an error, not a negative exclusion."""
        with pytest.raises(ValueError):
            limitation.compute(
                "appeal_hc_decree",
                date(2026, 5, 2),
                copy_application_date=date(2026, 5, 20),
                copy_ready_date=date(2026, 5, 5),
            )


class TestSection14WrongForum:
    """Section 14: bona fide proceedings in a court without jurisdiction."""

    def test_days_excluded(self):
        """Excluded days extend the expiry by the same number."""
        result = limitation.compute(
            "breach_of_contract", date(2023, 4, 10), wrong_forum_days=100
        )
        assert (result.adjusted_expiry - result.base_expiry).days == 100

    def test_negative_days_rejected(self):
        """A negative exclusion is rejected."""
        with pytest.raises(ValueError):
            limitation.compute(
                "breach_of_contract", date(2023, 4, 10), wrong_forum_days=-5
            )


class TestSection18Acknowledgment:
    """Section 18: a written acknowledgment restarts the clock, once."""

    def test_acknowledgment_before_expiry_restarts_period(self):
        """A fresh three years runs from the day after the acknowledgment."""
        result = limitation.compute(
            "money_lent", date(2021, 1, 15), acknowledgment_date=date(2023, 6, 1)
        )
        assert result.adjusted_expiry == date(2026, 6, 1)

    def test_acknowledgment_after_expiry_does_not_revive(self):
        """An acknowledgment after expiry cannot revive a time-barred claim."""
        result = limitation.compute(
            "money_lent", date(2018, 1, 15), acknowledgment_date=date(2025, 6, 1)
        )
        assert result.adjusted_expiry == date(2021, 1, 15)
        assert any("does NOT apply" in line for line in result.reasoning)


class TestSection4CourtClosed:
    """Section 4: expiry on a day the court is closed moves to the next open day."""

    def test_expiry_moves_off_a_closed_day(self):
        """A deadline landing on a closure is carried to the next working day."""
        closed = {date(2026, 4, 10), date(2026, 4, 11), date(2026, 4, 12)}
        result = limitation.compute(
            "breach_of_contract",
            date(2023, 4, 10),
            court_closed_check=lambda d: d in closed,
        )
        assert result.adjusted_expiry == date(2026, 4, 13)
        assert any(e["provision"] == "section 4" for e in result.exclusions)

    def test_open_day_is_untouched(self):
        """An expiry on a working day is not moved."""
        result = limitation.compute(
            "breach_of_contract", date(2023, 4, 10), court_closed_check=lambda d: False
        )
        assert result.adjusted_expiry == date(2026, 4, 10)


class TestExpiryReporting:
    """Days remaining and the expired flag."""

    def test_expired_claim(self):
        """A claim measured after expiry reports as expired."""
        result = limitation.compute(
            "breach_of_contract", date(2015, 1, 1), as_on=date(2026, 1, 1)
        )
        assert result.expired is True
        assert result.days_remaining is not None and result.days_remaining < 0

    def test_live_claim(self):
        """A claim measured before expiry reports days remaining."""
        result = limitation.compute(
            "breach_of_contract", date(2025, 1, 1), as_on=date(2026, 1, 1)
        )
        assert result.expired is False
        assert result.days_remaining == 730

    def test_no_measurement_date(self):
        """Without an as-on date the expired flag is unknown, not assumed."""
        result = limitation.compute("breach_of_contract", date(2025, 1, 1))
        assert result.expired is None


class TestRuleCatalogue:
    """The curated rule set and its search."""

    def test_unknown_rule_raises(self):
        """An unknown rule key raises rather than falling back to a default."""
        with pytest.raises(KeyError):
            limitation.compute("no_such_rule", date(2026, 1, 1))

    def test_find_rules_by_description(self):
        """A plain-language description surfaces the relevant rule."""
        keys = [r.key for r in limitation.find_rules("money lent to a friend")]
        assert "money_lent" in keys

    def test_every_rule_cites_authority(self):
        """No rule ships without naming the provision it rests on."""
        for rule in limitation.RULES.values():
            assert rule.authority
            assert rule.starting_point

    def test_arbitration_outer_limit_flagged_as_condonable(self):
        """Section 34 delay is condonable but only within a hard outer limit."""
        rule = limitation.RULES["arbitration_set_aside"]
        assert rule.condonable is True
        assert "30 days" in (rule.condonation_note or "")

    def test_ni_notice_period_is_not_condonable(self):
        """The 30-day s.138 notice period must not be marked condonable."""
        assert limitation.RULES["ni_138_notice"].condonable is False


class TestChequeBounceTimeline:
    """The three clocks in a section 138 matter."""

    def test_notice_deadline_is_thirty_days(self):
        """The demand notice is due 30 days after dishonour."""
        result = limitation.cheque_bounce_timeline(date(2026, 7, 15))
        assert result["steps"][0]["deadline"] == "2026-08-14"
        assert result["steps"][0]["condonable"] is False

    def test_incomplete_until_notice_issued(self):
        """Later deadlines are not computed before the notice exists."""
        result = limitation.cheque_bounce_timeline(date(2026, 7, 15))
        assert result["complete"] is False
        assert len(result["steps"]) == 1

    def test_late_notice_flagged_as_missed(self):
        """A notice issued after 30 days is reported as missed, not accepted."""
        result = limitation.cheque_bounce_timeline(
            date(2026, 7, 15), notice_date=date(2026, 8, 19)
        )
        assert result["steps"][0]["status"] == "MISSED"
        assert "not maintainable" in result["steps"][0]["warning"]

    def test_full_timeline_from_service(self):
        """Payment window and complaint deadline run from service."""
        result = limitation.cheque_bounce_timeline(
            date(2026, 7, 15),
            notice_date=date(2026, 7, 20),
            notice_served_date=date(2026, 7, 24),
        )
        assert result["steps"][1]["deadline"] == "2026-08-08"
        assert result["cause_of_action_date"] == "2026-08-09"
        assert result["complaint_deadline"] == "2026-09-08"
        assert result["complete"] is True

    def test_service_date_defaults_to_notice_date_with_a_warning(self):
        """Falling back to the notice date is disclosed, not silent."""
        result = limitation.cheque_bounce_timeline(
            date(2026, 7, 15), notice_date=date(2026, 7, 20)
        )
        assert "service date was not" in result["steps"][1]["service_basis"]

    def test_jurisdiction_note_present(self):
        """The territorial-jurisdiction rule travels with the timeline."""
        result = limitation.cheque_bounce_timeline(
            date(2026, 7, 15), notice_date=date(2026, 7, 20)
        )
        assert "142(2)(a)" in result["jurisdiction_note"]
