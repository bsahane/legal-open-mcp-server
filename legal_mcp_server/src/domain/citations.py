"""Parsing and normalisation of Indian legal citations.

Pure logic, no I/O. Two jobs:

1. Pull citations out of free text, so a draft or memo can be swept for every
   authority it relies on.
2. Normalise them into a canonical form, so the same authority written three
   different ways resolves to one lookup.

Formats handled
---------------
Reported case citations
    ``(2019) 5 SCC 266``, ``AIR 1973 SC 1461``, ``2021 SCC OnLine Bom 123``,
    ``(1998) 2 Bom CR 461``, ``1997 (3) ALL MR 200``
Neutral citations
    ``2023 INSC 456``, ``2024:BHC-AS:12345``, ``2022 SCC OnLine SC 1234``
Statutory references
    ``Section 138 of the Negotiable Instruments Act, 1881``,
    ``s. 420 IPC``, ``Art. 21 of the Constitution``, ``Order VII Rule 11 CPC``
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class CitationKind(str, Enum):
    """What sort of authority a citation points at."""

    CASE = "case"
    STATUTE = "statute"
    CONSTITUTION = "constitution"


# Reporter abbreviations seen in Indian practice, mapped to a canonical form.
REPORTERS: Dict[str, str] = {
    "scc": "SCC",
    "air": "AIR",
    "scr": "SCR",
    "sccrimr": "SCC (Cri)",
    "scc online": "SCC OnLine",
    "scconline": "SCC OnLine",
    "bomcr": "Bom CR",
    "bom cr": "Bom CR",
    "allmr": "ALL MR",
    "all mr": "ALL MR",
    "mhlj": "Mh LJ",
    "mh lj": "Mh LJ",
    "bomlr": "Bom LR",
    "delhi law times": "DLT",
    "dlt": "DLT",
    "klj": "KLJ",
    "crilj": "Cri LJ",
    "cri lj": "Cri LJ",
    "itr": "ITR",
    "comp cas": "Comp Cas",
    "cpj": "CPJ",
    "insc": "INSC",
    "supreme": "SCC",
}

# Statutes referred to by initials often enough to be worth expanding, so that
# "s. 420 IPC" and "section 420 of the Indian Penal Code" reconcile.
STATUTE_ABBREVIATIONS: Dict[str, str] = {
    "ipc": "Indian Penal Code, 1860",
    "bns": "Bharatiya Nyaya Sanhita, 2023",
    "crpc": "Code of Criminal Procedure, 1973",
    "cr.p.c": "Code of Criminal Procedure, 1973",
    "crpc.": "Code of Criminal Procedure, 1973",
    "bnss": "Bharatiya Nagarik Suraksha Sanhita, 2023",
    "evidence act": "Indian Evidence Act, 1872",
    "bsa": "Bharatiya Sakshya Adhiniyam, 2023",
    "cpc": "Code of Civil Procedure, 1908",
    "ni act": "Negotiable Instruments Act, 1881",
    "niact": "Negotiable Instruments Act, 1881",
    "ica": "Indian Contract Act, 1872",
    "contract act": "Indian Contract Act, 1872",
    "tpa": "Transfer of Property Act, 1882",
    "tp act": "Transfer of Property Act, 1882",
    "sra": "Specific Relief Act, 1963",
    "it act": "Information Technology Act, 2000",
    "arbitration act": "Arbitration and Conciliation Act, 1996",
    "a&c act": "Arbitration and Conciliation Act, 1996",
    "cpa": "Consumer Protection Act, 2019",
    "limitation act": "Limitation Act, 1963",
    "companies act": "Companies Act, 2013",
    "ibc": "Insolvency and Bankruptcy Code, 2016",
    "rera": "Real Estate (Regulation and Development) Act, 2016",
    "hma": "Hindu Marriage Act, 1955",
    "dv act": "Protection of Women from Domestic Violence Act, 2005",
    "mv act": "Motor Vehicles Act, 1988",
    "posh act": "Sexual Harassment of Women at Workplace "
    "(Prevention, Prohibition and Redressal) Act, 2013",
}


@dataclass
class Citation:
    """One citation located in a body of text."""

    raw: str
    kind: CitationKind
    normalized: str
    year: Optional[int] = None
    reporter: Optional[str] = None
    volume: Optional[str] = None
    page: Optional[str] = None
    case_name: Optional[str] = None
    section: Optional[str] = None
    statute: Optional[str] = None
    position: int = 0

    def to_dict(self) -> Dict[str, object]:
        """Serialise for MCP tool output."""
        return {
            "raw": self.raw,
            "kind": self.kind.value,
            "normalized": self.normalized,
            "year": self.year,
            "reporter": self.reporter,
            "volume": self.volume,
            "page": self.page,
            "case_name": self.case_name,
            "section": self.section,
            "statute": self.statute,
            "position": self.position,
        }

    def search_query(self) -> str:
        """The best query string for resolving this citation against a source."""
        if self.kind is CitationKind.CASE:
            if self.case_name:
                return f"{self.case_name} {self.normalized}"
            return self.normalized
        return f"{self.section} {self.statute}" if self.statute else self.normalized


# (2019) 5 SCC 266  |  (1998) 2 Bom CR 461  |  [2024] 10 S.C.R. 108
# Square brackets are the official Supreme Court Reports form used by the
# e-SCR portal and by the open judgment dataset, so both bracket styles match.
_RE_BRACKETED_YEAR = re.compile(
    r"[\(\[](?P<year>1[89]\d{2}|20\d{2})[\)\]]\s*(?P<volume>\d{1,3})?\s*"
    r"(?P<reporter>[A-Z][A-Za-z.\s()]{1,20}?)\s+(?P<page>\d{1,5})\b"
)

# 2024INSC735 - the compact neutral citation the Supreme Court stamps on
# judgments and the open dataset stores in its nc_display field.
_RE_NEUTRAL_COMPACT = re.compile(
    r"\b(?P<year>20\d{2})\s*(?P<court>INSC)\s*(?P<number>\d{1,6})\b",
    re.IGNORECASE,
)

# AIR 1973 SC 1461  |  2021 SCC OnLine Bom 123  |  2023 INSC 456
_RE_LEADING_REPORTER = re.compile(
    r"\b(?P<reporter>AIR|SCC OnLine|SCC|SCR|INSC|Cri\s?LJ|Mh\s?LJ|ALL\s?MR|DLT|ITR)\s+"
    r"(?P<year>1[89]\d{2}|20\d{2})\s+(?P<court>[A-Z][A-Za-z]{0,8})?\s*(?P<page>\d{1,5})\b"
)

# 1997 (3) ALL MR 200  |  2011 (4) Mh LJ 88
_RE_YEAR_FIRST = re.compile(
    r"\b(?P<year>1[89]\d{2}|20\d{2})\s*\((?P<volume>\d{1,3})\)\s*"
    r"(?P<reporter>[A-Z][A-Za-z.\s]{1,15}?)\s+(?P<page>\d{1,5})\b"
)

# 2021 SCC OnLine Bom 123  |  2023 INSC 456  |  2019 SCC OnLine SC 1234
_RE_YEAR_REPORTER = re.compile(
    r"\b(?P<year>1[89]\d{2}|20\d{2})\s+"
    r"(?P<reporter>SCC\s+OnLine|SCC|AIR|INSC|SCR|Cri\s?LJ|Mh\s?LJ|ALL\s?MR|DLT|ITR)\s+"
    r"(?P<court>[A-Z][A-Za-z]{0,8})?\s*(?P<page>\d{1,5})\b"
)

# 2024:BHC-AS:12345  |  2023:DHC:1234
_RE_NEUTRAL_COLON = re.compile(
    r"\b(?P<year>20\d{2}):(?P<court>[A-Z]{2,8}(?:-[A-Z]{2,4})?):(?P<number>\d{1,7})"
    r"(?::(?P<suffix>\d{1,4}))?\b"
)

# Section 138 of the Negotiable Instruments Act, 1881  |  s. 420 IPC
_RE_SECTION = re.compile(
    r"\b(?:[Ss]ec(?:tion|\.)?|[Ss]\.)\s*(?P<section>\d{1,4}[A-Za-z]{0,3}"
    r"(?:\s*\(\s*\w{1,3}\s*\))*)\s*"
    r"(?:of\s+the\s+|of\s+|,\s*|\s+)?"
    r"(?P<statute>(?:the\s+)?[A-Z][A-Za-z&.,'()\- ]{2,80}?"
    r"(?:Act|Code|Sanhita|Adhiniyam|Constitution)"
    r"(?:\s*,?\s*(?:1[89]\d{2}|20\d{2}))?|[A-Z][A-Za-z.&]{1,8})\b"
)

# Article 21 of the Constitution  |  Art. 226
_RE_ARTICLE = re.compile(
    r"\b(?:[Aa]rt(?:icle|\.)?)\s*(?P<article>\d{1,3}[A-Za-z]{0,2}"
    r"(?:\s*\(\s*\w{1,3}\s*\))*)"
)

# Order VII Rule 11 CPC
_RE_ORDER_RULE = re.compile(
    r"\bOrder\s+(?P<order>[IVXLC]{1,6}|\d{1,3})\s*,?\s*"
    r"Rule\s+(?P<rule>\d{1,3}[A-Za-z]?)\s*"
    r"(?:of\s+the\s+)?(?P<statute>CPC|Code of Civil Procedure[^.,;]{0,12})?"
)

# "Ramesh Kumar v. State of Maharashtra" preceding a citation.
_RE_CASE_NAME = re.compile(
    r"(?P<name>(?:[A-Z][\w&.'\-]*\s+){0,6}[A-Z][\w&.'\-]*)\s+"
    r"(?:v\.?|vs\.?|versus)\s+"
    r"(?P<respondent>(?:[A-Z][\w&.'\-]*\s+){0,6}[A-Z][\w&.'\-]*)",
    re.IGNORECASE,
)


def _canonical_reporter(raw: str) -> str:
    """Map a reporter abbreviation to its canonical spelling."""
    key = " ".join(raw.replace(".", "").split()).lower()
    return REPORTERS.get(key, " ".join(raw.split()).strip(" .,"))


def _expand_statute(raw: str) -> str:
    """Expand a statute abbreviation to its full name where recognised."""
    cleaned = raw.strip().strip(".,")
    cleaned = re.sub(r"^the\s+", "", cleaned, flags=re.IGNORECASE)
    key = cleaned.replace(".", "").lower().strip()
    if key in STATUTE_ABBREVIATIONS:
        return STATUTE_ABBREVIATIONS[key]
    return cleaned


# Words that routinely precede a case name in prose and are not part of it.
_CASE_NAME_LEAD_INS = {
    "in",
    "see",
    "cf",
    "but",
    "and",
    "the",
    "per",
    "also",
    "citing",
    "following",
    "followed",
    "applied",
    "held",
    "whereas",
    "compare",
    "relying",
    "on",
    "to",
    "of",
}


def _trim_lead_ins(name: str) -> str:
    """Strip narrative words that the party-name pattern swept up.

    ``"In Dashrath Rupsingh Rathod"`` should yield ``"Dashrath Rupsingh
    Rathod"``, but ``"In re Vinay Chandra Mishra"`` must keep its ``In re``.
    """
    words = name.split()
    while len(words) > 2 and words[0].lower().strip(".,") in _CASE_NAME_LEAD_INS:
        if words[0].lower() == "in" and words[1].lower().strip(".,") == "re":
            break
        words = words[1:]
    return " ".join(words)


def _nearest_case_name(text: str, position: int, window: int = 160) -> Optional[str]:
    """Find the party names immediately preceding a citation, if any."""
    start = max(0, position - window)
    preceding = text[start:position]
    matches = list(_RE_CASE_NAME.finditer(preceding))
    if not matches:
        return None
    match = matches[-1]
    # Only treat it as this citation's case name if it is genuinely adjacent.
    if position - (start + match.end()) > 30:
        return None
    appellant = _trim_lead_ins(match.group("name"))
    return " ".join(f"{appellant} v. {match.group('respondent')}".split())


def extract_case_citations(text: str) -> List[Citation]:
    """Extract reported and neutral case citations from text.

    Args:
        text: Any prose - a memo, a draft, a model's answer.

    Returns:
        Citations in order of appearance, de-duplicated by normalised form.
    """
    found: List[Citation] = []
    seen: set[str] = set()

    def add(citation: Citation) -> None:
        if citation.normalized.lower() in seen:
            return
        seen.add(citation.normalized.lower())
        found.append(citation)

    for match in _RE_BRACKETED_YEAR.finditer(text):
        reporter = _canonical_reporter(match.group("reporter"))
        volume = match.group("volume")
        year = int(match.group("year"))
        page = match.group("page")
        normalized = f"({year}) {volume + ' ' if volume else ''}{reporter} {page}"
        add(
            Citation(
                raw=match.group(0).strip(),
                kind=CitationKind.CASE,
                normalized=normalized,
                year=year,
                reporter=reporter,
                volume=volume,
                page=page,
                case_name=_nearest_case_name(text, match.start()),
                position=match.start(),
            )
        )

    for match in _RE_YEAR_FIRST.finditer(text):
        reporter = _canonical_reporter(match.group("reporter"))
        year = int(match.group("year"))
        volume = match.group("volume")
        page = match.group("page")
        add(
            Citation(
                raw=match.group(0).strip(),
                kind=CitationKind.CASE,
                normalized=f"{year} ({volume}) {reporter} {page}",
                year=year,
                reporter=reporter,
                volume=volume,
                page=page,
                case_name=_nearest_case_name(text, match.start()),
                position=match.start(),
            )
        )

    for match in _RE_YEAR_REPORTER.finditer(text):
        reporter = _canonical_reporter(match.group("reporter"))
        year = int(match.group("year"))
        court = (match.group("court") or "").strip()
        page = match.group("page")
        normalized = f"{year} {reporter} {court + ' ' if court else ''}{page}".strip()
        add(
            Citation(
                raw=match.group(0).strip(),
                kind=CitationKind.CASE,
                normalized=normalized,
                year=year,
                reporter=reporter,
                page=page,
                case_name=_nearest_case_name(text, match.start()),
                position=match.start(),
            )
        )

    for match in _RE_LEADING_REPORTER.finditer(text):
        reporter = _canonical_reporter(match.group("reporter"))
        year = int(match.group("year"))
        court = (match.group("court") or "").strip()
        page = match.group("page")
        normalized = f"{reporter} {year} {court + ' ' if court else ''}{page}".strip()
        add(
            Citation(
                raw=match.group(0).strip(),
                kind=CitationKind.CASE,
                normalized=normalized,
                year=year,
                reporter=reporter,
                page=page,
                case_name=_nearest_case_name(text, match.start()),
                position=match.start(),
            )
        )

    for match in _RE_NEUTRAL_COLON.finditer(text):
        year = int(match.group("year"))
        court = match.group("court")
        number = match.group("number")
        suffix = match.group("suffix")
        normalized = f"{year}:{court}:{number}" + (f":{suffix}" if suffix else "")
        add(
            Citation(
                raw=match.group(0).strip(),
                kind=CitationKind.CASE,
                normalized=normalized,
                year=year,
                reporter=f"{court} (neutral)",
                page=number,
                case_name=_nearest_case_name(text, match.start()),
                position=match.start(),
            )
        )

    for match in _RE_NEUTRAL_COMPACT.finditer(text):
        year = int(match.group("year"))
        court = match.group("court").upper()
        number = match.group("number")
        add(
            Citation(
                raw=match.group(0).strip(),
                kind=CitationKind.CASE,
                normalized=f"{year}{court}{number}",
                year=year,
                reporter=f"{court} (neutral)",
                page=number,
                case_name=_nearest_case_name(text, match.start()),
                position=match.start(),
            )
        )

    return sorted(found, key=lambda c: c.position)


def extract_statutory_citations(text: str) -> List[Citation]:
    """Extract section, article and order/rule references from text.

    Args:
        text: Any prose containing statutory references.

    Returns:
        Citations in order of appearance, de-duplicated by normalised form.
    """
    found: List[Citation] = []
    seen: set[str] = set()

    def add(citation: Citation) -> None:
        if citation.normalized.lower() in seen:
            return
        seen.add(citation.normalized.lower())
        found.append(citation)

    for match in _RE_SECTION.finditer(text):
        section = " ".join(match.group("section").split())
        statute = _expand_statute(match.group("statute"))
        add(
            Citation(
                raw=match.group(0).strip(),
                kind=CitationKind.STATUTE,
                normalized=f"Section {section}, {statute}",
                section=section,
                statute=statute,
                position=match.start(),
            )
        )

    for match in _RE_ORDER_RULE.finditer(text):
        order = match.group("order")
        rule = match.group("rule")
        statute = _expand_statute(match.group("statute") or "CPC")
        add(
            Citation(
                raw=match.group(0).strip(),
                kind=CitationKind.STATUTE,
                normalized=f"Order {order} Rule {rule}, {statute}",
                section=f"Order {order} Rule {rule}",
                statute=statute,
                position=match.start(),
            )
        )

    for match in _RE_ARTICLE.finditer(text):
        article = " ".join(match.group("article").split())
        add(
            Citation(
                raw=match.group(0).strip(),
                kind=CitationKind.CONSTITUTION,
                normalized=f"Article {article}, Constitution of India",
                section=article,
                statute="Constitution of India",
                position=match.start(),
            )
        )

    return sorted(found, key=lambda c: c.position)


def extract_all(text: str) -> List[Citation]:
    """Extract every case and statutory citation from text, in order.

    Args:
        text: Any prose to sweep.

    Returns:
        All citations found, ordered by position in the text.
    """
    if not text:
        return []
    combined = extract_case_citations(text) + extract_statutory_citations(text)
    return sorted(combined, key=lambda c: c.position)


def parse_citation(citation: str) -> Optional[Citation]:
    """Parse a single citation string.

    Args:
        citation: One citation, e.g. ``"(2019) 5 SCC 266"`` or
            ``"Section 138 of the Negotiable Instruments Act, 1881"``.

    Returns:
        The parsed citation, or None if the string is not recognisable as one.
    """
    results = extract_all(citation)
    if not results:
        return None
    # Prefer the match that covers most of the input.
    return max(results, key=lambda c: len(c.raw))
