# Full-text (topical) case-law search

## Problem

`search_case_law` queries `fts/corpus.sqlite`, an FTS5 index of judgment
**metadata** only: titles, party names, judges and short descriptions. A query by
legal proposition, such as `anticipatory bail parity` with
`court="Bombay High Court"`, returns nothing, even though many judgments
discuss exactly that. The full corpus is 16.2M judgments, too many to extract
text from, so this design covers the Supreme Court and the default High Court
(Bombay) first.

## Measurements (2026-10-19)

Counts come from the `*.index.json` files beside the PDF tar archives in the
public buckets. Extraction times were measured with `pypdf` (the extractor
`get_judgment` already uses) on three complete archives, on an 8-core Mac.
Index sizes come from FTS5 tables built over the same extracted text.

| | Supreme Court (English) | Bombay High Court |
|---|---|---|
| PDFs | 43,572 | 2,335,439 |
| PDF bytes on S3 | 22.7 GB | 88.2 GB |
| Sample measured | 2024, 782 PDFs | 2015 principal seat (O.S.), 10,708 PDFs; 2024 Goa, 1,829 PDFs |
| Text per judgment, mean (median) | 53 KB (32 KB) | 5.1–8.8 KB (1.8–2.0 KB) |
| pypdf seconds per judgment, mean (median) | 0.18 (0.10) | 0.041–0.069 (0.009–0.016) |
| No text layer (scans) | 0 of 782 | 7 of 12,537 |
| **Total text** | **≈ 2.3 GB** | **≈ 12–20 GB** |
| **Extraction CPU time** | **≈ 2.2 CPU-hours** (≈ 17 min on 8 cores) | **≈ 27–45 CPU-hours** (≈ 3.5–5.5 h on 8 cores) |
| **Index size** (contentless, positions kept) | **≈ 0.75 GB** | **≈ 6–9 GB** (4–7 GB inverted index + ≈ 2 GB per-judgment metadata) |

Bombay year distribution is very skewed: 239k PDFs in 2024, 350k in 2025, and
142k so far in 2026, against roughly 100k a year for 2010–2023. Most Bombay
PDFs are short procedural orders (median text about 2 KB). Judgments with at
least 4 KB of text are 29% of documents but hold 87% of the text, so filtering
out short orders would not shrink the index much.

FTS5 index size as a fraction of the extracted text:

| FTS5 options | SC | Bombay |
|---|---|---|
| text stored, `detail=full` | 1.33× | 1.40× |
| contentless, `detail=full` (positions; phrase queries work) | **0.31×** | **0.34×** |
| contentless, `detail=column` (no phrase queries) | 0.08× | 0.12× |

Other measurements:

* `pdftotext` (poppler) extracts the SC sample in 6.7 s against pypdf's 19.4 s
  on 8 cores, so it is about 2.9× faster.
* The prototype, run end to end against live S3 from a laptop (8 workers, 32
  concurrent downloads), indexed 1,498 judgments in 38.5 s, about 39 per second.
  The resulting `body.sqlite` was 23 MB for 65M characters of text, 0.36× the
  text including the metadata rows.
* On that prototype index, `'"specific performance" readiness willingness'`
  with `court="Supreme Court"` returned 5 on-point judgments in about 3 ms.
  Latency on the full 2.4M-judgment index has **not** been measured yet.

## Design

**A separate file, `fts/body.sqlite`, keyed by `doc_id`.** It is not part of
`corpus.sqlite` because a full rebuild swaps that file out and incremental
updates renumber its rowids. The body index uses the stable `doc_id`
(`sc:2024:…`, `hc:27_1:…`) and only grows.

```
docs(id INTEGER PRIMARY KEY, doc_id TEXT UNIQUE, court_code, decision_date,
     chars INTEGER, row TEXT)         -- row = the metadata row as JSON
body_fts USING fts5(body, content='', tokenize='porter unicode61 remove_diacritics 2')
```

* **Contentless.** Only the inverted index is stored, about 0.3× the text,
  against 1.3–1.4× if the text is stored too. The cost is that results carry no
  matching-passage snippet. Users open the judgment with `get_judgment` or
  `search_within_judgment`, which they must do before citing it anyway.
* **Positions are kept** (`detail=full`), so `"anticipatory bail"` matches only
  that exact phrase. Without positions the index would be 4× smaller, but
  phrase queries would stop working, and phrases are what legal research needs.
* **Porter stemming**, so `granted` matches `grant`. The metadata index
  prefix-matches instead; prefixes over full judgment text explode.
* **Self-contained filters.** Each `docs` row carries the metadata needed for
  court, date and judge filters and for rendering results, so a search never
  joins across the two files.

**Builder (`make fts-body`, `scripts/build_body_index.py`).** It reads the list
of judgments from the metadata index, using the FTS5 `court_code` column, newest
first. It skips `doc_id`s already present, takes each PDF from the
`get_judgment` cache or from public S3 without caching it, extracts the text in
a process pool, and commits every batch of 64. The build is incremental and
resumable, like the per-file metadata update: an interrupted run resumes where
it stopped, and a nightly run after `sync_case_law` picks up only new judgments.
`--limit N` makes it build in slices. Scans and 404s are recorded with
`chars=0` so they are not downloaded again. Fetch errors are not recorded, so
the next run retries them.

**Search.** `search_case_law(..., full_text=True)` is gated by
`CASE_LAW_FULL_TEXT_SEARCH` (off by default). Every word or quoted phrase must
appear, results are ranked by BM25, and court, date and judge filters apply.
The response's `scope_note` lists the courts and counts actually indexed, so an
empty result is not read as "no authority exists" anywhere else.
`case_law_status` reports the same coverage under `full_text_index`.

### Rollout

1. Supreme Court: about 20 minutes and 0.75 GB.
2. Bombay, newest first: the builder's default order. 2024–2026 alone is
   730k judgments, about 31% of Bombay.
3. The rest of Bombay, in `--limit` slices on a nightly cron.

## Upgrade paths (not built)

| Change | When |
|---|---|
| Stream the year/bench **tar archives** instead of 2.3M per-PDF GETs | if per-PDF download, not extraction, turns out to bound the Bombay build |
| `pdftotext` instead of pypdf (2.9× faster) | if extraction time matters; needs poppler in the image |
| Cap BM25 ranking for very broad terms (like `FTS_RANK_LIMIT`) | if a common word across 2.4M judgments proves slow; marked in `body_index.search` |
| Trim the per-judgment metadata JSON (≈ 870 B/row, ≈ 2 GB for Bombay) | if disk is tight |
| Embeddings (`sources/embeddings.py`) | only to rerank the top few hundred keyword hits. Keyword search with phrases and stemming returned on-point results in the prototype, so embeddings are not needed to make topical search work |
| More High Courts | same builder, `--court Delhi` etc.; size scales with PDF count |
