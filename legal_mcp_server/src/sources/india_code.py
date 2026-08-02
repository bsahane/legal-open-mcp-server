"""Access to Indian bare Acts from a bundled offline corpus.

India Code (indiacode.nic.in) is a DSpace portal with no documented public API,
so this server ships a normalised offline corpus under ``data/acts/`` instead of
scraping at query time. Each Act is one JSON file:

.. code-block:: json

    {
      "slug": "negotiable-instruments-act-1881",
      "title": "Negotiable Instruments Act, 1881",
      "short_title": "NI Act",
      "year": 1881,
      "aliases": ["ni act", "nia", "negotiable instruments act"],
      "coverage": "full",
      "source": "civictech-India/Indian-Law-Penal-Code-Json",
      "india_code_url": "https://www.indiacode.nic.in/handle/123456789/2263",
      "sections": [
        {"number": "138", "heading": "Dishonour of cheque...", "text": "...",
         "chapter": "XVII"}
      ]
    }

Coverage is deliberately explicit. ``coverage`` is ``"full"`` when every section
is present and ``"partial"`` when only selected sections have been curated. The
distinction matters: a lookup that misses in a *partial* Act means "not in our
extract", whereas a miss in a *full* Act means the section does not exist. The
lookup functions return that difference rather than flattening it, so that
citation verification never reports a false negative as a fabrication.

Run ``python scripts/fetch_corpus.py`` to build or refresh the corpus.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from legal_mcp_server.src.settings import settings
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()

COVERAGE_FULL = "full"
COVERAGE_PARTIAL = "partial"


TEXT_AUTHENTIC = "authentic"
TEXT_SUMMARY = "summary"

SUMMARY_CAVEAT = (
    "This is a curated summary of the provision, NOT its authentic text. "
    "Quote it as a summary, never as the words of the statute, and read the "
    "bare provision at the India Code URL before relying on its exact wording."
)


@dataclass
class Section:
    """One section of an Act.

    ``text_kind`` distinguishes reproduced statutory text from a curated
    summary. Presenting a paraphrase as the words of a statute is the statutory
    equivalent of a fabricated citation, so the difference is carried all the
    way out to the tool response.
    """

    act_slug: str
    act_title: str
    number: str
    heading: str
    text: str
    chapter: Optional[str] = None
    url: str = ""
    text_kind: str = TEXT_AUTHENTIC

    @property
    def is_authentic(self) -> bool:
        """Whether ``text`` reproduces the statute rather than summarising it."""
        return self.text_kind == TEXT_AUTHENTIC

    def to_dict(self) -> Dict[str, object]:
        """Serialise for MCP tool output."""
        payload: Dict[str, object] = {
            "act_slug": self.act_slug,
            "act": self.act_title,
            "section": self.number,
            "heading": self.heading,
            "text": self.text,
            "text_kind": self.text_kind,
            "chapter": self.chapter,
            "url": self.url,
        }
        if not self.is_authentic:
            payload["caveat"] = SUMMARY_CAVEAT
        return payload


@dataclass
class Act:
    """One Act in the bundled corpus."""

    slug: str
    title: str
    year: Optional[int]
    aliases: List[str]
    coverage: str
    source: str
    url: str
    short_title: Optional[str] = None
    act_number: Optional[str] = None
    note: Optional[str] = None
    sections: Dict[str, Section] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        """Whether every section of this Act is present in the corpus."""
        return self.coverage == COVERAGE_FULL

    def to_dict(self, include_sections: bool = False) -> Dict[str, object]:
        """Serialise for MCP tool output."""
        payload: Dict[str, object] = {
            "slug": self.slug,
            "title": self.title,
            "short_title": self.short_title,
            "year": self.year,
            "act_number": self.act_number,
            "coverage": self.coverage,
            "section_count": len(self.sections),
            "source": self.source,
            "url": self.url,
            "note": self.note,
        }
        if include_sections:
            payload["sections"] = [
                {"section": s.number, "heading": s.heading}
                for s in self.sections.values()
            ]
        return payload


def _normalise_section_number(number: str) -> str:
    """Canonicalise a section number for lookup.

    ``"138"``, ``"138."``, ``"Section 138"``, ``"138 A"`` and ``"138-A"`` must
    all reach the same entry, while ``"138(1)"`` reduces to ``"138"`` because
    sub-sections are not stored separately.
    """
    text = str(number).strip().lower()
    text = re.sub(r"^(section|sec\.?|s\.)\s*", "", text)
    text = re.sub(r"\(.*?\)", "", text)
    text = text.replace("-", "").replace(" ", "").rstrip(".")
    return text


def _normalise_act_name(name: str) -> str:
    """Canonicalise an Act name for alias matching."""
    text = name.strip().lower()
    text = re.sub(r"^the\s+", "", text)
    text = text.replace(".", "").replace(",", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _corpus_dir() -> Path:
    return Path(settings.LEGAL_DATA_PATH).expanduser() / "acts"


@lru_cache(maxsize=1)
def load_corpus() -> Tuple[Dict[str, Act], Dict[str, str]]:
    """Load every Act JSON file from the corpus directory.

    Cached for the process lifetime; call :func:`reload_corpus` after changing
    the files on disk.

    Returns:
        A tuple of (acts by slug, alias -> slug index).
    """
    acts: Dict[str, Act] = {}
    alias_index: Dict[str, str] = {}

    directory = _corpus_dir()
    if not directory.is_dir():
        logger.warning(
            f"Statute corpus directory not found at {directory}. Statutory lookups "
            "will report themselves as unavailable. Run scripts/fetch_corpus.py."
        )
        return acts, alias_index

    for path in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Skipping unreadable Act file {path}: {e}")
            continue

        try:
            slug = raw["slug"]
            act = Act(
                slug=slug,
                title=raw["title"],
                year=raw.get("year"),
                aliases=[str(a) for a in raw.get("aliases", [])],
                coverage=raw.get("coverage", COVERAGE_PARTIAL),
                source=raw.get("source", "unknown"),
                url=raw.get("india_code_url", ""),
                short_title=raw.get("short_title"),
                act_number=raw.get("act_number"),
                note=raw.get("note"),
            )
            for entry in raw.get("sections", []):
                section = Section(
                    act_slug=slug,
                    act_title=act.title,
                    number=str(entry["number"]),
                    heading=entry.get("heading", ""),
                    text=entry.get("text", ""),
                    chapter=entry.get("chapter"),
                    url=entry.get("url") or act.url,
                    text_kind=entry.get(
                        "text_kind", raw.get("text_kind", TEXT_AUTHENTIC)
                    ),
                )
                act.sections[_normalise_section_number(section.number)] = section
        except Exception as e:
            logger.error(f"Skipping malformed Act file {path}: {e}")
            continue

        acts[slug] = act

        for alias in [act.title, act.slug.replace("-", " "), *act.aliases]:
            if act.short_title:
                alias_index[_normalise_act_name(act.short_title)] = slug
            alias_index[_normalise_act_name(alias)] = slug

    logger.info(f"Loaded {len(acts)} Acts from the bundled statute corpus")
    return acts, alias_index


def reload_corpus() -> None:
    """Drop the cached corpus so the next call re-reads from disk."""
    load_corpus.cache_clear()


def corpus_available() -> bool:
    """Whether any Act at all is bundled."""
    acts, _ = load_corpus()
    return bool(acts)


def list_acts() -> List[Act]:
    """Every Act in the corpus, alphabetically by title."""
    acts, _ = load_corpus()
    return sorted(acts.values(), key=lambda a: a.title)


def resolve_act(name: str) -> Optional[Act]:
    """Find an Act by name, short title, alias or approximate spelling.

    Args:
        name: An Act name as a user or a citation would write it.

    Returns:
        The matching Act, or None if nothing in the corpus is close enough.
    """
    if not name or not name.strip():
        return None

    acts, alias_index = load_corpus()
    if not acts:
        return None

    key = _normalise_act_name(name)

    if key in alias_index:
        return acts[alias_index[key]]

    # Substring containment handles "Negotiable Instruments Act" against
    # "negotiable instruments act, 1881" and vice versa.
    for alias, slug in alias_index.items():
        if key and (key in alias or alias in key) and abs(len(key) - len(alias)) < 25:
            return acts[slug]

    try:
        from rapidfuzz import process

        match = process.extractOne(key, list(alias_index.keys()), score_cutoff=88)
        if match:
            return acts[alias_index[match[0]]]
    except ImportError:  # pragma: no cover - rapidfuzz is a hard dependency
        logger.debug("rapidfuzz unavailable; skipping fuzzy Act matching")

    return None


def lookup_section(statute: str, section: str) -> Optional[Section]:
    """Look up one section of one Act.

    Args:
        statute: Act name, short title or alias.
        section: Section number, with or without sub-section.

    Returns:
        The section, or None if the Act or the section is not in the corpus.
        Use :func:`resolve_act` to tell those two cases apart.
    """
    act = resolve_act(statute)
    if act is None:
        return None
    return act.sections.get(_normalise_section_number(section))


def search_sections(
    query: str, statute: Optional[str] = None, limit: int = 10
) -> List[Section]:
    """Full-text search across section headings and bodies.

    Args:
        query: Words to look for.
        statute: Optional Act to restrict the search to.
        limit: Maximum sections to return.

    Returns:
        Matching sections, best first. Heading matches outrank body matches.
    """
    acts, _ = load_corpus()
    if not acts:
        return []

    if statute:
        act = resolve_act(statute)
        candidates = [act] if act else []
    else:
        candidates = list(acts.values())

    terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]
    if not terms:
        return []

    scored: List[Tuple[int, Section]] = []
    for act in candidates:
        for sec in act.sections.values():
            heading = sec.heading.lower()
            body = sec.text.lower()
            score = 0
            for term in terms:
                if term in heading:
                    score += 5
                if term in body:
                    score += 1
            if score:
                scored.append((score, sec))

    scored.sort(key=lambda pair: (-pair[0], pair[1].act_title, pair[1].number))
    return [sec for _, sec in scored[:limit]]


def coverage_report() -> Dict[str, object]:
    """Summarise what the corpus does and does not contain.

    Being able to state coverage precisely is what lets the statute tools say
    "not in the corpus" instead of "does not exist".
    """
    acts, _ = load_corpus()
    full = [a for a in acts.values() if a.is_complete]
    partial = [a for a in acts.values() if not a.is_complete]
    return {
        "act_count": len(acts),
        "section_count": sum(len(a.sections) for a in acts.values()),
        "complete_acts": sorted(a.title for a in full),
        "partial_acts": sorted(a.title for a in partial),
        "corpus_path": str(_corpus_dir()),
    }
