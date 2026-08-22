# Changelog

All notable changes to this project will be documented in this file.

This project uses [GitHub Releases](https://github.com/redhat-data-and-ai/legal-mcp-server/releases) for detailed changelogs. Release notes are auto-generated from merged pull request titles and labels.

## [Unreleased]

### Added

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
