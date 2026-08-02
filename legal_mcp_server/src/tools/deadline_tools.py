"""Limitation and deadline tools for the Legal MCP Server.

A claim that cannot be filed in time is worth nothing regardless of its merits,
so these tools are meant to be reached for early - before the merits are
discussed, not after.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional, cast

from legal_mcp_server.src.domain import holidays, limitation
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()


def _parse_date(value: Optional[str], field: str) -> Optional[date]:
    """Parse a YYYY-MM-DD string, raising a clear error if malformed."""
    if value is None or value == "":
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError) as e:
        raise ValueError(f"{field} must be in YYYY-MM-DD form, got '{value}'") from e


def compute_limitation(
    claim_type: str,
    start_date: str,
    as_on: Optional[str] = None,
    acknowledgment_date: Optional[str] = None,
    copy_application_date: Optional[str] = None,
    copy_ready_date: Optional[str] = None,
    wrong_forum_days: int = 0,
    court: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute the limitation position for a claim under the Limitation Act, 1963.

    TOOL_NAME=compute_limitation
    DISPLAY_NAME=Limitation Period Calculator
    USECASE=Establish whether a claim is still in time, and by how long, before advising on its merits
    INSTRUCTIONS=1. Identify the claim type with find_limitation_rule if unsure, 2. Supply the date the cause of action arose, 3. Add any acknowledgment, certified-copy or wrong-forum facts, 4. Report the expiry date, the article relied on, and any caution attached to it
    INPUT_DESCRIPTION=claim_type (string, required): rule key such as "breach_of_contract", "money_lent", "consumer_complaint", "appeal_hc_decree". start_date (string, required): YYYY-MM-DD, when the period starts running. as_on (string, optional): date to measure against, defaults to today. acknowledgment_date (string, optional): written acknowledgment of liability under section 18. copy_application_date/copy_ready_date (string, optional): certified copy dates for section 12(2). wrong_forum_days (int, optional): days excluded under section 14. court (string, optional): court whose holiday calendar applies for section 4.
    OUTPUT_DESCRIPTION=Dictionary with status, the rule and its authority, expiry date, days remaining, expired flag, every exclusion applied, step-by-step reasoning, and the confidence of the holiday calendar used
    EXAMPLES=compute_limitation("breach_of_contract", "2023-04-10"), compute_limitation("money_lent", "2021-01-15", acknowledgment_date="2023-06-01"), compute_limitation("appeal_hc_decree", "2026-05-02", copy_application_date="2026-05-05", copy_ready_date="2026-05-20")
    PREREQUISITES=None - fully offline. Install a court holiday calendar for accurate section 4 treatment.
    RELATED_TOOLS=find_limitation_rule to identify the claim type; compute_cheque_bounce_timeline for section 138 matters; compute_deadline for a plain date calculation

    CPU-bound operation - uses def for date arithmetic.

    Args:
        claim_type: Key identifying the limitation rule.
        start_date: When the period begins, YYYY-MM-DD.
        as_on: Date to measure remaining time against.
        acknowledgment_date: Date of a section 18 acknowledgment.
        copy_application_date: Date a certified copy was applied for.
        copy_ready_date: Date the certified copy was ready.
        wrong_forum_days: Days excluded under section 14.
        court: Court whose holiday calendar governs section 4.

    Returns:
        Dict with the computed limitation position.
    """
    try:
        if claim_type not in limitation.RULES:
            suggestions = [r.key for r in limitation.find_rules(claim_type, limit=5)]
            return {
                "status": "not_found",
                "operation": "compute_limitation",
                "claim_type": claim_type,
                "suggestions": suggestions,
                "available_types": sorted(limitation.RULES),
                "message": (
                    f"'{claim_type}' is not a known limitation rule. "
                    + (
                        f"Closest matches: {', '.join(suggestions)}. "
                        if suggestions
                        else ""
                    )
                    + "Use find_limitation_rule to search by description. Do not "
                    "guess a period."
                ),
            }

        start = _parse_date(start_date, "start_date")
        if start is None:
            raise ValueError("start_date is required")

        measure_on = _parse_date(as_on, "as_on") or date.today()

        result = limitation.compute(
            rule_key=claim_type,
            start_date=start,
            as_on=measure_on,
            copy_application_date=_parse_date(
                copy_application_date, "copy_application_date"
            ),
            copy_ready_date=_parse_date(copy_ready_date, "copy_ready_date"),
            wrong_forum_days=wrong_forum_days,
            acknowledgment_date=_parse_date(acknowledgment_date, "acknowledgment_date"),
            court_closed_check=lambda d: holidays.is_court_closed(d, court),
        )

        payload = result.to_dict()
        days_left = result.days_remaining or 0

        if result.expired:
            urgency = "EXPIRED"
            headline = (
                f"This claim appears time-barred: the period expired on "
                f"{result.adjusted_expiry.isoformat()}, {abs(days_left)} days ago. "
                "Section 3 requires the court to dismiss a time-barred suit even "
                "if limitation is not pleaded."
                + (
                    " Delay may be condonable here - see the rule's condonation note."
                    if result.rule.condonable
                    else " This period is not condonable."
                )
            )
        elif days_left <= 30:
            urgency = "CRITICAL"
            headline = (
                f"Only {days_left} days remain - the period expires on "
                f"{result.adjusted_expiry.isoformat()}. Treat this as urgent and "
                "advise engaging an advocate immediately."
            )
        elif days_left <= 90:
            urgency = "SOON"
            headline = (
                f"{days_left} days remain, expiring "
                f"{result.adjusted_expiry.isoformat()}. Begin preparation now."
            )
        else:
            urgency = "IN_TIME"
            headline = (
                f"{days_left} days remain, expiring "
                f"{result.adjusted_expiry.isoformat()}."
            )

        return {
            "status": "success",
            "operation": "compute_limitation",
            **payload,
            "urgency": urgency,
            "calendar_confidence": holidays.calendar_confidence(
                result.adjusted_expiry, court
            ),
            "message": headline,
            "disclaimer": (
                "Limitation turns on exactly when the cause of action accrued, "
                "which is a question of fact. Confirm the start date against the "
                "documents before relying on this computation."
            ),
        }

    except Exception as e:
        logger.error(f"Error in compute_limitation: {e}")
        return {
            "status": "error",
            "operation": "compute_limitation",
            "error": str(e),
            "message": "Failed to compute limitation",
        }


def find_limitation_rule(description: str, limit: int = 8) -> Dict[str, Any]:
    """Find the limitation rule that governs a described claim.

    TOOL_NAME=find_limitation_rule
    DISPLAY_NAME=Limitation Rule Finder
    USECASE=Identify which limitation article applies when you know the nature of the claim but not the article
    INSTRUCTIONS=1. Describe the claim in a few words, 2. Read the candidate rules and their starting points, 3. Pass the chosen key to compute_limitation
    INPUT_DESCRIPTION=description (string, required): the claim in plain words, e.g. "unpaid invoice", "ex parte decree", "arbitral award", "defective product". limit (int, optional, default 8): maximum candidates.
    OUTPUT_DESCRIPTION=Dictionary with status, candidate rules including key, period, starting point, governing article, whether delay is condonable, and any caution
    EXAMPLES=find_limitation_rule("unpaid invoice for goods supplied"), find_limitation_rule("set aside arbitration award"), find_limitation_rule("ex parte decree")
    PREREQUISITES=None - fully offline
    RELATED_TOOLS=compute_limitation once the rule is identified; list_limitation_rules for the full catalogue

    CPU-bound operation - uses def for local table search.

    Args:
        description: Plain-language description of the claim.
        limit: Maximum candidate rules to return.

    Returns:
        Dict with the matching rules.
    """
    try:
        if not description or not description.strip():
            raise ValueError("description must be a non-empty string")

        matches = limitation.find_rules(
            description.strip(), limit=max(1, min(limit, 20))
        )

        return {
            "status": "success",
            "operation": "find_limitation_rule",
            "description": description,
            "candidates": [r.to_dict() for r in matches],
            "candidate_count": len(matches),
            "message": (
                f"Found {len(matches)} candidate rules. Choose by the starting "
                "point, not just the subject - most limitation errors come from "
                "the wrong start date, not the wrong period."
                if matches
                else "No rule matched. The residuary article (Article 113, three "
                "years from when the right to sue accrues) may apply, but check "
                "the Schedule for a specific article before assuming it."
            ),
        }

    except Exception as e:
        logger.error(f"Error in find_limitation_rule: {e}")
        return {
            "status": "error",
            "operation": "find_limitation_rule",
            "error": str(e),
            "message": "Failed to search limitation rules",
        }


def list_limitation_rules() -> Dict[str, Any]:
    """List every limitation rule this server can compute.

    TOOL_NAME=list_limitation_rules
    DISPLAY_NAME=Limitation Rule Catalogue
    USECASE=See the full set of limitation periods available before deciding whether a claim's period is modelled here at all
    INSTRUCTIONS=1. Call to review coverage, 2. If the claim is not listed, say the period is not modelled rather than inventing one
    INPUT_DESCRIPTION=No parameters
    OUTPUT_DESCRIPTION=Dictionary with status, every rule grouped by source Act, and the total count
    EXAMPLES=list_limitation_rules()
    PREREQUISITES=None
    RELATED_TOOLS=find_limitation_rule to search by description; compute_limitation to apply one

    CPU-bound operation - uses def for local table inspection.

    Returns:
        Dict cataloguing every modelled limitation rule.
    """
    try:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for rule in limitation.RULES.values():
            grouped.setdefault(rule.source_act, []).append(rule.to_dict())
        for entries in grouped.values():
            entries.sort(key=lambda r: str(r["key"]))

        return {
            "status": "success",
            "operation": "list_limitation_rules",
            "rules_by_act": grouped,
            "rule_count": len(limitation.RULES),
            "message": (
                f"{len(limitation.RULES)} limitation rules are modelled. This is a "
                "curated set, not the whole Schedule to the Limitation Act. If a "
                "claim is not covered here, say the period is not modelled and "
                "check the Schedule directly - do not extrapolate."
            ),
        }

    except Exception as e:
        logger.error(f"Error in list_limitation_rules: {e}")
        return {
            "status": "error",
            "operation": "list_limitation_rules",
            "error": str(e),
            "message": "Failed to list limitation rules",
        }


def compute_cheque_bounce_timeline(
    dishonour_date: str,
    notice_date: Optional[str] = None,
    notice_served_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute every deadline in a section 138 Negotiable Instruments Act matter.

    TOOL_NAME=compute_cheque_bounce_timeline
    DISPLAY_NAME=Cheque Dishonour Deadline Timeline
    USECASE=Work out the notice and complaint deadlines in a dishonoured-cheque matter, where the first deadline is non-extendable and routinely missed
    INSTRUCTIONS=1. Give the date the drawer learned of dishonour from the bank, 2. Give the notice date and, if known, the actual service date, 3. Act on the earliest pending deadline, 4. Warn the user explicitly that the 30-day notice period cannot be extended
    INPUT_DESCRIPTION=dishonour_date (string, required): YYYY-MM-DD, when the bank's dishonour memo was received. notice_date (string, optional): when the demand notice was issued. notice_served_date (string, optional): when it was actually served - service, not dispatch, starts the payment clock.
    OUTPUT_DESCRIPTION=Dictionary with status, each of the three steps with its deadline, authority and whether it is condonable, the cause-of-action date, the complaint deadline, and a note on territorial jurisdiction
    EXAMPLES=compute_cheque_bounce_timeline("2026-07-15"), compute_cheque_bounce_timeline("2026-07-15", notice_date="2026-07-20", notice_served_date="2026-07-24")
    PREREQUISITES=None - fully offline
    RELATED_TOOLS=draft_document with the s138 notice template; get_section for the text of section 138; compute_limitation for other claim types

    CPU-bound operation - uses def for date arithmetic.

    Args:
        dishonour_date: Date the drawer received the dishonour memo.
        notice_date: Date the statutory demand notice was issued.
        notice_served_date: Date the notice was served.

    Returns:
        Dict with the full statutory timeline.
    """
    try:
        dishonour = _parse_date(dishonour_date, "dishonour_date")
        if dishonour is None:
            raise ValueError("dishonour_date is required")

        timeline = limitation.cheque_bounce_timeline(
            dishonour_date=dishonour,
            notice_date=_parse_date(notice_date, "notice_date"),
            notice_served_date=_parse_date(notice_served_date, "notice_served_date"),
        )

        today = date.today()
        steps = cast(List[Dict[str, Any]], timeline["steps"])
        pending = [
            s for s in steps if s.get("status") == "pending" and s.get("deadline")
        ]
        next_step = pending[0] if pending else None

        urgency = "NONE"
        if next_step:
            deadline = date.fromisoformat(str(next_step["deadline"]))
            days_left = (deadline - today).days
            if days_left < 0:
                urgency = "MISSED"
            elif days_left <= 7:
                urgency = "CRITICAL"
            elif days_left <= 21:
                urgency = "SOON"
            else:
                urgency = "IN_TIME"
            next_step = {**next_step, "days_remaining": days_left}

        if any(s.get("status") == "MISSED" for s in steps):
            urgency = "MISSED"

        return {
            "status": "success",
            "operation": "compute_cheque_bounce_timeline",
            **timeline,
            "next_step": next_step,
            "urgency": urgency,
            "message": (
                "Section 138 has three separate clocks. The 30-day notice period is "
                "NOT extendable - state that to the user plainly. The 15-day payment "
                "window must expire before the offence is complete, so a complaint "
                "filed earlier is premature."
            ),
        }

    except Exception as e:
        logger.error(f"Error in compute_cheque_bounce_timeline: {e}")
        return {
            "status": "error",
            "operation": "compute_cheque_bounce_timeline",
            "error": str(e),
            "message": "Failed to compute the cheque dishonour timeline",
        }


def compute_deadline(
    start_date: str,
    value: int,
    unit: str = "days",
    working_days_only: bool = False,
    court: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a period to a date, respecting court closures.

    TOOL_NAME=compute_deadline
    DISPLAY_NAME=Deadline Calculator
    USECASE=Work out any procedural date - a notice period, a reply deadline, a next hearing - with court holidays taken into account
    INSTRUCTIONS=1. Give the starting date and the period, 2. Set working_days_only where the rule counts working days, 3. Read the calendar_confidence field before relying on a date close to the limit
    INPUT_DESCRIPTION=start_date (string, required): YYYY-MM-DD. value (int, required): length of the period. unit (string, optional, default "days"): "days", "months" or "years". working_days_only (bool, optional, default False): count only days the court is open. court (string, optional): whose holiday calendar to use.
    OUTPUT_DESCRIPTION=Dictionary with status, the computed deadline, whether it fell on a closure and was moved, the next working day, and the confidence of the calendar used
    EXAMPLES=compute_deadline("2026-08-02", 30), compute_deadline("2026-08-02", 3, unit="months"), compute_deadline("2026-08-02", 10, working_days_only=True)
    PREREQUISITES=None. Install a court holiday calendar at data/reference/court_holidays.json for festival and vacation accuracy.
    RELATED_TOOLS=compute_limitation for statutory limitation periods; get_court_holidays to see the calendar

    CPU-bound operation - uses def for date arithmetic.

    Args:
        start_date: The date to count from.
        value: Length of the period.
        unit: "days", "months" or "years".
        working_days_only: Whether to count only court working days.
        court: Court whose calendar governs.

    Returns:
        Dict with the computed deadline.
    """
    try:
        start = _parse_date(start_date, "start_date")
        if start is None:
            raise ValueError("start_date is required")
        if unit not in {"days", "months", "years"}:
            raise ValueError("unit must be 'days', 'months' or 'years'")
        if working_days_only and unit != "days":
            raise ValueError("working_days_only can only be used with unit='days'")
        if value < 0:
            raise ValueError("value cannot be negative")

        if working_days_only:
            deadline = holidays.add_working_days(start, value, court)
            moved_from = None
        else:
            deadline = limitation.add_period(start, value, unit)
            moved_from = None
            if holidays.is_court_closed(deadline, court):
                moved_from = deadline
                deadline = holidays.next_working_day(deadline, court)

        return {
            "status": "success",
            "operation": "compute_deadline",
            "start_date": start.isoformat(),
            "period": f"{value} {unit}",
            "working_days_only": working_days_only,
            "deadline": deadline.isoformat(),
            "moved_from": moved_from.isoformat() if moved_from else None,
            "closure_reason": (
                holidays.holiday_reason(moved_from, court) if moved_from else None
            ),
            "day_of_week": deadline.strftime("%A"),
            "calendar_confidence": holidays.calendar_confidence(deadline, court),
            "message": (
                f"Deadline: {deadline.isoformat()} ({deadline.strftime('%A')})."
                + (
                    f" Moved from {moved_from.isoformat()} under section 4 of the "
                    "Limitation Act because the court was closed."
                    if moved_from
                    else ""
                )
            ),
        }

    except Exception as e:
        logger.error(f"Error in compute_deadline: {e}")
        return {
            "status": "error",
            "operation": "compute_deadline",
            "error": str(e),
            "message": "Failed to compute deadline",
        }


def get_court_holidays(year: int, court: Optional[str] = None) -> Dict[str, Any]:
    """List the court closures known for a year.

    TOOL_NAME=get_court_holidays
    DISPLAY_NAME=Court Holiday Calendar
    USECASE=Check which days a court is closed, and whether a calendar is installed at all before trusting a working-day computation
    INSTRUCTIONS=1. Call for the relevant year, 2. If calendar_installed is false, tell the user that festival holidays and vacations are not accounted for and point them at the court's published list
    INPUT_DESCRIPTION=year (int, required): calendar year. court (string, optional): court name, defaults to the configured High Court.
    OUTPUT_DESCRIPTION=Dictionary with status, known closures with occasions, whether a published calendar is installed, which years are covered, and the install path
    EXAMPLES=get_court_holidays(2026), get_court_holidays(2026, court="Bombay High Court")
    PREREQUISITES=None
    RELATED_TOOLS=compute_deadline and compute_limitation both apply this calendar

    CPU-bound operation - uses def for local calendar inspection.

    Args:
        year: The calendar year.
        court: Court whose calendar to read.

    Returns:
        Dict with the known closures.
    """
    try:
        if not isinstance(year, int) or not (1950 <= year <= 2200):
            raise ValueError("year must be a four-digit calendar year")

        closures = holidays.known_closures(year, court)
        confidence = holidays.calendar_confidence(date(year, 1, 1), court)

        return {
            "status": "success",
            "operation": "get_court_holidays",
            "year": year,
            "closures": closures,
            "closure_count": len(closures),
            "weekends_excluded_from_list": True,
            **confidence,
            "message": (
                f"{len(closures)} known non-weekend closures in {year}."
                + (
                    ""
                    if confidence["year_covered"]
                    else " Only fixed-date national holidays are included - no "
                    "published calendar is installed for this court and year, so "
                    "festival holidays and court vacations are missing."
                )
            ),
        }

    except Exception as e:
        logger.error(f"Error in get_court_holidays: {e}")
        return {
            "status": "error",
            "operation": "get_court_holidays",
            "error": str(e),
            "message": "Failed to read the court holiday calendar",
        }


TOOLS: List[Any] = [
    compute_limitation,
    find_limitation_rule,
    list_limitation_rules,
    compute_cheque_bounce_timeline,
    compute_deadline,
    get_court_holidays,
]
