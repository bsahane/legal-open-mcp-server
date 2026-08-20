# Privacy Policy

_Last updated: 16 August 2026_

## Overview

The Legal MCP Server ("the Service") is a personal legal-research, drafting and
matter-management assistant for Indian law. It is an MCP (Model Context
Protocol) server: a program your AI assistant connects to in order to use legal
tools. This policy describes what the Service stores, what it sends elsewhere,
and what it never does with your information.

## What the Service processes

When you use the Service through an MCP client (Claude Code, OpenCode, Claude
Desktop, or a custom connector), the client sends the Service:

- **Queries and document text** you choose to submit to its tools, for example
  the facts of a dispute, a contract to review, or a draft to check.
- **Matter data** you choose to create and maintain (matter names, parties,
  hearing dates, event notes).
- **Document files** you explicitly choose to ingest for storage and search.

The Service processes this data only to answer the request you made. It does
not use your data to train models, and it does not share your data with any
third party other than as described below.

## Where data lives

- **Matters, hearings, documents and full-text search** are stored in a
  PostgreSQL database owned and operated by the operator of the Service
  instance you are connected to.
- **Ingested documents** are stored as files alongside that database.
- **Case-law metadata and cached judgments** (the public AWS Open Data corpus of
  Indian judgments) are stored locally on the Service's own storage. This is
  public court data, not your data.

## What leaves the machine, and when

The Service is designed to keep your data on its own storage. The only
outbound requests it makes are:

1. **Judgment fetches.** When you open a judgment, the Service downloads the
   PDF from the public AWS Open Data bucket (the Indian Supreme Court / High
   Court judgments corpus) and caches it locally.
2. **Optional case-law synchronization.** `sync_case_law` downloads public
   Parquet metadata from the same public corpus.
3. **Optional embedding calls.** If you enable an embedding provider (the
   default is `disabled`), document chunks are sent to that provider solely to
   generate search vectors. The default configuration sends nothing.
4. **Optional third-party case-status lookups.** If you configure a licensed
   case-status API, queries are sent to that provider. The default
   (`manual`) sends nothing.
5. **Search queries and citation checks** sent to any paid case-law backend you
   opt into (the default `open_data` backend is local and offline).

When connected through an Anthropic custom connector, your client relays
requests to the Service over the public internet; the Service itself still
follows the rules above.

## What the Service never does

- It never files, serves, sends, or emails anything on your behalf.
- It never defeats CAPTCHAs or automates the official eCourts portal.
- It never sends matter or document content to any third party except the
  explicit, optional integrations listed above.
- It never sends prompts, chats, or conversation history anywhere. MCP tools
  receive only the arguments you pass them.

## Data retention and deletion

- You may delete matters, hearings, events and documents through the Service's
  own tools, or by asking the operator of your instance to remove them from its
  database and document store.
- Deleted records are removed from the database; file caches (for example
  downloaded public judgment PDFs) are overwritten or removed on operator
  request.

## Security

- All public connections to the Service use HTTPS (TLS).
- Authentication is optional and disabled by default for local use; the
  operator of your instance decides whether it is enabled and how access is
  controlled.
- The operator of each instance is responsible for the security of the
  PostgreSQL database and document store that instance uses.

## Important legal note

The Service provides legal information and drafting assistance. It is **not**
legal advice, and using it does not create a lawyer-client relationship. Do not
submit privileged or confidential material to a Service instance you do not
control.

## Changes to this policy

Material changes will be reflected by updating the "Last updated" date above
and, where practical, by notifying the operator of your instance.

## Contact

For privacy questions about a specific instance, contact the operator of that
instance. For questions about the software itself, raise an issue in the
project repository.
