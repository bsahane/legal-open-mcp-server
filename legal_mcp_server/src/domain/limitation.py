"""Limitation computation under the Limitation Act, 1963 and special statutes.

Missing a limitation period is the most consequential and least recoverable
mistake in civil practice, so this module is deliberately conservative:

* It models a curated set of Schedule articles plus the special periods that
  displace the Schedule (section 138 NI Act, section 34 Arbitration Act,
  section 69 Consumer Protection Act, and so on).
* It applies section 12 (exclusion of the starting day and of copy time),
  section 14 (bona fide proceedings in a wrong forum), section 18
  (acknowledgment) and section 4 (expiry when the court is closed).
* Where the period depends on a fact the caller has not supplied - when the
  right to sue accrued, when performance was refused, when adverse possession
  began - it says so instead of assuming.

Nothing here is a substitute for reading the Schedule. Every result names the
article or provision relied on so the reasoning can be checked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from dateutil.relativedelta import relativedelta

ACT_LIMITATION = "Limitation Act, 1963"


@dataclass(frozen=True)
class LimitationRule:
    """One limitation period, from the Schedule or a special statute."""

    key: str
    description: str
    period_value: int
    period_unit: str  # "days", "months" or "years"
    starting_point: str
    authority: str
    source_act: str = ACT_LIMITATION
    condonable: bool = False
    condonation_note: Optional[str] = None
    caution: Optional[str] = None

    @property
    def period_label(self) -> str:
        """Human-readable period, e.g. '3 years'."""
        unit = (
            self.period_unit if self.period_value != 1 else self.period_unit.rstrip("s")
        )
        return f"{self.period_value} {unit}"

    def to_dict(self) -> Dict[str, object]:
        """Serialise for MCP tool output."""
        return {
            "key": self.key,
            "description": self.description,
            "period": self.period_label,
            "starting_point": self.starting_point,
            "authority": self.authority,
            "source_act": self.source_act,
            "condonable": self.condonable,
            "condonation_note": self.condonation_note,
            "caution": self.caution,
        }


def _rule(
    key: str,
    description: str,
    value: int,
    unit: str,
    start: str,
    authority: str,
    **kwargs: object,
) -> LimitationRule:
    return LimitationRule(
        key=key,
        description=description,
        period_value=value,
        period_unit=unit,
        starting_point=start,
        authority=authority,
        **kwargs,  # type: ignore[arg-type]
    )


#: Curated limitation rules, keyed by a stable slug.
RULES: Dict[str, LimitationRule] = {
    r.key: r
    for r in [
        # --- Contract and money claims (Schedule, Division I) ---
        _rule(
            "goods_sold",
            "Price of goods sold and delivered",
            3,
            "years",
            "the date of delivery of the goods",
            "Article 14",
        ),
        _rule(
            "work_done",
            "Money payable for work done for the defendant",
            3,
            "years",
            "the date the work was done",
            "Article 18",
        ),
        _rule(
            "money_lent",
            "Money lent",
            3,
            "years",
            "the date the loan was made",
            "Article 19",
        ),
        _rule(
            "money_lent_on_demand",
            "Money lent under an agreement that it is payable on demand",
            3,
            "years",
            "the date the loan was made",
            "Article 21",
            caution="Time runs from the loan, not from the demand.",
        ),
        _rule(
            "deposit_on_demand",
            "Money deposited under an agreement that it is payable on demand",
            3,
            "years",
            "the date the demand is made",
            "Article 22",
        ),
        _rule(
            "money_had_and_received",
            "Money had and received to the plaintiff's use",
            3,
            "years",
            "the date the money was received",
            "Article 24",
        ),
        _rule(
            "breach_of_contract",
            "Compensation for breach of any contract",
            3,
            "years",
            "the date the contract was broken, or where there are "
            "successive breaches, the date of each breach",
            "Article 55",
        ),
        _rule(
            "specific_performance",
            "Specific performance of a contract",
            3,
            "years",
            "the date fixed for performance, or if no date is fixed, "
            "the date the plaintiff had notice that performance was refused",
            "Article 54",
            caution="Which limb applies is a question of fact on the contract. "
            "If no date was fixed, the period does not begin until refusal is "
            "brought home to the plaintiff.",
        ),
        # --- Declarations, instruments, property ---
        _rule(
            "declaration",
            "Suit to obtain any other declaration",
            3,
            "years",
            "the date the right to sue first accrues",
            "Article 58",
        ),
        _rule(
            "cancel_instrument",
            "Suit to cancel or set aside an instrument or decree",
            3,
            "years",
            "the date the facts entitling the plaintiff to have the "
            "instrument cancelled become known to the plaintiff",
            "Article 59",
        ),
        _rule(
            "possession_title",
            "Possession of immovable property based on title",
            12,
            "years",
            "the date the defendant's possession becomes adverse to the plaintiff",
            "Article 65",
            caution="Adverse possession must be nec vi, nec clam, nec precario "
            "and its starting date is a question of evidence.",
        ),
        _rule(
            "possession_dispossession",
            "Possession of immovable property on dispossession",
            12,
            "years",
            "the date of dispossession",
            "Article 64",
        ),
        _rule(
            "mortgage_money",
            "Suit to enforce payment of money secured by a mortgage",
            12,
            "years",
            "the date the money sued for becomes due",
            "Article 62",
        ),
        _rule(
            "residuary",
            "Any suit for which no period is provided elsewhere",
            3,
            "years",
            "the date the right to sue accrues",
            "Article 113",
            caution="The residuary article. Check the specific articles first - "
            "using Article 113 where a specific article applies is a common error.",
        ),
        # --- Torts ---
        _rule(
            "tort_compensation",
            "Compensation for a tort not otherwise provided for",
            3,
            "years",
            "the date the right to sue accrues (usually when the damage occurs)",
            "Article 113",
        ),
        _rule(
            "malicious_prosecution",
            "Compensation for malicious prosecution",
            1,
            "years",
            "the date the plaintiff is acquitted or the prosecution "
            "is otherwise terminated",
            "Article 74",
        ),
        _rule(
            "defamation_libel",
            "Compensation for libel",
            1,
            "years",
            "the date of publication",
            "Article 75",
        ),
        _rule(
            "defamation_slander",
            "Compensation for slander",
            1,
            "years",
            "the date the words are spoken, or if special damage is the cause of "
            "action, when the damage occurs",
            "Article 76",
        ),
        # --- Appeals and applications ---
        _rule(
            "appeal_hc_decree",
            "Appeal to a High Court from a decree or order",
            90,
            "days",
            "the date of the decree or order",
            "Article 116(a)",
            condonable=True,
            condonation_note="Delay may be condoned under section 5 on sufficient "
            "cause. Time taken to obtain a certified copy is excluded under "
            "section 12(2).",
        ),
        _rule(
            "appeal_other_court",
            "Appeal to any court other than a High Court from a decree or order",
            30,
            "days",
            "the date of the decree or order",
            "Article 116(b)",
            condonable=True,
            condonation_note="Section 5 condonation available; section 12(2) copy "
            "time excluded.",
        ),
        _rule(
            "restore_dismissed_suit",
            "Application to restore a suit dismissed for default",
            30,
            "days",
            "the date of dismissal",
            "Article 122",
            condonable=True,
        ),
        _rule(
            "set_aside_ex_parte",
            "Application to set aside an ex parte decree",
            30,
            "days",
            "the date of the decree, or where the summons was not duly served, "
            "the date the applicant had knowledge of the decree",
            "Article 123",
            condonable=True,
        ),
        _rule(
            "review",
            "Application for review of judgment",
            30,
            "days",
            "the date of the decree or order",
            "Article 124",
            condonable=True,
        ),
        _rule(
            "execution",
            "Application for execution of a decree",
            12,
            "years",
            "the date the decree becomes enforceable",
            "Article 136",
            caution="Not extendable under section 5.",
        ),
        # --- Special statutes that displace the Schedule ---
        _rule(
            "ni_138_complaint",
            "Complaint for dishonour of cheque",
            1,
            "months",
            "the date on which the 15-day period after service of the statutory "
            "notice expires without payment",
            "section 142(b), Negotiable Instruments Act, 1881",
            source_act="Negotiable Instruments Act, 1881",
            condonable=True,
            condonation_note="The proviso to section 142(b) allows a complaint "
            "after the period if the complainant shows sufficient cause.",
            caution="Use compute_cheque_bounce_timeline instead of this rule "
            "directly - the notice steps must be computed first.",
        ),
        _rule(
            "ni_138_notice",
            "Statutory notice demanding payment on a dishonoured cheque",
            30,
            "days",
            "the date the drawer receives information from the bank that the "
            "cheque has been returned unpaid",
            "proviso (b) to section 138, Negotiable Instruments Act, 1881",
            source_act="Negotiable Instruments Act, 1881",
            caution="This period is NOT condonable. Missing it destroys the "
            "cause of action for that dishonour, although a fresh presentation "
            "of the cheque within its validity can create a new one.",
        ),
        _rule(
            "consumer_complaint",
            "Consumer complaint",
            2,
            "years",
            "the date on which the cause of action arises",
            "section 69, Consumer Protection Act, 2019",
            source_act="Consumer Protection Act, 2019",
            condonable=True,
            condonation_note="Section 69(2) permits a later complaint if "
            "sufficient cause is shown and reasons are recorded.",
        ),
        _rule(
            "arbitration_set_aside",
            "Application to set aside an arbitral award",
            3,
            "months",
            "the date on which the party making the application received the "
            "award, or the date a request under section 33 is disposed of",
            "section 34(3), Arbitration and Conciliation Act, 1996",
            source_act="Arbitration and Conciliation Act, 1996",
            condonable=True,
            condonation_note="A further 30 days only, on sufficient cause. The "
            "court has no power to condone beyond that; section 5 of the "
            "Limitation Act does not apply.",
            caution="This is a hard outer limit of three months and thirty days.",
        ),
        _rule(
            "rti_first_appeal",
            "First appeal under the Right to Information Act",
            30,
            "days",
            "the date of the decision, or the expiry of the period for a response",
            "section 19(1), Right to Information Act, 2005",
            source_act="Right to Information Act, 2005",
            condonable=True,
        ),
        _rule(
            "rti_second_appeal",
            "Second appeal to the Information Commission",
            90,
            "days",
            "the date on which the first appeal decision was made or "
            "should have been made",
            "section 19(3), Right to Information Act, 2005",
            source_act="Right to Information Act, 2005",
            condonable=True,
        ),
        _rule(
            "suit_against_government",
            "Suit against the Government or a public officer for an act done in "
            "official capacity",
            3,
            "years",
            "the date the right to sue accrues",
            "Article 113 with section 80 CPC",
            caution="Section 80 CPC additionally requires two months' prior "
            "written notice before the suit is instituted, and that notice period "
            "is added to, not taken out of, the limitation period.",
        ),
    ]
}


@dataclass
class LimitationResult:
    """The computed limitation position for one claim."""

    rule: LimitationRule
    start_date: date
    base_expiry: date
    adjusted_expiry: date
    exclusions: List[Dict[str, object]] = field(default_factory=list)
    reasoning: List[str] = field(default_factory=list)
    as_on: Optional[date] = None

    @property
    def days_remaining(self) -> Optional[int]:
        """Days left before expiry, negative if already expired."""
        if self.as_on is None:
            return None
        return (self.adjusted_expiry - self.as_on).days

    @property
    def expired(self) -> Optional[bool]:
        """Whether the period has run out as at ``as_on``."""
        if self.as_on is None:
            return None
        return self.as_on > self.adjusted_expiry

    def to_dict(self) -> Dict[str, object]:
        """Serialise for MCP tool output."""
        return {
            "rule": self.rule.to_dict(),
            "start_date": self.start_date.isoformat(),
            "base_expiry": self.base_expiry.isoformat(),
            "expiry_date": self.adjusted_expiry.isoformat(),
            "exclusions_applied": self.exclusions,
            "reasoning": self.reasoning,
            "as_on": self.as_on.isoformat() if self.as_on else None,
            "days_remaining": self.days_remaining,
            "expired": self.expired,
        }


def add_period(start: date, value: int, unit: str) -> date:
    """Add a limitation period to a date.

    Months and years are calendar-based, matching how Indian courts compute
    them: one month from 31 January is 28 February, not 3 March.

    Args:
        start: The date to add to.
        value: Number of units.
        unit: ``"days"``, ``"months"`` or ``"years"``.

    Returns:
        The resulting date.

    Raises:
        ValueError: If ``unit`` is not recognised.
    """
    if unit == "days":
        return start + timedelta(days=value)
    if unit == "months":
        return start + relativedelta(months=value)
    if unit == "years":
        return start + relativedelta(years=value)
    raise ValueError(f"unknown period unit: {unit}")


def compute(
    rule_key: str,
    start_date: date,
    as_on: Optional[date] = None,
    copy_application_date: Optional[date] = None,
    copy_ready_date: Optional[date] = None,
    wrong_forum_days: int = 0,
    acknowledgment_date: Optional[date] = None,
    court_closed_check: Optional[object] = None,
) -> LimitationResult:
    """Compute the limitation position for a claim.

    Args:
        rule_key: Key into :data:`RULES`.
        start_date: The date from which the period runs.
        as_on: Date to measure remaining time against; defaults to no measurement.
        copy_application_date: Date a certified copy was applied for (section 12(2)).
        copy_ready_date: Date the certified copy was ready (section 12(2)).
        wrong_forum_days: Days spent bona fide in a forum without jurisdiction
            (section 14).
        acknowledgment_date: Date of a written acknowledgment of liability
            (section 18). Must fall before the original expiry to have effect.
        court_closed_check: Optional callable taking a date and returning True if
            the court is closed that day (section 4).

    Returns:
        The computed position, with the reasoning that produced it.

    Raises:
        KeyError: If ``rule_key`` is not a known rule.
    """
    rule = RULES[rule_key]
    reasoning: List[str] = []
    exclusions: List[Dict[str, object]] = []

    # Section 12(1): the day from which the period runs is excluded.
    effective_start = start_date + timedelta(days=1)
    reasoning.append(
        f"Section 12(1): the starting day ({start_date.isoformat()}) is excluded, "
        f"so time runs from {effective_start.isoformat()}."
    )

    # Section 18: a written acknowledgment before expiry restarts the clock.
    provisional_expiry = add_period(
        effective_start, rule.period_value, rule.period_unit
    ) - timedelta(days=1)

    if acknowledgment_date is not None:
        if acknowledgment_date <= provisional_expiry:
            effective_start = acknowledgment_date + timedelta(days=1)
            exclusions.append(
                {
                    "provision": "section 18",
                    "effect": "fresh period from acknowledgment",
                    "acknowledgment_date": acknowledgment_date.isoformat(),
                }
            )
            reasoning.append(
                f"Section 18: a written acknowledgment dated "
                f"{acknowledgment_date.isoformat()} was made before the original "
                "period expired, so a fresh period of "
                f"{rule.period_label} runs from the following day."
            )
        else:
            reasoning.append(
                f"Section 18 does NOT apply: the acknowledgment dated "
                f"{acknowledgment_date.isoformat()} came after the period had "
                f"already expired on {provisional_expiry.isoformat()}. An "
                "acknowledgment cannot revive a time-barred claim."
            )

    base_expiry = add_period(
        effective_start, rule.period_value, rule.period_unit
    ) - timedelta(days=1)
    expiry = base_expiry

    # Section 12(2): exclude time taken to obtain a certified copy.
    if copy_application_date and copy_ready_date:
        if copy_ready_date < copy_application_date:
            raise ValueError("copy_ready_date cannot precede copy_application_date")
        copy_days = (copy_ready_date - copy_application_date).days
        expiry += timedelta(days=copy_days)
        exclusions.append(
            {
                "provision": "section 12(2)",
                "effect": "certified copy time excluded",
                "days": copy_days,
            }
        )
        reasoning.append(
            f"Section 12(2): {copy_days} days taken to obtain the certified copy "
            f"({copy_application_date.isoformat()} to {copy_ready_date.isoformat()}) "
            "are excluded."
        )

    # Section 14: exclude time spent bona fide before a court without jurisdiction.
    if wrong_forum_days:
        if wrong_forum_days < 0:
            raise ValueError("wrong_forum_days cannot be negative")
        expiry += timedelta(days=wrong_forum_days)
        exclusions.append(
            {
                "provision": "section 14",
                "effect": "bona fide proceeding in wrong forum excluded",
                "days": wrong_forum_days,
            }
        )
        reasoning.append(
            f"Section 14: {wrong_forum_days} days spent prosecuting the matter with "
            "due diligence and in good faith before a court unable to entertain it "
            "are excluded. The exclusion depends on proving diligence and good "
            "faith, so treat it as arguable rather than settled."
        )

    # Section 4: if the period expires on a day the court is closed, the
    # proceeding may be instituted on the next open day.
    if court_closed_check is not None:
        shifted = expiry
        guard = 0
        while court_closed_check(shifted) and guard < 60:  # type: ignore[operator]
            shifted += timedelta(days=1)
            guard += 1
        if shifted != expiry:
            reasoning.append(
                f"Section 4: the period expired on {expiry.isoformat()} when the "
                f"court was closed, so filing is competent up to "
                f"{shifted.isoformat()}, the next working day."
            )
            exclusions.append(
                {
                    "provision": "section 4",
                    "effect": "expiry moved to next working day",
                    "from": expiry.isoformat(),
                    "to": shifted.isoformat(),
                }
            )
            expiry = shifted

    reasoning.append(
        f"{rule.authority} ({rule.source_act}): {rule.period_label} from "
        f"{rule.starting_point}."
    )

    return LimitationResult(
        rule=rule,
        start_date=start_date,
        base_expiry=base_expiry,
        adjusted_expiry=expiry,
        exclusions=exclusions,
        reasoning=reasoning,
        as_on=as_on,
    )


def find_rules(description: str, limit: int = 8) -> List[LimitationRule]:
    """Find limitation rules matching a description of the claim.

    Args:
        description: Words describing the claim, e.g. "unpaid invoice" or
            "ex parte decree".
        limit: Maximum rules to return.

    Returns:
        Matching rules, best first.
    """
    terms = [t for t in description.lower().split() if len(t) > 2]
    if not terms:
        return []

    scored: List[tuple[int, LimitationRule]] = []
    for rule in RULES.values():
        haystack = f"{rule.key} {rule.description} {rule.starting_point}".lower()
        score = sum(
            2 if term in rule.description.lower() else 1
            for term in terms
            if term in haystack
        )
        if score:
            scored.append((score, rule))

    scored.sort(key=lambda pair: (-pair[0], pair[1].key))
    return [r for _, r in scored[:limit]]


def cheque_bounce_timeline(
    dishonour_date: date,
    notice_date: Optional[date] = None,
    notice_served_date: Optional[date] = None,
) -> Dict[str, object]:
    """Compute the full section 138 Negotiable Instruments Act timeline.

    The section 138 sequence has three separate clocks and the first of them is
    not condonable, which makes it the most commonly blown deadline in Indian
    practice:

    1. 30 days from the drawer learning of dishonour, to issue the demand notice
       (proviso (b) to section 138) - **not extendable**;
    2. 15 days from service of that notice for the drawer to pay
       (proviso (c) to section 138) - the offence is complete only on its expiry;
    3. 1 month from the expiry of those 15 days, to file the complaint
       (section 142(b)) - extendable on sufficient cause.

    Args:
        dishonour_date: Date the drawer received the bank's dishonour memo.
        notice_date: Date the demand notice was issued, if it has been.
        notice_served_date: Date the notice was served, if known. Service, not
            dispatch, starts the 15-day clock.

    Returns:
        Dict with each step, its deadline, and what remains outstanding.
    """
    steps: List[Dict[str, object]] = []

    notice_deadline = dishonour_date + timedelta(days=30)
    steps.append(
        {
            "step": 1,
            "action": "Issue the statutory demand notice to the drawer",
            "deadline": notice_deadline.isoformat(),
            "authority": "proviso (b) to section 138, Negotiable Instruments Act, 1881",
            "condonable": False,
            "status": "done" if notice_date else "pending",
            "actual_date": notice_date.isoformat() if notice_date else None,
            "warning": (
                "This 30-day period cannot be extended. If it lapses, the cause of "
                "action on this dishonour is lost, though re-presenting the cheque "
                "within its validity can generate a fresh one."
            ),
        }
    )

    if notice_date and notice_date > notice_deadline:
        steps[0]["status"] = "MISSED"
        steps[0]["warning"] = (
            f"The notice was issued on {notice_date.isoformat()}, after the "
            f"non-extendable deadline of {notice_deadline.isoformat()}. The "
            "complaint on this dishonour is not maintainable."
        )

    service_date = notice_served_date or notice_date
    if service_date is None:
        return {
            "dishonour_date": dishonour_date.isoformat(),
            "steps": steps,
            "complete": False,
            "next_action": "Issue the demand notice",
            "next_deadline": notice_deadline.isoformat(),
            "note": (
                "The remaining deadlines cannot be computed until the notice is "
                "issued and served. Service, not dispatch, starts the 15-day clock."
            ),
        }

    payment_deadline = service_date + timedelta(days=15)
    steps.append(
        {
            "step": 2,
            "action": "Wait for the drawer's 15 days to pay to expire",
            "deadline": payment_deadline.isoformat(),
            "authority": "proviso (c) to section 138, Negotiable Instruments Act, 1881",
            "condonable": False,
            "status": "pending",
            "warning": (
                "The offence is complete only when these 15 days expire without "
                "payment. A complaint filed before that is premature and liable to "
                "be dismissed."
            ),
            "service_basis": (
                "computed from service"
                if notice_served_date
                else "computed from the notice date because the service date was not "
                "supplied - confirm actual service, as it is service that counts"
            ),
        }
    )

    cause_of_action_date = payment_deadline + timedelta(days=1)
    complaint_deadline = (
        cause_of_action_date + relativedelta(months=1) - timedelta(days=1)
    )
    steps.append(
        {
            "step": 3,
            "action": "File the complaint before the competent Magistrate",
            "window_opens": cause_of_action_date.isoformat(),
            "deadline": complaint_deadline.isoformat(),
            "authority": "section 142(b), Negotiable Instruments Act, 1881",
            "condonable": True,
            "status": "pending",
            "warning": (
                "Delay may be condoned under the proviso to section 142(b) on "
                "sufficient cause, but do not plan around condonation."
            ),
        }
    )

    return {
        "dishonour_date": dishonour_date.isoformat(),
        "notice_date": notice_date.isoformat() if notice_date else None,
        "notice_service_date": service_date.isoformat(),
        "steps": steps,
        "cause_of_action_date": cause_of_action_date.isoformat(),
        "complaint_deadline": complaint_deadline.isoformat(),
        "complete": True,
        "jurisdiction_note": (
            "Section 142(2)(a) fixes territorial jurisdiction at the court within "
            "whose local limits the payee's bank branch, where the cheque was "
            "delivered for collection, is situated."
        ),
    }
