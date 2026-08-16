#!/usr/bin/env python3
"""Scrape pre-1950 Bombay High Court judgments from the official archive.

Source: the Judges' Library digitization at
``https://bombayhighcourt.gov.in/bhc/libweb/archive/`` - the High Court's own
public e-repository. Judgments are public records (Sec. 52(1)(q)(iv), Copyright
Act), so copying them for research is lawful.

Sections harvested:

* **Bombay High Court Reports (BHCR)** - the reported series, 1862-1875,
  with headnotes and the classic ``(vol) BHCR page`` citation.
* **Indian Law Reports, Bombay Series (ILR Bombay)** - 1876 onwards, the
  volumes the Court has digitized.
* **Sadar Diwani Adalat decisions** - 1860-1862, the pre-High-Court appellate
  court.
* **Handwritten judgments** - the 1864 manuscript ledger.

Output layout (matches the server's ``open_data`` corpus, so it can be indexed
by the existing DuckDB search)::

    data/case_law/historical/bombay/pdfs/          # downloaded PDFs
    data/case_law/historical/bombay/metadata.parquet   # searchable metadata

Be polite: one request at a time with a small delay, skip PDFs already present.
"""

from __future__ import annotations

import argparse
import re
import ssl
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import duckdb
import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "case_law" / "historical" / "bombay"
PDF_DIR = OUT_DIR / "pdfs"
METADATA = OUT_DIR / "metadata.parquet"

ARCHIVE = "https://bombayhighcourt.gov.in/bhc/libweb/archive"

# Official Bombay High Court court code in the server's corpus.
BOMBAY_CODE = "27_1"

REQUEST_TIMEOUT = 60.0
MAX_RETRIES = 4
POLITE_DELAY_SECONDS = 0.4


@dataclass
class Case:
    """One judgment harvested from the archive."""

    title: str
    series: str  # bhcr | ilr | diwani | manuscript
    bench: str
    year: int
    description: str = ""
    citation: str = ""
    source_url: str = ""
    pdf_name: str = ""
    decision_date: str = ""


class ArchiveClient:
    """Polite HTTP client for the Bombay High Court archive."""

    def __init__(self, delay: float = POLITE_DELAY_SECONDS):
        self.delay = delay
        tls = ssl.create_default_context()
        legacy = getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
        if legacy:
            tls.options |= legacy  # the court site still speaks TLS 1.2 with insecure renegotiation
        self._client = httpx.Client(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            verify=tls,
            headers={"User-Agent": "legal-mcp-scraper (research; contact rghc_bombay[at]mh-hc.nic.in)"},
        )

    def get(self, url: str) -> Optional[str]:
        """Fetch a URL as text with retries and a polite delay."""
        for attempt in range(MAX_RETRIES):
            time.sleep(self.delay)
            try:
                response = self._client.get(url)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return response.text
            except (httpx.HTTPError, httpx.TransportError) as exc:
                if attempt == MAX_RETRIES - 1:
                    print(f"  ! failed after retries: {url}: {exc}", file=sys.stderr)
                    return None
                time.sleep(2**attempt)
        return None

    def close(self) -> None:
        self._client.close()


def _abs(base: str, href: str) -> str:
    """Resolve a relative ``href`` against ``base``."""
    from urllib.parse import urljoin

    return urljoin(base, href)


def _clean(text: str) -> str:
    """Strip HTML entities/tags and collapse whitespace."""
    import html

    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(text)).split())


def _pdf_name(href: str) -> str:
    """Local filename for a PDF link (URL-decoded)."""
    from urllib.parse import unquote

    return unquote(Path(href).name)


def _years_from(label: str) -> Optional[int]:
    """Best-effort start year from a volume label like '1862-65' or '1875'."""
    match = re.search(r"(?:^|[^\d])(\d{4})", label)
    if not match:
        return None
    return int(match.group(1))


def parse_bhcr_page(
    html: str, base_url: str, volume_label: str
) -> tuple[List[Case], List[str]]:
    """Parse one BHCR index page into cases and links to follow."""
    cases: List[Case] = []
    next_pages: List[str] = []
    start_year = _years_from(volume_label) or 1862

    for match in re.finditer(
        r'<a\s+[^>]*href="([^"]+\.pdf)"[^>]*>(.*?)</a>(.*?)(?=<a\s|</tr>|</table>|\Z)',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        href, link_text, trailing = match.groups()
        name = _pdf_name(href)
        title = _clean(link_text)

        trailing_text = _clean(trailing)
        citation_match = re.search(r"(\d{4}-\d{4}\s*\(\d+\)\s*BHCR\s+[A-Z]?\d+[A-Z]?)", trailing_text, re.IGNORECASE)
        citation = citation_match.group(1) if citation_match else volume_label
        description = trailing_text.replace(citation, "").strip()

        cases.append(
            Case(
                title=title,
                series="bhcr",
                bench="bhcr",
                year=start_year,
                description=description,
                citation=citation,
                source_url=_abs(base_url, href),
                pdf_name=name,
                decision_date=f"{start_year}-01-01",
            )
        )

    for href in re.findall(
        r'<a\s+[^>]*href="([^"]+\.html)"[^>]*>', html, re.IGNORECASE
    ):
        if "bhcrvol" in href and href not in next_pages:
            next_pages.append(_abs(base_url, href))

    return cases, next_pages


def parse_ilr_page(
    html: str, base_url: str, volume_label: str
) -> tuple[List[Case], List[str]]:
    """Parse one ILR Bombay index page into cases and links to follow."""
    cases: List[Case] = []
    next_pages: List[str] = []

    for href, title in re.findall(
        r'<a\s+[^>]*href="([^"]+\.pdf)"[^>]*>([^<]+)</a>', html, re.IGNORECASE
    ):
        name = _pdf_name(href)
        page_match = re.search(r"Bom(\d+)\.pdf$", name, re.IGNORECASE)
        page = page_match.group(1) if page_match else ""
        cases.append(
            Case(
                title=_clean(title),
                series="ilr",
                bench="ilr",
                year=_years_from(volume_label) or 1876,
                citation=f"ILR Bombay {volume_label}" + (f" p.{page}" if page else ""),
                source_url=_abs(base_url, href),
                pdf_name=name,
                decision_date=f"{_years_from(volume_label) or 1876}-01-01",
            )
        )

    for href in re.findall(
        r'<a\s+[^>]*href="([^"]+\.html)"[^>]*>', html, re.IGNORECASE
    ):
        if "ilrbom" in href and href not in next_pages:
            next_pages.append(_abs(base_url, href))

    return cases, next_pages


def parse_simple_page(
    html: str, base_url: str, series: str, bench: str, year: int
) -> tuple[List[Case], List[str]]:
    """Parse Sadar Diwani / manuscript pages (case-number ledgers)."""
    cases: List[Case] = []
    next_pages: List[str] = []

    for href, label in re.findall(
        r'<a\s+[^>]*href="([^"]+\.pdf)"[^>]*>([^<]*)</a>', html, re.IGNORECASE
    ):
        name = _pdf_name(href)
        title = _clean(label) or f"{series.title()} decision {name}"
        cases.append(
            Case(
                title=title,
                series=series,
                bench=bench,
                year=year,
                citation=f"{series.title()} {title}",
                source_url=_abs(base_url, href),
                pdf_name=name,
                decision_date=f"{year}-01-01",
            )
        )

    for href in re.findall(
        r'<a\s+[^>]*href="([^"]+\.htm)"[^>]*>', html, re.IGNORECASE
    ):
        if series in ("diwani", "manuscript") and href not in next_pages:
            next_pages.append(_abs(base_url, href))

    return cases, next_pages


def crawl(
    client: ArchiveClient,
    start_url: str,
    parser,
    *,
    download: bool,
) -> List[Case]:
    """Follow an index page (and its pagination), collecting cases."""
    cases: List[Case] = []
    seen: set = set()
    queue: List[str] = [start_url]

    while queue:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        html = client.get(url)
        if html is None:
            continue
        found, links = parser(html, url)
        cases.extend(found)
        queue.extend(links)

    if download:
        download_pdfs(client, cases)

    return cases


def download_pdfs(client: ArchiveClient, cases: List[Case]) -> None:
    """Download any PDF not already on disk (incremental)."""
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    for case in cases:
        target = PDF_DIR / case.pdf_name
        if target.exists() and target.stat().st_size > 0:
            continue
        html_or_pdf = client.get(case.source_url)
        if html_or_pdf is None:
            print(f"  ! no PDF: {case.source_url}", file=sys.stderr)
            continue
        data = html_or_pdf.encode("utf-8")
        if not data.startswith(b"%PDF"):
            print(
                f"  ! not a PDF ({len(data)}B): {case.source_url}", file=sys.stderr
            )
            continue
        target.write_bytes(data)
        print(f"  - {case.pdf_name}")


def harvest_bhcr(client: ArchiveClient, download: bool) -> List[Case]:
    """BHCR volumes 1862-1875."""
    cases: List[Case] = []
    index_url = f"{ARCHIVE}/lawreports/BHCR/index.html"
    html = client.get(index_url)
    if not html:
        return cases
    seen: set = set()
    for href, label in re.findall(
        r'<a[^>]*href="([^"]+\.html)"[^>]*>([^<]*)</a>', html, re.IGNORECASE
    ):
        label = " ".join(label.split())
        if "BHCR" not in href or "bhcrvol" not in href or href in seen:
            continue
        seen.add(href)
        vol_url = _abs(index_url, href)
        print(f"[BHCR] {label} -> {vol_url}")
        cases.extend(
            crawl(
                client,
                vol_url,
                lambda html, url, _l=label: parse_bhcr_page(html, url, _l),
                download=download,
            )
        )
    return cases


def harvest_ilr(client: ArchiveClient, download: bool) -> List[Case]:
    """ILR Bombay volumes linked from the series index."""
    cases: List[Case] = []
    index_url = f"{ARCHIVE}/lawreports/ilrbom/index.html"
    html = client.get(index_url)
    if not html:
        return cases
    seen: set = set()
    for href, label in re.findall(
        r'<a[^>]*href="([^"]+\.html)"[^>]*>([^<]*)</a>', html, re.IGNORECASE
    ):
        label = " ".join(label.split())
        if "ilrbom" not in href or href in seen:
            continue
        seen.add(href)
        vol_url = _abs(index_url, href)
        print(f"[ILR] {label} -> {vol_url}")
        cases.extend(
            crawl(
                client,
                vol_url,
                lambda html, url, _l=label: parse_ilr_page(html, url, _l),
                download=download,
            )
        )
    return cases


def harvest_diwani(client: ArchiveClient, download: bool) -> List[Case]:
    """Sadar Diwani Adalat decisions, 1860-1862."""
    cases: List[Case] = []
    index_url = f"{ARCHIVE}/diwaniadalat/diwaniadalat.html"
    html = client.get(index_url)
    if not html:
        return cases
    for href, label in re.findall(
        r'<a[^>]*href="([^"]+\.htm)"[^>]*>([^<]*)</a>', html, re.IGNORECASE
    ):
        if "list" not in href:
            continue
        year = int(re.search(r"(\d{4})", href).group(1))
        list_url = _abs(index_url, href)
        print(f"[DIWANI] {year} -> {list_url}")
        cases.extend(
            crawl(
                client,
                list_url,
                lambda html, url: parse_simple_page(html, url, "diwani", "diwani", year),
                download=download,
            )
        )
    return cases


def harvest_manuscript(client: ArchiveClient, download: bool) -> List[Case]:
    """Handwritten judgments of 1864."""
    index_url = f"{ARCHIVE}/diwaniadalat/oldjudgments/list1864.htm"
    cases = crawl(
        client,
        index_url,
        lambda html, url: parse_simple_page(html, url, "manuscript", "manuscript", 1864),
        download=download,
    )
    return cases


def write_metadata(cases: List[Case]) -> Path:
    """Write the harvested cases as a searchable DuckDB parquet."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            """
            CREATE TABLE hist (
                court VARCHAR, year INTEGER, bench VARCHAR, title VARCHAR,
                description VARCHAR, judge VARCHAR, citation VARCHAR,
                decision_date VARCHAR, pdf_link VARCHAR, source_url VARCHAR
            )
            """
        )
        for c in cases:
            con.execute(
                "INSERT INTO hist VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    BOMBAY_CODE,
                    c.year,
                    c.bench,
                    c.title,
                    c.description,
                    "",
                    c.citation,
                    c.decision_date,
                    f"historical/bombay/pdfs/{c.pdf_name}",
                    c.source_url,
                ],
            )
        con.execute(f"COPY hist TO '{METADATA}' (FORMAT PARQUET)")
    finally:
        con.close()
    return METADATA


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download PDFs (default: metadata only)",
    )
    parser.add_argument(
        "--sections",
        default="bhcr,ilr,diwani,manuscript",
        help="Comma-separated sections to harvest",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=POLITE_DELAY_SECONDS,
        help="Seconds between requests (politeness)",
    )
    args = parser.parse_args()

    client = ArchiveClient(delay=args.delay)
    all_cases: List[Case] = []
    try:
        for section in args.sections.split(","):
            section = section.strip()
            if section == "bhcr":
                all_cases.extend(harvest_bhcr(client, args.download))
            elif section == "ilr":
                all_cases.extend(harvest_ilr(client, args.download))
            elif section == "diwani":
                all_cases.extend(harvest_diwani(client, args.download))
            elif section == "manuscript":
                all_cases.extend(harvest_manuscript(client, args.download))
            else:
                print(f"Unknown section: {section}", file=sys.stderr)
            # Write metadata as each section completes so search sees the
            # corpus even while a long --download run is still fetching PDFs.
            if all_cases:
                write_metadata(all_cases)
    finally:
        client.close()

    print(f"\nHarvested {len(all_cases)} cases.")
    if all_cases:
        written = write_metadata(all_cases)
        print(f"Metadata written to {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
