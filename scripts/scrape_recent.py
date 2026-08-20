#!/usr/bin/env python3
"""Scrape recently-published judgments from official court websites.

The AWS Open Data corpus only refreshes every two months, so the newest
judgments are never in the synced dataset. This script fills that gap by
harvesting the "recent" sections courts publish on their own sites:

* Bombay High Court - ``front/recentjudgment`` (recent reported judgments,
  with direct PDFs, case numbers and decision dates);
* Supreme Court of India - ``www.sci.gov.in/latest-orders`` (recent orders,
  with the official viewer link for the PDF).

Output lands in ``data/case_law/recent/<court>/metadata.parquet`` plus a
``pdfs/`` directory, in the same column layout as the historical corpus so
the server can UNION it straight into search. Re-running is incremental:
entries are keyed by document id and PDFs already on disk are skipped.

Run from the project root::

    python scripts/scrape_recent.py --download
"""

from __future__ import annotations

import argparse
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from legal_mcp_server.src.settings import settings  # noqa: E402

DATA_ROOT = Path(settings.CASE_LAW_DATA_PATH)
RECENT_DIR = DATA_ROOT / "recent"

BOMBAY_CODE = "27_1"
SC_CODE = "SC"

BHC_INDEX = "https://bombayhighcourt.gov.in/bhc/index.php/front/recentjudgment"
SC_ORDERS = "https://www.sci.gov.in/latest-orders"

POLITE_DELAY_SECONDS = 0.4
REQUEST_TIMEOUT_SECONDS = 40


@dataclass
class Case:
    court: str
    bench: str
    year: int
    title: str
    description: str
    judge: str
    citation: str
    decision_date: str  # YYYY-MM-DD
    pdf_link: str  # relative path under DATA_ROOT, or "" if not downloadable
    source_url: str
    doc_id: str
    pdf_url: Optional[str] = None


def _ssl_context() -> ssl.SSLContext:
    """The Bombay HC site speaks TLS with insecure renegotiation; downgrade."""
    ctx = ssl.create_default_context()
    try:
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
    except AttributeError:
        pass
    return ctx


def _fetch(url: str, headers: Optional[Dict[str, str]] = None) -> bytes:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(
        req, timeout=REQUEST_TIMEOUT_SECONDS, context=_ssl_context()
    ) as resp:
        return resp.read()


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_date(d: str) -> str:
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(d.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def harvest_bhc_recent(min_date: date, download: bool, delay: float) -> List[Case]:
    """Recent reported judgments from the Bombay High Court portal."""
    cases: List[Case] = []
    seen: set = set()
    page = 1
    while True:
        url = BHC_INDEX if page == 1 else f"{BHC_INDEX}?page={page}"
        html = _fetch(url).decode("utf-8", "ignore")
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
        new_this_page = 0
        for tr in rows:
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if len(tds) < 4:
                continue
            # Columns: Sr.No | Matter No | Party | Coram | Order Date (+ PDF)
            matter = _clean(tds[1])
            title = _clean(tds[2])
            judge = _clean(tds[3])
            last = tds[-1]
            if not title or "order-pdf" not in last:
                continue
            dstr = _parse_date(re.search(r"(\d{2}/\d{2}/\d{4})", last).group(1))
            if not dstr:
                continue
            d = datetime.strptime(dstr, "%Y-%m-%d").date()
            if d < min_date:
                return cases
            m = re.search(
                r'order-pdf/([A-Z0-9]+)/(\d{4}-\d{2}-\d{2})\?path=([^"&\s]+)',
                last,
            )
            if not m:
                continue
            cnr, pdf_date, path = m.group(1), m.group(2), m.group(3)
            if cnr in seen:
                continue
            seen.add(cnr)
            new_this_page += 1
            pdf_url = (
                "https://bombayhighcourt.gov.in/bhc/index.php/recentjudgments/"
                f"order-pdf/{cnr}/{pdf_date}?path={path}"
            )
            cases.append(
                Case(
                    court=BOMBAY_CODE,
                    bench="bombay",
                    year=d.year,
                    title=title,
                    description=title,
                    judge=judge,
                    citation=f"{matter} ({cnr})",
                    decision_date=dstr,
                    pdf_link=f"recent/bombay/pdfs/{cnr}.pdf",
                    source_url=pdf_url,
                    doc_id=f"{cnr}.pdf",
                    pdf_url=pdf_url,
                )
            )
        if new_this_page == 0:
            break
        if page >= 20:
            break
        page += 1
        time.sleep(delay)
    return cases


def harvest_sc_latest(min_date: date) -> List[Case]:
    """Recent orders from the Supreme Court's own site (metadata + link)."""
    html = _fetch(SC_ORDERS).decode("utf-8", "ignore")
    entries = re.findall(
        r'<li>\s*<a href="https://www\.sci\.gov\.in/view-pdf/'
        r"\?diary_no=(\d+)&type=([a-z])&order_date=(\d{4}-\d{2}-\d{2})"
        r'[^"]*"[^>]*>(.*?)</a>\s*</li>',
        html,
        re.S,
    )
    cases: List[Case] = []
    seen: set = set()
    for diary, typ, od, txt in entries:
        d = datetime.strptime(od, "%Y-%m-%d").date()
        if d < min_date:
            continue
        clean = _clean(txt)
        title = re.sub(r"\s*-\s*Diary Number.*$", "", clean.split(" - (Uploaded")[0])
        title = re.sub(r"\s*-\s*\d{2}-[A-Za-z]{3}-\d{4}\s*$", "", title)
        mcase = re.search(r"-\s*([A-Za-z().]+ No\.?\s*[\d/-]+)\s*-", clean)
        citation = mcase.group(1) if mcase else ""
        doc_id = f"sc{diary}_{typ}.pdf"
        if doc_id in seen:
            continue
        seen.add(doc_id)
        pdf_url = (
            f"https://www.sci.gov.in/view-pdf/?diary_no={diary}&type={typ}"
            f"&order_date={od}&from=latest_judgements_order"
        )
        cases.append(
            Case(
                court=SC_CODE,
                bench="",
                year=d.year,
                title=title or clean[:80],
                description=clean,
                judge="",
                citation=citation,
                decision_date=od,
                # No local copy (the official PDF is viewer-gated); keep a
                # stable locator so doc_ids round-trip and metadata lookup works.
                pdf_link=f"recent/{SC_CODE}/pdfs/{doc_id}",
                source_url=pdf_url,
                doc_id=doc_id,
                pdf_url=None,
            )
        )
    return cases


def download_pdfs(cases: List[Case], delay: float) -> None:
    for case in cases:
        if not case.pdf_url or not case.pdf_link:
            continue
        target = DATA_ROOT / case.pdf_link
        if target.exists() and target.stat().st_size > 0:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = _fetch(case.pdf_url)
        except Exception as exc:
            print(f"  ! failed: {case.source_url} ({exc})", file=sys.stderr)
            continue
        if not data.startswith(b"%PDF"):
            print(f"  ! not a PDF ({len(data)}B): {case.source_url}", file=sys.stderr)
            continue
        target.write_bytes(data)
        print(f"  - {case.pdf_link.split('/')[-1]}")
        time.sleep(delay)


def write_metadata(cases: List[Case]) -> List[Path]:
    """Write per-court parquet files (one per court, matching the server's
    ``recent/*/metadata.parquet`` glob)."""
    RECENT_DIR.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    by_court: Dict[str, List[Case]] = {}
    for c in cases:
        by_court.setdefault(c.court, []).append(c)
    con = duckdb.connect()
    try:
        for court, rows in by_court.items():
            con.execute(
                """
                CREATE TABLE recent (
                    court VARCHAR, year INTEGER, bench VARCHAR, title VARCHAR,
                    description VARCHAR, judge VARCHAR, citation VARCHAR,
                    decision_date VARCHAR, pdf_link VARCHAR, source_url VARCHAR
                )
                """
            )
            for c in rows:
                con.execute(
                    "INSERT INTO recent VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [
                        c.court,
                        c.year,
                        c.bench,
                        c.title,
                        c.description,
                        c.judge,
                        c.citation,
                        c.decision_date,
                        c.pdf_link,
                        c.source_url,
                    ],
                )
            out_dir = RECENT_DIR / court
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / "metadata.parquet"
            con.execute(f"COPY recent TO '{out}' (FORMAT PARQUET)")
            written.append(out)
            con.execute("DROP TABLE recent")
    finally:
        con.close()
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--download", action="store_true", help="Download BHC PDFs (default: no)"
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=21,
        help="Harvest entries with decision date within this many days",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=POLITE_DELAY_SECONDS,
        help="Seconds between requests (politeness)",
    )
    args = parser.parse_args()

    min_date = date.today() - timedelta(days=args.lookback_days)

    bhc = harvest_bhc_recent(min_date, args.download, args.delay)
    sc = harvest_sc_latest(min_date)
    all_cases = bhc + sc
    print(f"Harvested {len(all_cases)} recent entries ({len(bhc)} BHC, {len(sc)} SC).")

    if args.download:
        download_pdfs(bhc, args.delay)

    if all_cases:
        written = write_metadata(all_cases)
        print(f"Metadata written to {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
