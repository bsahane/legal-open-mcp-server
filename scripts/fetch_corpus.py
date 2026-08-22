#!/usr/bin/env python3
"""Build the bundled bare-Acts corpus under ``data/acts/``.

Sources
-------
``civictech-India/Indian-Law-Penal-Code-Json`` publishes several central Acts
as section-level JSON under an open licence. This script downloads those,
normalises them into the schema that
``legal_mcp_server.src.sources.india_code`` expects, and writes one file per
Act.

Acts not available from that source ship as hand-curated *partial* extracts in
``data/acts/seed/`` and are copied through unchanged. Partial coverage is
recorded honestly in each file so that a missing section is reported as "not in
the corpus" rather than "does not exist".

Usage::

    python scripts/fetch_corpus.py            # fetch and write everything
    python scripts/fetch_corpus.py --check    # report coverage, write nothing
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

REPO_RAW = (
    "https://raw.githubusercontent.com/civictech-India/Indian-Law-Penal-Code-Json/main"
)

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "acts"
SEED_DIR = REPO_ROOT / "data" / "acts_seed"

# Acts available from the open JSON corpus, with the metadata that source lacks.
REMOTE_ACTS: List[Dict[str, Any]] = [
    {
        "file": "ipc.json",
        "slug": "indian-penal-code-1860",
        "title": "Indian Penal Code, 1860",
        "short_title": "IPC",
        "year": 1860,
        "act_number": "45 of 1860",
        "aliases": ["ipc", "penal code", "indian penal code"],
        "india_code_url": "https://www.indiacode.nic.in/handle/123456789/2263",
        "note": (
            "Repealed and replaced by the Bharatiya Nyaya Sanhita, 2023 with "
            "effect from 1 July 2024. Still governs offences committed before "
            "that date."
        ),
    },
    {
        "file": "crpc.json",
        "slug": "code-of-criminal-procedure-1973",
        "title": "Code of Criminal Procedure, 1973",
        "short_title": "CrPC",
        "year": 1973,
        "act_number": "2 of 1974",
        "aliases": ["crpc", "cr.p.c", "criminal procedure code"],
        "india_code_url": "https://www.indiacode.nic.in/handle/123456789/15272",
        "note": (
            "Repealed and replaced by the Bharatiya Nagarik Suraksha Sanhita, "
            "2023 with effect from 1 July 2024."
        ),
    },
    {
        "file": "iea.json",
        "slug": "indian-evidence-act-1872",
        "title": "Indian Evidence Act, 1872",
        "short_title": "Evidence Act",
        "year": 1872,
        "act_number": "1 of 1872",
        "aliases": ["evidence act", "iea", "indian evidence act"],
        "india_code_url": "https://www.indiacode.nic.in/handle/123456789/15351",
        "note": (
            "Repealed and replaced by the Bharatiya Sakshya Adhiniyam, 2023 "
            "with effect from 1 July 2024."
        ),
    },
    {
        "file": "cpc.json",
        "slug": "code-of-civil-procedure-1908",
        "title": "Code of Civil Procedure, 1908",
        "short_title": "CPC",
        "year": 1908,
        "act_number": "5 of 1908",
        "aliases": ["cpc", "civil procedure code", "code of civil procedure"],
        "india_code_url": "https://www.indiacode.nic.in/handle/123456789/2191",
    },
    {
        "file": "nia.json",
        "slug": "negotiable-instruments-act-1881",
        "title": "Negotiable Instruments Act, 1881",
        "short_title": "NI Act",
        "year": 1881,
        "act_number": "26 of 1881",
        "aliases": ["ni act", "nia", "negotiable instruments act"],
        "india_code_url": "https://www.indiacode.nic.in/handle/123456789/2189",
    },
    # hma.json is excluded: upstream ships it as CSV crammed into a JSON list,
    # with every field collapsed into one key. It cannot be parsed reliably and
    # a mangled Act is worse than a missing one.
    {
        "file": "MVA.json",
        "slug": "motor-vehicles-act-1988",
        "title": "Motor Vehicles Act, 1988",
        "short_title": "MV Act",
        "year": 1988,
        "act_number": "59 of 1988",
        "aliases": ["mv act", "mva", "motor vehicles act"],
        "india_code_url": "https://www.indiacode.nic.in/handle/123456789/1798",
    },
    {
        "file": "ida.json",
        "slug": "indian-divorce-act-1869",
        "title": "Indian Divorce Act, 1869",
        "short_title": "Divorce Act",
        "year": 1869,
        "act_number": "4 of 1869",
        "aliases": ["divorce act", "ida", "indian divorce act"],
        "india_code_url": "https://www.indiacode.nic.in/handle/123456789/2400",
    },
]


def fetch_json(url: str) -> Any:
    """Download and parse a JSON document."""
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310  # nosec B310 - https-only corpus URLs
        return json.loads(response.read().decode("utf-8"))


def normalise(entries: List[Dict[str, Any]], meta: Dict[str, Any]) -> Dict[str, Any]:
    """Convert one upstream Act file into the corpus schema."""
    sections = []
    for entry in entries:
        # Upstream is inconsistent: ipc.json capitalises the section key.
        number = entry.get("section", entry.get("Section"))
        if number is None:
            continue
        chapter = entry.get("chapter_title") or entry.get("chapter")
        sections.append(
            {
                "number": str(number).strip(),
                "heading": (entry.get("section_title") or "").strip(),
                "text": (entry.get("section_desc") or "").strip(),
                "chapter": str(chapter) if chapter else None,
            }
        )

    if not sections:
        raise ValueError(
            f"no sections parsed from {meta['file']} - upstream schema has changed"
        )

    return {
        "slug": meta["slug"],
        "title": meta["title"],
        "short_title": meta.get("short_title"),
        "year": meta.get("year"),
        "act_number": meta.get("act_number"),
        "aliases": meta.get("aliases", []),
        "coverage": "full",
        "source": "civictech-India/Indian-Law-Penal-Code-Json",
        "india_code_url": meta.get("india_code_url", ""),
        "note": meta.get("note"),
        "sections": sections,
    }


def copy_seed_acts() -> int:
    """Copy hand-curated partial Acts into the corpus directory."""
    if not SEED_DIR.is_dir():
        return 0
    copied = 0
    for path in sorted(SEED_DIR.glob("*.json")):
        shutil.copy2(path, OUT_DIR / path.name)
        copied += 1
    return copied


def main() -> int:
    """Fetch, normalise and write the corpus."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report existing coverage without downloading anything",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.check:
        total_sections = 0
        for path in sorted(OUT_DIR.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            count = len(data.get("sections", []))
            total_sections += count
            print(f"  {data['coverage']:<8} {count:>5} sections  {data['title']}")
        print(
            f"\n{total_sections} sections across {len(list(OUT_DIR.glob('*.json')))} Acts"
        )
        return 0

    written = 0
    for meta in REMOTE_ACTS:
        url = f"{REPO_RAW}/{meta['file']}"
        print(f"Fetching {meta['title']} ...", flush=True)
        try:
            entries = fetch_json(url)
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)
            continue

        act = normalise(entries, meta)
        target = OUT_DIR / f"{meta['slug']}.json"
        target.write_text(
            json.dumps(act, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"  wrote {len(act['sections'])} sections -> {target.name}")
        written += 1

    seeded = copy_seed_acts()
    print(f"\n{written} Acts fetched, {seeded} curated Acts copied into {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
