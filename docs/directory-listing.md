# Claude Connectors Directory — Submission Kit

This document is the scaffolding for submitting the Legal MCP Server to the
[Claude Connectors Directory](https://claude.com/connectors). Fill in the
placeholders marked `TODO` before you submit, then use the answers to complete
the form in the [submission portal](https://claude.ai/admin-settings/directory/submissions/new).

Pre-submission checklist (from the
[official guidelines](https://claude.com/docs/connectors/building/review-criteria)):

- [x] Public HTTPS endpoint — `https://legal-mcp.tech247.in/mcp` (Streamable HTTP)
- [x] Every tool has a `title` plus `readOnlyHint` or `destructiveHint` (see
      `legal_mcp_server/src/tool_annotations.py`)
- [ ] OAuth 2.0 enabled on the production endpoint (currently `ENABLE_AUTH=False`)
- [x] Public privacy policy — `PRIVACY.md` (publish to a live URL before submission)
- [ ] Public documentation hosted at a URL (start from `README.md`, publish a rendered copy)
- [ ] Support contact / channel
- [ ] Reviewer demo account with sample data
- [ ] Logo and favicon assets

---

## Submission form answers

### Identity

| Field | Value |
|---|---|
| **Server name** | legal-mcp |
| **Tagline** | Indian case-law research, limitation arithmetic and legal drafting with verified citations |
| **Description** | An MCP server that turns Claude into a working legal assistant for Indian law: case-law research with verified citations, limitation and deadline arithmetic, document drafting, matter tracking, and search over your own contracts and case files. Defaults to Maharashtra / Bombay High Court; every tool takes an explicit jurisdiction where it matters. Free offline corpus — no API key. |
| **URL** | `https://legal-mcp.tech247.in/mcp` |
| **Transport** | Streamable HTTP (POST) |
| **Auth type** | TODO: OAuth 2.0 (required once auth is enabled) |

### Use cases

1. Research an Indian legal question and get citations that can be verified
   against the official record (`search_case_law`, `verify_citation`).
2. Compute whether a claim is time-barred and draft the section 138 NI Act
   notice before the deadline runs (`compute_cheque_bounce_timeline`,
   `draft_document`).
3. Map a pre-2024 IPC/CrPC/Evidence Act offence to the new BNS/BNSS/BSA
   provision that governs it from 1 July 2024 (`map_criminal_code_section`).
4. Review a contract against India-specific rules — section 27 non-competes,
   section 28 jurisdiction clauses, unstamped instruments (`review_contract`).
5. Track matters, hearings and limitation alerts in your own PostgreSQL
   (`create_matter`, `list_matters`).

### Capabilities

- **Read-only tools (30):** search case law, get judgments, verify citations,
  compute limitation/deadlines/holidays, read statutes, list matters, search
  documents, review contracts and drafts, determine jurisdiction, etc.
- **Write tools (6):** `sync_case_law` (downloads the public corpus),
  `create_matter`, `update_matter`, `add_hearing`, `log_matter_event`
  (PostgreSQL), `ingest_document` (document store). All marked
  `destructiveHint: true`.

### Tool list (human-readable names)

Research and citations: Search Indian case law · Get a full judgment · Search
within a judgment · Find related proceedings · Verify a legal citation ·
Verify all citations in a text · Build a research memo · Sync the case-law
corpus · Show case-law corpus status.

Statutes: Get a statute section · Search statutes · Map a criminal code section
· Decide which criminal code applies · List bundled Acts.

Limitation and deadlines: Compute a limitation period · Find a limitation rule ·
List limitation rules · Compute a cheque-bounce timeline · Compute a deadline ·
Get court holidays.

Matters and hearings: Create a matter · Update a matter · List matters · Get a
matter · Add a hearing · List upcoming hearings · Log a matter event · Get a
matter timeline.

Documents: Ingest a document · Search my documents · List my documents · Get a
document · Extract clauses from text · Review a contract.

Drafting: List document templates · Draft a document · Review a draft.

Courts and jurisdiction: Get case status · Court directory · Determine
jurisdiction.

### Data handling (privacy)

Public privacy policy: `PRIVACY.md` (publish to a live URL, e.g.
`https://legal-mcp.tech247.in/privacy`, before submitting). The server stores
matters and documents in its own PostgreSQL and document store, fetches public
judgments from AWS Open Data, and — with the default configuration — sends no
user data to any third party.

### Support

- **Support contact:** TODO (email / channel)
- **Documentation:** TODO (hosted copy of `README.md`)
- **Demo account / test credentials:** TODO (sample matters and documents
  seeded for reviewers)

### Branding

- **Logo:** TODO (PNG, square)
- **Favicon:** TODO
- **Screenshots:** required only for MCP Apps / desktop extensions, not for a
  plain remote MCP server.

---

## Notes

- Directory listing is free; review takes weeks and the turnaround is not
  published.
- A missing or incomplete privacy policy is an immediate rejection.
- Tool annotations are enforced by the reviewer; keep `tool_annotations.py` in
  sync with any tool added or removed.
- The directory connector connects from Anthropic's cloud, so the endpoint
  must stay publicly reachable and HTTPS.
