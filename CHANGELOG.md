# Changelog

All notable changes to this project will be documented in this file.

This project uses [GitHub Releases](https://github.com/redhat-data-and-ai/legal-mcp-server/releases) for detailed changelogs. Release notes are auto-generated from merged pull request titles and labels.

## [Unreleased]

### Changed

- Case-law full-text search now uses a SQLite FTS5 index
  (`data/case_law/fts/corpus.sqlite`) instead of DuckDB's `fts` extension.
  DuckDB's `match_bm25` scored every row of the 16M-row corpus on every query
  (20-50s on a 2-core host); FTS5 answers from its inverted index. Search
  terms are prefix matches over title and description, and the court filter
  is matched inside the index. Rebuild with `make fts`; the old
  `corpus.duckdb` file is no longer read and can be deleted.
- `build_fts_index()` (and the nightly sync) now re-indexes only the Parquet
  files that are new, changed or removed since the last build, in place.
  A nightly update takes seconds instead of a 30-minute full build and needs
  no disk for a second copy of the index. `force=True` (`make fts`) still
  does a full rebuild; an index built before per-file tracking gets one
  automatically.
- Case-law queries matching more than 100,000 judgments are listed newest
  first instead of BM25-ranked, with `ordering: "newest_first"` and a notice
  asking for narrower terms; BM25 had to score every match (15-35s for
  "india" or "criminal appeal"). The index assigns rowids in decision-date
  order so this is a cheap walk. Queries of only common words ("state") now
  use the index instead of the full LIKE scan. Date filters on broad
  queries become rowid ranges (binary search over the date-ordered rowids
  recorded in `fts_meta`), so they stay fast too; a judge filter keeps the
  exact ranked path. Source files are stored as
  integer ids, shrinking the index by about 3 GB. Needs one full rebuild
  (`make fts`); the next update triggers it automatically.
- uvicorn no longer loads websocket support (`ws="none"`); no MCP transport
  uses it, and it pulled in the deprecated `websockets.legacy` module.

### Fixed

- Cached case-law searches are keyed on the corpus version (index and
  newest metadata mtime), so a sync or index update no longer leaves
  pre-update answers in the 24-hour search cache.
- Root-cause fixed: `_configure_third_party_loggers` cleared **all** root
  logger handlers on every `get_python_logger()` call (i.e. on every module
  import with a module-level logger), silently dropping all INFO records from
  modules imported afterwards — this is why unattended FTS builds produced
  empty logs. The app logger hierarchy is also pinned into the uvicorn
  `dictConfig`, so application records no longer depend on mutable root
  handler state at all.
- Bounded graceful shutdown: uvicorn now force-closes lingering connections
  after `MCP_GRACEFUL_SHUTDOWN_SECONDS` (default 15s) instead of hanging past
  systemd's 90s stop timeout, and the lifespan shutdown releases the
  open-data corpus client (DuckDB + HTTP), the Indian Kanoon client and the
  search disk cache deterministically.
- The FTS build logs its phases (parquet scan, corpus table, FTS5 index)
  and caps the DuckDB Parquet scan's memory at ~60% of RAM (max 8 GB), so unattended
  builds leave a trail instead of dying silently; `build_fts_index.py` now
  flushes output and exits non-zero on failure.
- The nightly sync reports elapsed time and row counts for the FTS rebuild,
  including failures.

### Added

- `scripts/healthcheck.py`: hourly check of `/health`, disk usage and the
  last nightly sync report (now written to
  `data/daily_sync_report.json`); problems go to syslog and, if
  `LEGAL_MCP_ALERT_URL` is set, are POSTed there (ntfy-compatible), once a
  day per distinct problem.
- `deployment/lxc/deploy.sh`: fast-forward a git checkout, re-sync the
  virtualenv only when dependencies changed, restart, and wait for health.

- Pagination on the free open-data case-law backend: `search_case_law` now
  accepts `page` on every backend, so deep result sets are reachable without
  the paid Indian Kanoon API.
- 24-hour disk cache for citation verification: repeated sweeps of unchanged
  citations no longer re-hit sources or re-incur paid calls.
- Retry with exponential backoff for S3 metadata and judgment-PDF fetches on
  the open-data backend (429/5xx and transient network errors).
- The nightly sync (`scripts/daily_sync.py`) now rebuilds the BM25 FTS index
  after pulling new judgments, instead of silently degrading search to LIKE
  scans until `make fts` was run by hand.
- The Indian Kanoon daily spend ledger persists to
  `<LEGAL_DATA_PATH>/cache/indian_kanoon_spend.json`, so restarting the server
  cannot bypass the configured INR cap.
- `search_my_documents` names both embedding options (the `local` and `voyage`
  extras) when semantic search is disabled.

### Changed

- The pytest coverage floor (80%) is enforced by `uv run pytest` directly, not
  only via `make coverage`.

## [0.1.0] - 2026-02-09

### Added

- Initial release of Legal MCP Server.
- MCP server implementation with FastMCP and FastAPI.
- Example tools: multiply numbers, code review prompt generator, Red Hat logo resource.
- OAuth integration with PostgreSQL-backed token storage.
- Multiple transport protocols: HTTP, SSE, streamable-HTTP.
- SSL/TLS support.
- Structured JSON logging with structlog.
- Pydantic-based configuration management.
- Containerized deployment with Red Hat UBI9 base image.
- OpenShift deployment support.
- Comprehensive test suite with 80%+ coverage.
- Pre-commit hooks: Ruff, MyPy, pydocstyle, Bandit.
- GitHub Actions CI workflows for tests and pre-commit.

[Unreleased]: https://github.com/redhat-data-and-ai/legal-mcp-server/compare/0.1.0...HEAD
[0.1.0]: https://github.com/redhat-data-and-ai/legal-mcp-server/releases/tag/0.1.0

### Legal-domain milestones (pre-1.0, from git history)

The template-era 0.1.0 release grew into the legal product in these steps:

- **2026-08-03** — Replaced the paid case-law API with the free AWS Open Data
  judgment corpus (SC + all High Courts, CC-BY-4.0 attribution).
- **2026-08-16** — Connectors Directory annotations and privacy policy; daily
  data-sync script covering the full corpus from 1950; pre-1950 Bombay High
  Court digitized archive; live recent-judgments harvest bridging the
  open-data publication lag; multilingual court-format drafting (en/hi/mr/ta/te).
- **2026-08-17** — Formatted legal notice templates with advocate branding and
  five more court-format templates.
- **2026-08-20** — DuckDB BM25 full-text search over the synced corpus plus the
  research performance work (bounded-concurrency citation sweeps, disk cache
  for case-law searches).
