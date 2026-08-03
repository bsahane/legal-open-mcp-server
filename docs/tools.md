# Tool reference

39 tools in seven groups. Every tool returns a dictionary with a `status` key
and never raises to the client.

## The status contract

| Status | Meaning | How to treat it |
|---|---|---|
| `success` | The operation completed | Use the result |
| `not_found` | The source was consulted and had nothing matching | A real, reportable answer |
| `unavailable` | The source **could not be consulted** | **Not** a finding of absence. Say the lookup failed; do not substitute recalled law. |
| `incomplete` | Required input is missing | Ask the user for the named fields |
| `manual_action_required` | A human step is needed | Follow the returned instructions |
| `error` | Bad input or an unexpected failure | Report it |

The distinction between `not_found` and `unavailable` is the most important one
in this server. "No authority found" and "I could not look" are different
answers with different consequences.

---

## Research and citations

Case law comes from the **free** AWS Open Data release of Indian judgments
(CC-BY-4.0): Supreme Court from 1950 with official S.C.R. and neutral
citations, plus 25 High Courts / 45 benches. No API key, no per-query charge.

`sync_case_law` downloads Parquet metadata locally; searches then run offline
through DuckDB. Judgment PDFs are pulled from public S3 on demand and cached.

### `sync_case_law`
Downloads metadata for given `courts` and a `from_year`/`to_year` range.
Defaults to the Supreme Court plus the configured default High Court, 2015-2026.
Tens of MB per court-year. Run once, then widen when a search comes up empty.

### `case_law_status`
Which backend is active, whether it is usable, and exactly which courts and
years are searchable. Check this before treating an empty search as meaningful.

### `search_case_law`
Filters: `court`, `from_date`, `to_date`, `judge`, `limit`. Searches case
**metadata** — party names, case titles, judges, short descriptions — not the
full text of every judgment. The response carries a `scope_note` saying so, so
an empty result is never mistaken for "no such authority exists".

### `get_judgment`
Full judgment text, extracted from the official PDF. `max_chars` truncates and
discloses the truncation. Scanned judgments with no extractable text say that
plainly rather than returning an empty string.

### `search_within_judgment`
Passages inside one judgment matching a query, with character offsets. Runs
against the cached PDF text, so it is offline and free after the first fetch.

### `find_related_proceedings`
Other proceedings sharing the judgment's party names — appeals, reviews,
connected matters. **This is not a citator.** The open corpus has no citation
graph, and the response sets `is_citator: false` and says outright that it does
not establish whether the judgment is still good law.

### `verify_citation`
Resolves one citation. Supreme Court citations are matched against the dataset's
official `citation` and neutral-citation fields — an exact match, not a text
search — so `[2024] 10 S.C.R. 108` and `2024INSC735` both resolve. Statutory
citations resolve offline against the bundled corpus. Verdicts: `VERIFIED`,
`NOT_FOUND`, `AMBIGUOUS`, `UNCHECKED`. A `NOT_FOUND` explicitly notes that only
synced years were searched.

### `verify_all_citations`
Extracts and verifies every citation in a block of prose. Anything skipped is
returned as `UNCHECKED`, never dropped. Run this over every memo and draft
before presenting it.

### `build_research_memo`
Gathers and de-duplicates authorities across several search phrasings and
returns them with drafting instructions. It assembles an evidence base; it does
not write the analysis.

---

## Statutes

### `get_section`
One section of one Act. **Check `text_kind`**: `authentic` is the statute's own
words; `summary` is a curated paraphrase carrying a caveat and must never be
quoted as statutory text.

### `search_statute`
Find provisions by subject across the corpus, optionally within one Act.

### `map_criminal_code_section`
IPC↔BNS, CrPC↔BNSS, Evidence↔BSA, both directions. Pass `offence_date` and it
also reports which regime governs. `substantive_changes` lists mappings that
changed the law rather than the numbering.

### `which_criminal_code_applies`
Given an offence date, names the governing penal, procedural and evidence
statutes, and flags the savings position for proceedings pending on
1 July 2024.

### `list_bundled_acts`
Corpus coverage. Acts marked `partial` hold curated extracts only.

---

## Limitation and deadlines

### `compute_limitation`
Takes a `claim_type` (from `find_limitation_rule`) and a start date. Applies
section 12(1) (starting day excluded), 12(2) (certified copy time), 14 (bona
fide wrong forum), 18 (acknowledgment) and 4 (expiry on a closed day). Returns
the expiry, days remaining, an `urgency` band, every exclusion applied, the
step-by-step reasoning, and `calendar_confidence`.

Section 18 is handled correctly in both directions: an acknowledgment before
expiry starts a fresh period; one after expiry does not revive the claim, and
the reasoning says so.

### `find_limitation_rule` / `list_limitation_rules`
Discover the applicable rule by description, or list all 31. The catalogue
states that it is curated, not the whole Schedule.

### `compute_cheque_bounce_timeline`
All three section 138 clocks: the 30-day notice deadline (**not extendable**),
the 15-day payment window, and the one-month complaint window. A notice issued
late is marked `MISSED` with an explanation that the complaint is not
maintainable on that dishonour. Includes the section 142(2)(a) jurisdiction
rule.

### `compute_deadline`
Generic date arithmetic, calendar-based for months and years, court-closure
aware, with optional working-day counting.

### `get_court_holidays`
Known closures for a year, and whether a published calendar is installed at
all.

---

## Matters

`create_matter`, `update_matter`, `list_matters`, `get_matter`, `add_hearing`,
`list_upcoming_hearings`, `log_matter_event`, `get_matter_timeline`.

All require PostgreSQL. Creating a matter without a limitation date returns an
explicit prompt to compute one. `list_matters` returns `limitation_alerts` for
anything expiring within 60 days or already past. `get_matter_timeline` merges
the cause of action, filing, events and hearings into one dated chronology.

---

## Documents

### `ingest_document`
PDF, DOCX, TXT or MD. Deduplicates by SHA-256. Chunks on the document's own
clause and heading boundaries. A scanned PDF with no extractable text is
**rejected**, not indexed empty — OCR it first.

### `search_my_documents`
Hybrid Postgres full-text + pgvector cosine, fused by reciprocal rank. The
response reports `search_mode` (`hybrid` or `fulltext_only`) so a weak result
set is never mistaken for a thorough search.

### `get_document` / `list_my_documents`
Retrieve or enumerate. `list_my_documents` reports the embedding status.

### `extract_clauses`
Maps a contract onto a 22-category taxonomy and reports which categories a
commercial contract normally has but this one lacks.

### `review_contract`
Rule-based risk review grounded in Indian statute. High-severity rules include
post-termination non-competes (section 27 Contract Act), uncapped liability,
unlimited indemnities, and arbitration clauses naming a venue but no seat. Each
flag cites its provision. The response states that this is a checklist, not an
opinion on enforceability.

---

## Drafting

### `list_templates`
Templates with their required and optional parameters, procedural checklist,
governing authority and next steps.

### `draft_document`
Renders a template. Missing required parameters return `incomplete` with the
names — the template will not render placeholders into a legal document.
Amounts use Indian digit grouping via the `inr` filter.

### `review_draft`
Checks a draft for unfilled placeholders, missing verification and prayer
clauses, absent limitation and jurisdiction averments, missing affirmation in
an affidavit, and missing dates. Does not check citations — use
`verify_all_citations` for that.

---

## Courts

### `get_case_status`
In the default `manual` mode, returns the portal URL, the steps, and what to
capture. The official eCourts portal is CAPTCHA-gated and this server does not
automate it. Set `ECOURTS_ADAPTER=api` with a licensed provider key for
automated lookups.

### `court_directory`
Supreme Court, Bombay High Court and its benches, main Maharashtra district
courts, and the commonly used tribunals. States that it is not exhaustive.

### `determine_jurisdiction`
Subject-matter, pecuniary and territorial analysis with the governing
provision. Always cautions that pecuniary thresholds move by notification and
are not tracked here.

---

## Adding a tool

1. Write the function in the right `src/tools/*.py` module. Use `async def` for
   I/O, `def` for computation.
2. Give it the structured docstring header (`TOOL_NAME=`, `DISPLAY_NAME=`,
   `USECASE=`, `INSTRUCTIONS=`, `INPUT_DESCRIPTION=`, `OUTPUT_DESCRIPTION=`,
   `EXAMPLES=`, `PREREQUISITES=`, `RELATED_TOOLS=`). This is what MCP clients
   use to choose tools — it is not decoration.
3. Return a dict with `status`; wrap the body in try/except.
4. Put real logic in `domain/` or `sources/`, not in the tool.
5. Append it to that module's `TOOLS` list.
6. Add tests. `tests/test_legal_tools.py` asserts that every registered tool has
   the docstring markers and honours the status contract.
