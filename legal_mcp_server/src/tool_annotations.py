"""Tool annotation metadata for the Claude Connectors Directory.

Every tool this server exposes must carry a human-readable ``title`` and a
safety annotation - either ``readOnlyHint`` or ``destructiveHint`` - to
satisfy the Claude Connectors Directory review criteria and the MCP tool
annotation conventions.

This module is the single source of truth for that metadata. ``mcp.py`` reads
it at registration time and attaches a ``ToolAnnotations`` object to each tool
exposed over the wire.

Conventions used here:

* ``readOnlyHint=True``: the tool only reads and returns information. It has
  no side effects - no writes, downloads, creation or mutation of persistent
  state. All computation is pure.
* ``destructiveHint=True``: the tool writes, downloads, creates, updates or
  otherwise changes persistent state (the case-law corpus, PostgreSQL, or the
  document store).
"""

from typing import Any, Dict

TOOL_ANNOTATIONS: Dict[str, Dict[str, Any]] = {
    # --- Research and citations ---
    "search_case_law": {"title": "Search Indian case law", "readOnlyHint": True},
    "get_judgment": {"title": "Get a full judgment", "readOnlyHint": True},
    "search_within_judgment": {
        "title": "Search within a judgment",
        "readOnlyHint": True,
    },
    "find_related_proceedings": {
        "title": "Find related proceedings",
        "readOnlyHint": True,
    },
    "verify_citation": {"title": "Verify a legal citation", "readOnlyHint": True},
    "verify_all_citations": {
        "title": "Verify all citations in a text",
        "readOnlyHint": True,
    },
    "build_research_memo": {"title": "Build a research memo", "readOnlyHint": True},
    "sync_case_law": {
        "title": "Sync the case-law corpus",
        "destructiveHint": True,
    },
    "case_law_status": {"title": "Show case-law corpus status", "readOnlyHint": True},
    # --- Statutes and the new criminal codes ---
    "get_section": {"title": "Get a statute section", "readOnlyHint": True},
    "search_statute": {"title": "Search statutes", "readOnlyHint": True},
    "map_criminal_code_section": {
        "title": "Map a criminal code section",
        "readOnlyHint": True,
    },
    "which_criminal_code_applies": {
        "title": "Decide which criminal code applies",
        "readOnlyHint": True,
    },
    "list_bundled_acts": {"title": "List bundled Acts", "readOnlyHint": True},
    # --- Limitation and deadlines ---
    "compute_limitation": {"title": "Compute a limitation period", "readOnlyHint": True},
    "find_limitation_rule": {
        "title": "Find a limitation rule",
        "readOnlyHint": True,
    },
    "list_limitation_rules": {
        "title": "List limitation rules",
        "readOnlyHint": True,
    },
    "compute_cheque_bounce_timeline": {
        "title": "Compute a cheque-bounce timeline",
        "readOnlyHint": True,
    },
    "compute_deadline": {"title": "Compute a deadline", "readOnlyHint": True},
    "get_court_holidays": {"title": "Get court holidays", "readOnlyHint": True},
    # --- Matters and hearings ---
    "create_matter": {"title": "Create a matter", "destructiveHint": True},
    "update_matter": {"title": "Update a matter", "destructiveHint": True},
    "list_matters": {"title": "List matters", "readOnlyHint": True},
    "get_matter": {"title": "Get a matter", "readOnlyHint": True},
    "add_hearing": {"title": "Add a hearing", "destructiveHint": True},
    "list_upcoming_hearings": {
        "title": "List upcoming hearings",
        "readOnlyHint": True,
    },
    "log_matter_event": {"title": "Log a matter event", "destructiveHint": True},
    "get_matter_timeline": {"title": "Get a matter timeline", "readOnlyHint": True},
    # --- Your documents ---
    "ingest_document": {"title": "Ingest a document", "destructiveHint": True},
    "search_my_documents": {"title": "Search my documents", "readOnlyHint": True},
    "list_my_documents": {"title": "List my documents", "readOnlyHint": True},
    "get_document": {"title": "Get a document", "readOnlyHint": True},
    "extract_clauses": {"title": "Extract clauses from text", "readOnlyHint": True},
    "review_contract": {"title": "Review a contract", "readOnlyHint": True},
    # --- Drafting ---
    "list_templates": {"title": "List document templates", "readOnlyHint": True},
    "draft_document": {"title": "Draft a document", "readOnlyHint": True},
    "review_draft": {"title": "Review a draft", "readOnlyHint": True},
    "get_document_languages": {
        "title": "Get document languages",
        "readOnlyHint": True,
    },
    "translate_document": {"title": "Translate a draft", "readOnlyHint": True},
    # --- Courts and jurisdiction ---
    "get_case_status": {"title": "Get case status", "readOnlyHint": True},
    "court_directory": {"title": "Court directory", "readOnlyHint": True},
    "determine_jurisdiction": {
        "title": "Determine jurisdiction",
        "readOnlyHint": True,
    },
}
