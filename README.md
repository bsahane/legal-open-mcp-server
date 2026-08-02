# Legal MCP Server

[![Python 3.12+](https://img.shields.io/badge/python-3.12,3.13-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

An MCP server that turns Claude into a working legal assistant for **Indian
law** — case-law research with verified citations, limitation and deadline
arithmetic, document drafting, matter tracking, and search over your own
contracts and case files.

Built on Red Hat's
[template-mcp-server](https://github.com/redhat-data-and-ai/template-mcp-server)
(FastMCP + FastAPI, OAuth, PostgreSQL, Containerfile, OpenShift, CI).

Defaults to **Maharashtra / Bombay High Court**; every tool takes an explicit
jurisdiction where it matters.

---

## The problem this is built around

An LLM asked a legal question will produce a fluent answer containing citations
that look exactly like real ones. Some of them will not exist. In legal work
that is not a rough edge — it is the whole risk.

So the design rule throughout is: **the server distinguishes what it knows from
what it does not, and never closes the gap on its own.**

- Case law comes from a real lookup against Indian Kanoon, or the tool reports
  `unavailable`. "The source could not be consulted" is never rendered as "no
  authority exists".
- `verify_all_citations` sweeps any draft or memo and marks every citation
  `VERIFIED`, `NOT_FOUND`, `AMBIGUOUS` or `UNCHECKED`. Nothing is quietly
  dropped or reworded.
- Statutory text is labelled `authentic` or `summary`. A curated paraphrase is
  never presentable as the words of a statute.
- A section missing from a *partially* bundled Act reports "not in the corpus",
  not "does not exist".
- Deadline results carry a `calendar_confidence` block saying which court
  holidays were actually accounted for.
- Templates refuse to render with a placeholder where a fact should be.

---

## What it does

**39 tools in seven groups.**

### Research and citations
`search_case_law` · `get_judgment` · `search_within_judgment` ·
`find_citing_cases` · `verify_citation` · `verify_all_citations` ·
`build_research_memo` · `get_research_budget_status`

Indian Kanoon's ~30M judgments, with a per-day spend cap and response caching so
a research loop cannot run up a bill.

### Statutes and the new criminal codes
`get_section` · `search_statute` · `map_criminal_code_section` ·
`which_criminal_code_applies` · `list_bundled_acts`

**2,040 sections across 19 Acts bundled offline** — free, fast, no network. The
BNS/BNSS/BSA came into force on 1 July 2024, and *the date of the offence*, not
today's date, decides which code governs. The concordance covers 103 of the
most-used provisions in both directions and flags the ones that are substantive
changes rather than renumberings (CrPC 200 → BNSS 223, Evidence 65B → BSA 63).

### Limitation and deadlines
`compute_limitation` · `find_limitation_rule` · `list_limitation_rules` ·
`compute_cheque_bounce_timeline` · `compute_deadline` · `get_court_holidays`

Limitation Act 1963 with sections 4, 12(1), 12(2), 14 and 18 modelled — an
acknowledgment before expiry restarts the clock, one after it does not revive a
time-barred claim, and the tool says which rule it applied and why.
`compute_cheque_bounce_timeline` handles all three section 138 clocks and is
loud about the fact that the 30-day notice period cannot be extended.

### Matters and hearings
`create_matter` · `update_matter` · `list_matters` · `get_matter` ·
`add_hearing` · `list_upcoming_hearings` · `log_matter_event` ·
`get_matter_timeline`

Your matters in your own PostgreSQL. `list_matters` surfaces limitation alerts
unprompted.

### Your documents
`ingest_document` · `search_my_documents` · `list_my_documents` ·
`get_document` · `extract_clauses` · `review_contract`

PDF/DOCX/TXT/MD ingest, chunked on the document's own clause boundaries.
Hybrid search (Postgres full-text + pgvector, reciprocal-rank fused).
`review_contract` applies India-specific rules — section 27 on post-termination
non-competes, section 28 on jurisdiction clauses, seat-versus-venue in
arbitration clauses, unstamped instruments — each citing the provision it rests
on.

### Drafting
`list_templates` · `draft_document` · `review_draft`

Six templates in correct Indian form: section 138 NI Act notice, general legal
notice, reply to notice, Consumer Protection Act complaint, RTI application,
general affidavit. Each carries its own procedural checklist and next steps.
Amounts use Indian digit grouping (₹2,00,000, not ₹200,000).

### Courts and jurisdiction
`get_case_status` · `court_directory` · `determine_jurisdiction`

---

## Quick start

```bash
make install
```

```bash
make corpus
```

```bash
cp .env.example .env
```

Set `ENABLE_AUTH=False` in `.env` for local use, then:

```bash
make local
```

Register it with Claude Code:

```bash
claude mcp add legal --transport http http://localhost:5001/mcp
```

Everything except case law, document storage and semantic search works with no
API key and no database.

### Optional capabilities

| Capability | Needs | Without it |
|---|---|---|
| Case law + case-citation verification | `INDIAN_KANOON_API_KEY` ([₹500 free credit](https://api.indiankanoon.org/)) | Tools report `unavailable` |
| Matters, hearings, documents | PostgreSQL (`podman compose up postgres`) | Tools report `unavailable` |
| Semantic document search | `EMBEDDING_PROVIDER=voyage` + `VOYAGE_API_KEY`, or `=local` | Full-text search only |
| Automated case status | A licensed provider key + `ECOURTS_ADAPTER=api` | Portal instructions for you to follow |
| Festival/vacation court holidays | A calendar at `data/reference/court_holidays.json` | Weekends + fixed national holidays only, with the gap disclosed |

Install an embedding backend with `uv pip install -e ".[voyage]"` or
`".[local]"`.

---

## Try it

> A cheque for ₹2,00,000 was dishonoured on 15 July 2026. What are my
> deadlines, draft the notice, and find Bombay High Court authority on
> territorial jurisdiction.

This chains `compute_cheque_bounce_timeline` → `get_section` →
`draft_document` → `search_case_law` → `verify_all_citations`.

---

## Architecture

```
legal_mcp_server/src/
├── mcp.py          LegalMCPServer; carries the advocate persona as FastMCP instructions
├── settings.py     Pydantic settings, extended with the legal configuration
├── domain/         Pure logic, no I/O — the most valuable and most testable code
│   ├── citations.py           Indian citation parsing (AIR, SCC, SCC OnLine, neutral)
│   ├── limitation.py          Limitation Act 1963 + special statutory periods
│   ├── holidays.py            Court closures and calendar confidence
│   ├── new_criminal_codes.py  IPC-BNS, CrPC-BNSS, Evidence-BSA concordance
│   └── clause_rules.py        Contract taxonomy and India-specific risk rules
├── sources/        External adapters, mockable, MCP-unaware
│   ├── indian_kanoon.py  Budget cap, cache, honest failure
│   ├── india_code.py     Bundled corpus with explicit coverage
│   ├── ecourts.py        Pluggable; no CAPTCHA automation
│   └── embeddings.py     voyage-law-2 | fastembed | disabled
├── storage/        legal_store.py owns its own pool and schema
├── templates/      Jinja2 documents + manifest.yaml
└── tools/          Thin MCP adapters over the above
```

Tool modules are deliberately thin. Legal logic lives in `domain/`, which needs
no network or database to test — hence 98% coverage on limitation and citation
parsing.

The server's `instructions` (in `mcp.py`) carry the practitioner brief the
client reads on connect: cite everything, raise limitation unprompted, be
direct about weaknesses, and say plainly that this is information rather than
the advice of an engaged advocate.

---

## Configuration

Every setting is documented in [`.env.example`](.env.example). The ones that
change behaviour most:

| Variable | Default | Effect |
|---|---|---|
| `INDIAN_KANOON_API_KEY` | unset | Enables case law. Without it those tools report `unavailable`. |
| `INDIAN_KANOON_DAILY_BUDGET_INR` | `100` | Hard daily spend cap. `0` disables all paid calls. |
| `ENABLE_CITATION_VERIFICATION` | `True` | Leave on. Off means citations are not checked, and the tools say so. |
| `EMBEDDING_PROVIDER` | `disabled` | `voyage` \| `local` \| `disabled` |
| `ECOURTS_ADAPTER` | `manual` | `manual` \| `api` \| `disabled` |
| `DEFAULT_STATE` / `DEFAULT_HIGH_COURT` | `Maharashtra` / `Bombay` | Jurisdiction defaults in the persona and tools |
| `LEGAL_DATA_PATH` | `./data` | Where the bundled corpus lives |

---

## Development

```bash
make test
```

```bash
make lint
```

```bash
make coverage
```

512 tests, 82% coverage, ruff and mypy clean.

```bash
make container
```

```bash
make deploy openshift NAMESPACE=legal-mcp
```

Run `make corpus` before building the image — the Containerfile copies `data/`,
and without it every statutory lookup reports itself as unavailable. The compose
file uses `pgvector/pgvector:pg16`; plain Postgres works but disables semantic
search.

Further guides live in [`docs/`](docs/): architecture, development,
deployment, authentication and CI/CD.

---

## Deliberate limits

- **Not legal advice.** This is legal information and drafting assistance. No
  lawyer-client relationship arises from it. For anything involving personal
  liberty, an imminent limitation date, a court appearance, or money you cannot
  afford to lose, engage an advocate.
- **No CAPTCHA bypass.** The official eCourts portal is CAPTCHA-gated. This
  server will not defeat that. Case status is manual-entry by default, or a
  licensed third-party API if you supply a key.
- **It never sends anything.** No filing, no service, no email. It drafts and
  organises; you decide what leaves the building.
- **Coverage is bounded and stated.** 19 Acts, 103 concordance mappings, 31
  limitation rules — each tool reports what it does not cover rather than
  extrapolating.
- **Your data stays yours.** Matters and documents live in your PostgreSQL.
  Only search queries and citation checks leave the machine, plus chunk text to
  the embedding provider — which is why `EMBEDDING_PROVIDER=local` exists.

---

## Sources

- [redhat-data-and-ai/template-mcp-server](https://github.com/redhat-data-and-ai/template-mcp-server) — Apache 2.0
- [Indian Kanoon API](https://api.indiankanoon.org/) · [pricing](https://api.indiankanoon.org/pricing/)
- [India Code](https://www.indiacode.nic.in/) — authentic bare Act text
- [civictech-India/Indian-Law-Penal-Code-Json](https://github.com/civictech-India/Indian-Law-Penal-Code-Json) — the open corpus `make corpus` fetches
- [eCourts Services](https://services.ecourts.gov.in/ecourtindia_v6/)

## License

Apache 2.0
