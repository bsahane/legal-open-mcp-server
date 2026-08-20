<!-- bmad:context -->
<!-- Verified 2026-08-20 against e35704e. Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## legal-mcp

MCP server and legal research/drafting assistant for Indian law. Python 3.12+, FastMCP 2, FastAPI, Pydantic, DuckDB, asyncpg. Built on the [Red Hat template-mcp-server](https://github.com/redhat-data-and-ai/template-mcp-server) pattern. Architecture and docs live in `docs/`.

## Policy

- Never commit secrets, API keys, or `.env` — use environment variables via `.env.example`.
- Security vulnerabilities go through GitHub Security Advisories, never public issues.

## Where things are

- MCP tool modules: `legal_mcp_server/src/tools/` — each file exports a `TOOLS` list registered in `legal_mcp_server/src/mcp.py`
- Domain logic (citations, limitation, criminal codes): `legal_mcp_server/src/domain/`
- Data sources (Indian Kanoon, open judgments, eCourts, embeddings): `legal_mcp_server/src/sources/`
- OAuth flow: `legal_mcp_server/src/oauth/`
- Settings and env loading: `legal_mcp_server/src/settings.py`
- Jinja templates and manifest: `legal_mcp_server/src/templates/`
- Bundled corpus data: `data/`; build with `make corpus`
- Deployment (OpenShift): `deployment/openshift/`
- Tool docstring format guide: `legal_mcp_server/src/tools/README.md`

## Running and verifying

- Use `uv run pytest` (or `make test`) — do not run bare `pytest`, which resolves outside the project venv.
- CI also runs `pre-commit run --all-files` (ruff, mypy, pydocstyle, bandit); `make test` alone does not cover this — run `make pre-commit` locally before pushing.
- Coverage must stay ≥ 80% (`--cov-fail-under=80`).
- Local server: `make local` (port 5001). Container: `make container` (podman compose).
- Corpus must be built before case-law tools work: `make corpus`.

## Conventions that differ from defaults

- Every new tool function must be added to its module's `TOOLS` list **and** given an entry in `legal_mcp_server/src/tool_annotations.py` — a missing annotation logs a warning at startup.
- Tool docstrings use the structured `TOOL_NAME=…` / `DISPLAY_NAME=…` / `USECASE=…` format described in `legal_mcp_server/src/tools/README.md`, not plain Google-style.
- All tool functions return `Dict[str, Any]` with a `status` field (`"success"` or `"error"`).
- Logging uses `legal_mcp_server.utils.pylogger.get_python_logger()`, not stdlib `logging` directly.
- Google-convention docstrings enforced by pydocstyle; double-quote strings enforced by Ruff.

## Known pitfalls

- Root-level `*.py` files (`patch.py`, `fix_indent.py`, `new_block.py`, etc.) are throwaway agent artifacts — ignore them, do not import from them.
- DuckDB must be imported eagerly before any `mock.patch(dict)` on `sys.modules` in tests — see `tests/conftest.py` for the workaround and its explanation.
- The `Makefile` test target uses `.venv/bin/python -m pytest`, not a bare `pytest` — match this when adding test targets.

<!-- /bmad:context -->
