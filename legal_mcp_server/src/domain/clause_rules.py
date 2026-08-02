"""Contract clause classification and India-specific risk rules.

Two pieces of pure logic:

* a **taxonomy** that labels the clauses of a contract, so a document can be
  navigated by what its provisions do rather than by page number;
* a set of **risk rules** grounded in Indian law - section 27 of the Contract
  Act on restraint of trade, section 28 on ousting jurisdiction, the stamping
  requirement that has sunk more arbitration references than any drafting
  error - each of which cites the provision it rests on.

These rules flag patterns worth a human look. They are a checklist, not an
opinion: a flag means "read this clause", not "this clause is void".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Severity(str, Enum):
    """How much attention a flagged clause warrants."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class ClauseType:
    """One category in the clause taxonomy."""

    key: str
    label: str
    patterns: List[str]
    expected: bool = False  # whether a commercial contract should normally have it


CLAUSE_TAXONOMY: List[ClauseType] = [
    ClauseType(
        "parties",
        "Parties and recitals",
        [r"\bbetween\b.*\band\b", r"\bwhereas\b", r"\brecitals?\b"],
        True,
    ),
    ClauseType(
        "definitions",
        "Definitions",
        [r"\bdefinitions?\b", r"shall mean", r"unless the context"],
    ),
    ClauseType(
        "term",
        "Term and duration",
        [
            r"\bterm of this agreement\b",
            r"\bcommencement date\b",
            r"\bshall remain in (force|effect)\b",
            r"\brenewal\b",
        ],
        True,
    ),
    ClauseType(
        "payment",
        "Payment and consideration",
        [
            r"\bconsideration\b",
            r"\bpayment terms?\b",
            r"\binvoice\b",
            r"\bfees? payable\b",
            r"\binterest on delayed\b",
        ],
        True,
    ),
    ClauseType(
        "obligations",
        "Obligations and scope",
        [r"\bscope of (work|services)\b", r"\bdeliverables?\b", r"\bobligations of\b"],
        True,
    ),
    ClauseType(
        "representations",
        "Representations and warranties",
        [r"\brepresents? and warrants?\b", r"\bwarrant(y|ies)\b"],
    ),
    ClauseType(
        "indemnity",
        "Indemnity",
        [r"\bindemnif(y|ies|ication)\b", r"\bhold harmless\b", r"\bdefend and hold\b"],
    ),
    ClauseType(
        "liability",
        "Limitation of liability",
        [
            r"\blimitation of liability\b",
            r"\baggregate liability\b",
            r"\bconsequential (loss|damages?)\b",
            r"\bin no event shall\b",
        ],
    ),
    ClauseType(
        "termination",
        "Termination",
        [
            r"\btermination\b",
            r"\bterminate this agreement\b",
            r"\bnotice period\b",
            r"\bmaterial breach\b",
        ],
        True,
    ),
    ClauseType(
        "confidentiality",
        "Confidentiality",
        [
            r"\bconfidential(ity)? information\b",
            r"\bnon.?disclosure\b",
            r"\bshall not disclose\b",
        ],
    ),
    ClauseType(
        "non_compete",
        "Non-compete and restraint",
        [
            r"\bnon.?compet(e|ition)\b",
            r"\bshall not.{0,40}(compete|engage in "
            r"any business)\b",
            r"\brestrictive covenant\b",
            r"\bnon.?solicit(ation)?\b",
        ],
    ),
    ClauseType(
        "ip",
        "Intellectual property",
        [
            r"\bintellectual property\b",
            r"\bcopyright\b",
            r"\bwork for hire\b",
            r"\bassigns? all right(s)?, title\b",
        ],
    ),
    ClauseType(
        "force_majeure",
        "Force majeure",
        [r"\bforce majeure\b", r"\bact of god\b", r"\bbeyond the reasonable control\b"],
    ),
    ClauseType(
        "dispute_resolution",
        "Dispute resolution",
        [
            r"\bdispute resolution\b",
            r"\bmediation\b",
            r"\bnegotiation in good "
            r"faith\b",
        ],
        True,
    ),
    ClauseType(
        "arbitration",
        "Arbitration",
        [
            r"\barbitrat(ion|or)\b",
            r"\barbitral tribunal\b",
            r"\bArbitration and Conciliation Act\b",
        ],
    ),
    ClauseType(
        "governing_law",
        "Governing law",
        [
            r"\bgoverning law\b",
            r"\bgoverned by the laws? of\b",
            r"\bconstrued in accordance with\b",
        ],
        True,
    ),
    ClauseType(
        "jurisdiction",
        "Jurisdiction",
        [
            r"\bexclusive jurisdiction\b",
            r"\bcourts? at [A-Z]\w+ shall\b",
            r"\bsubject to the jurisdiction\b",
        ],
        True,
    ),
    ClauseType(
        "notices",
        "Notices",
        [
            r"\bnotices? under this agreement\b",
            r"\bshall be sent to\b",
            r"\bregistered post\b",
            r"\backnowledgement due\b",
        ],
        True,
    ),
    ClauseType(
        "assignment",
        "Assignment",
        [r"\bassign(ment)? of this agreement\b", r"\bshall not assign\b"],
    ),
    ClauseType(
        "entire_agreement",
        "Entire agreement",
        [r"\bentire agreement\b", r"\bsupersedes all (prior|previous)\b"],
    ),
    ClauseType(
        "severability",
        "Severability",
        [r"\bseverab(le|ility)\b", r"\bremain in full force and effect\b"],
    ),
    ClauseType(
        "stamp_registration",
        "Stamp duty and registration",
        [r"\bstamp duty\b", r"\bregistration charges?\b", r"\bstamped\b"],
    ),
]


@dataclass
class RiskFlag:
    """One risk identified in a document."""

    rule: str
    severity: Severity
    title: str
    explanation: str
    authority: Optional[str]
    excerpt: str
    position: int

    def to_dict(self) -> Dict[str, object]:
        """Serialise for MCP tool output."""
        return {
            "rule": self.rule,
            "severity": self.severity.value,
            "title": self.title,
            "explanation": self.explanation,
            "authority": self.authority,
            "excerpt": self.excerpt,
            "position": self.position,
        }


@dataclass
class RiskRule:
    """A pattern whose presence (or absence) in a contract is worth flagging."""

    key: str
    severity: Severity
    title: str
    explanation: str
    pattern: str
    authority: Optional[str] = None
    negate: bool = False  # flag when the pattern is ABSENT
    requires: Optional[str] = None  # only apply when this pattern is present


RISK_RULES: List[RiskRule] = [
    RiskRule(
        key="post_termination_non_compete",
        severity=Severity.HIGH,
        title="Post-termination non-compete",
        explanation=(
            "A covenant restraining a party from competing after the agreement "
            "ends is, in India, generally void under section 27 of the Contract "
            "Act. Unlike English law, there is no reasonableness test that saves "
            "it; the only statutory exception is the sale of goodwill. A "
            "restraint operating during the term is a different matter and may "
            "well be enforceable."
        ),
        pattern=(
            r"(?:after|following|upon|post)[^.]{0,60}(?:termination|expiry|"
            r"cessation)[^.]{0,200}?(?:not\s+(?:directly\s+or\s+indirectly\s+)?"
            r"(?:compete|engage|carry on|be employed)|non.?compet)"
        ),
        authority="section 27, Indian Contract Act, 1872",
    ),
    RiskRule(
        key="non_compete_generic",
        severity=Severity.MEDIUM,
        title="Restraint of trade clause",
        explanation=(
            "A restraint-of-trade covenant is present. Check whether it operates "
            "during the term (potentially enforceable) or after it (generally "
            "void under section 27), and whether it is tied to a sale of goodwill."
        ),
        pattern=r"\bnon.?compet(?:e|ition)\b|\brestraint of trade\b",
        authority="section 27, Indian Contract Act, 1872",
    ),
    RiskRule(
        key="uncapped_liability",
        severity=Severity.HIGH,
        title="No cap on liability",
        explanation=(
            "The agreement allocates liability but does not appear to cap it. "
            "Uncapped exposure on a fixed-fee engagement is rarely intended. "
            "Check whether an aggregate cap should be negotiated."
        ),
        pattern=r"\b(?:aggregate|total|maximum)\s+liability\b|\bliability\s+(?:shall|"
        r"is)\s+(?:be\s+)?(?:limited|capped)\b",
        negate=True,
        requires=r"\bindemnif|liabilit",
    ),
    RiskRule(
        key="unlimited_indemnity",
        severity=Severity.HIGH,
        title="Indemnity without limit or carve-out",
        explanation=(
            "An indemnity that is not qualified by a cap, a notice-and-conduct "
            "procedure, or an exclusion for the indemnified party's own "
            "negligence transfers open-ended risk. Check what it actually covers."
        ),
        pattern=r"\bindemnif(?:y|ies|ication)\b[^.]{0,300}\ball\b[^.]{0,120}"
        r"\b(?:claims?|losses|damages?|liabilit)",
    ),
    RiskRule(
        key="one_sided_indemnity",
        severity=Severity.MEDIUM,
        title="Indemnity may run one way only",
        explanation=(
            "An indemnity appears without a reciprocal obligation. That is normal "
            "in some contracts and unacceptable in others - confirm it matches "
            "the commercial bargain."
        ),
        pattern=r"\bmutual(?:ly)?\s+indemnif|\beach\s+party\s+shall\s+indemnif",
        negate=True,
        requires=r"\bindemnif",
    ),
    RiskRule(
        key="auto_renewal",
        severity=Severity.MEDIUM,
        title="Automatic renewal",
        explanation=(
            "The agreement renews itself unless notice is given. Diarise the "
            "notice deadline: these clauses are missed far more often than they "
            "are negotiated."
        ),
        pattern=r"\bautomatic(?:ally)?\s+renew|\brenewed?\s+for\s+(?:successive|"
        r"further)\b|\bunless\s+(?:either\s+)?party\s+gives?\s+notice[^.]{0,80}"
        r"\brenew",
    ),
    RiskRule(
        key="arbitration_seat_unclear",
        severity=Severity.HIGH,
        title="Arbitration clause without a clear seat",
        explanation=(
            "The clause provides for arbitration but does not identify the seat, "
            "or names only a 'venue'. The seat determines which court supervises "
            "the arbitration and hears a section 34 challenge; venue alone does "
            "not settle it. This ambiguity is litigated constantly - fix it in "
            "drafting."
        ),
        pattern=r"\bseat\s+of\s+(?:the\s+)?arbitration\b",
        negate=True,
        requires=r"\barbitrat",
        authority="Arbitration and Conciliation Act, 1996",
    ),
    RiskRule(
        key="arbitration_no_appointment",
        severity=Severity.MEDIUM,
        title="Arbitration clause without an appointment mechanism",
        explanation=(
            "No procedure is specified for appointing the arbitrator, so a "
            "section 11 application to the High Court will be needed if the "
            "parties disagree. That is months of delay avoidable by drafting."
        ),
        pattern=r"\bsole\s+arbitrator\b|\bappoint(?:ed|ment)\b[^.]{0,80}\barbitrat",
        negate=True,
        requires=r"\barbitrat",
        authority="section 11, Arbitration and Conciliation Act, 1996",
    ),
    RiskRule(
        key="stamping_not_addressed",
        severity=Severity.MEDIUM,
        title="Stamp duty not addressed",
        explanation=(
            "The agreement does not say who bears stamp duty or confirm the "
            "instrument is stamped. An unstamped or insufficiently stamped "
            "instrument is inadmissible in evidence until duty and penalty are "
            "paid, and this has repeatedly derailed arbitration references."
        ),
        pattern=r"\bstamp(?:ed|\s+duty)\b",
        negate=True,
        requires=r"\bagreement\b",
        authority="Indian Stamp Act, 1899 and the Maharashtra Stamp Act, 1958",
    ),
    RiskRule(
        key="exclusive_jurisdiction",
        severity=Severity.LOW,
        title="Exclusive jurisdiction clause",
        explanation=(
            "An exclusive-jurisdiction clause is valid under section 28 of the "
            "Contract Act provided the chosen court is one that would otherwise "
            "have jurisdiction; parties cannot confer jurisdiction on a court "
            "that has none. Confirm the nominated court has a genuine connection "
            "to the cause of action."
        ),
        pattern=r"\bexclusive\s+jurisdiction\b|\bcourts?\s+at\s+\w+\s+(?:alone\s+)?"
        r"shall\s+have\s+jurisdiction\b",
        authority="section 28, Indian Contract Act, 1872",
    ),
    RiskRule(
        key="no_governing_law",
        severity=Severity.MEDIUM,
        title="No governing law clause",
        explanation=(
            "The agreement does not state which law governs it. For a purely "
            "domestic contract this is survivable, but it invites a preliminary "
            "fight in any cross-border dispute."
        ),
        pattern=r"\bgovern(?:ing|ed)\s+(?:by\s+)?(?:the\s+)?laws?\b",
        negate=True,
        requires=r"\bagreement\b",
    ),
    RiskRule(
        key="no_termination_clause",
        severity=Severity.MEDIUM,
        title="No termination clause",
        explanation=(
            "No express right to terminate is provided. Without one the parties "
            "are left to common-law repudiation, which is a far worse position "
            "than a contractual exit on notice."
        ),
        pattern=r"\bterminat",
        negate=True,
        requires=r"\bagreement\b",
    ),
    RiskRule(
        key="no_notice_clause",
        severity=Severity.LOW,
        title="No notices clause",
        explanation=(
            "No address or method for service of notices is specified, which "
            "creates an argument about whether any notice was validly given - "
            "exactly the argument you do not want when terminating."
        ),
        pattern=r"\bnotices?\b[^.]{0,100}\b(?:address|sent|served|delivered)\b",
        negate=True,
        requires=r"\bagreement\b",
    ),
    RiskRule(
        key="penalty_language",
        severity=Severity.LOW,
        title="Penalty framed as liquidated damages",
        explanation=(
            "Under section 74 of the Contract Act a named sum is a ceiling, and "
            "the court awards reasonable compensation up to it whether or not "
            "loss is proved. Indian law does not enforce a penalty at face value "
            "simply because it is labelled liquidated damages."
        ),
        pattern=r"\bliquidated damages?\b|\bpenalty\s+of\s+(?:Rs|INR|₹)",
        authority="section 74, Indian Contract Act, 1872",
    ),
    RiskRule(
        key="unilateral_variation",
        severity=Severity.MEDIUM,
        title="Unilateral variation right",
        explanation=(
            "One party can change the terms without the other's consent. Check "
            "the scope: an unfettered right to vary core terms may be "
            "unconscionable and, in a consumer contract, an unfair term under "
            "the Consumer Protection Act, 2019."
        ),
        pattern=r"\b(?:may|reserves? the right to)\s+(?:at any time\s+)?"
        r"(?:amend|modify|vary|change)\s+(?:these|the|this)\s+"
        r"(?:terms|agreement|conditions)\b[^.]{0,80}"
        r"(?:without (?:prior )?notice|at its (?:sole )?discretion)",
    ),
]


def classify_clauses(text: str) -> Dict[str, List[Tuple[int, str]]]:
    """Locate clauses of each taxonomy type within a document.

    Args:
        text: The document text.

    Returns:
        Mapping of clause key to a list of (position, excerpt) matches.
    """
    found: Dict[str, List[Tuple[int, str]]] = {}
    for clause in CLAUSE_TAXONOMY:
        hits: List[Tuple[int, str]] = []
        for pattern in clause.patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                start = max(0, match.start() - 100)
                end = min(len(text), match.end() + 200)
                hits.append((match.start(), " ".join(text[start:end].split())))
                if len(hits) >= 5:
                    break
            if len(hits) >= 5:
                break
        if hits:
            found[clause.key] = hits
    return found


def missing_expected_clauses(text: str) -> List[ClauseType]:
    """Clauses a commercial contract normally has but this document lacks."""
    present = set(classify_clauses(text))
    return [c for c in CLAUSE_TAXONOMY if c.expected and c.key not in present]


def assess_risks(text: str) -> List[RiskFlag]:
    """Apply every risk rule to a document.

    Args:
        text: The document text.

    Returns:
        Flags ordered by severity, then by position in the document.
    """
    flags: List[RiskFlag] = []

    for rule in RISK_RULES:
        if rule.requires and not re.search(rule.requires, text, re.IGNORECASE):
            continue

        match = re.search(rule.pattern, text, re.IGNORECASE | re.DOTALL)

        if rule.negate:
            if match is None:
                flags.append(
                    RiskFlag(
                        rule=rule.key,
                        severity=rule.severity,
                        title=rule.title,
                        explanation=rule.explanation,
                        authority=rule.authority,
                        excerpt="(not present in the document)",
                        position=-1,
                    )
                )
            continue

        if match is not None:
            start = max(0, match.start() - 80)
            end = min(len(text), match.end() + 160)
            flags.append(
                RiskFlag(
                    rule=rule.key,
                    severity=rule.severity,
                    title=rule.title,
                    explanation=rule.explanation,
                    authority=rule.authority,
                    excerpt=" ".join(text[start:end].split()),
                    position=match.start(),
                )
            )

    order = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2, Severity.INFO: 3}
    flags.sort(key=lambda f: (order[f.severity], f.position))
    return flags
