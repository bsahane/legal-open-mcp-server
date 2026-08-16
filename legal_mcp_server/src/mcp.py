"""Legal MCP Server implementation.

This module contains the main Legal MCP Server class that provides legal
research, drafting, matter-management and document-review tools for Indian
law. It uses FastMCP to register and manage MCP capabilities.
"""

from typing import Any, Callable, Dict, List, Optional

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from legal_mcp_server.src.settings import settings
from legal_mcp_server.utils.pylogger import (
    force_reconfigure_all_loggers,
    get_python_logger,
)

logger = get_python_logger()

SERVER_INSTRUCTIONS = """
You are operating as an experienced Indian legal practitioner's assistant. The
tools on this server give you real sources; your job is to use them rather than
to answer from memory.

JURISDICTION
- Indian law. Default state is {state}; default High Court is the {high_court}
  High Court. Ask before assuming a different forum.
- The Bharatiya Nyaya Sanhita 2023 (BNS), Bharatiya Nagarik Suraksha Sanhita
  2023 (BNSS) and Bharatiya Sakshya Adhiniyam 2023 (BSA) came into force on
  1 July 2024 and replaced the IPC, CrPC and Evidence Act. Which code governs
  depends on the date of the offence, not today's date. When a criminal
  provision is in play, establish the offence date first, then use
  map_criminal_code_section to give the correct provision under both codes.

SOURCING
- Cite the section number, Act name and year for every statutory proposition,
  and the case name with a reported or neutral citation for every judicial one.
- Never state a proposition of law you have not retrieved from a tool. If a
  search returns nothing on point, say "no authority found" - that is a real
  and useful answer.
- Run verify_all_citations over any memo, opinion or draft before presenting
  it. Present anything that comes back UNVERIFIED with its warning intact;
  never quietly reword it into something that reads authoritative.
- Distinguish clearly between settled law, a contested question with a
  division of authority, and your own inference from first principles.

LIMITATION AND PROCEDURE
- Raise limitation unprompted. If a user describes a dispute with a date in it,
  compute the limitation position with compute_limitation before discussing the
  merits - an unanswerable-on-time claim is the most consequential thing you can
  spot early.
- Flag statutory pre-conditions (notice periods, pre-institution mediation,
  pre-deposit) before discussing strategy.

REGISTER
- Give the technical answer first: provisions, authorities, procedure. Then add
  a short plain-language explanation of what it means in practice. The user
  reads both professionally and personally.
- Be direct about weaknesses in the user's position. An assistant that only
  confirms what the user hopes is worse than useless in a dispute.

LIMITS
- This is legal information and drafting assistance, not the advice of an
  engaged advocate, and no lawyer-client relationship arises from it. Say so
  plainly on advisory output - once, briefly, not as a disclaimer wall.
- Recommend engaging an advocate where the matter involves personal liberty,
  an imminent limitation expiry, a court appearance, or sums the user cannot
  afford to lose.
- These tools draft and organise. They never file, send, or serve anything.
""".strip()


def _research_tools() -> List[Callable[..., Any]]:
    """Load the case-law research and citation-verification tool group."""
    from legal_mcp_server.src.tools import research_tools

    return research_tools.TOOLS


def _statute_tools() -> List[Callable[..., Any]]:
    """Load the bare-Act and criminal-code concordance tool group."""
    from legal_mcp_server.src.tools import statute_tools

    return statute_tools.TOOLS


def _deadline_tools() -> List[Callable[..., Any]]:
    """Load the limitation and deadline tool group."""
    from legal_mcp_server.src.tools import deadline_tools

    return deadline_tools.TOOLS


def _matter_tools() -> List[Callable[..., Any]]:
    """Load the matter, hearing and chronology tool group."""
    from legal_mcp_server.src.tools import matter_tools

    return matter_tools.TOOLS


def _document_tools() -> List[Callable[..., Any]]:
    """Load the document ingest, search and review tool group."""
    from legal_mcp_server.src.tools import document_tools

    return document_tools.TOOLS


def _drafting_tools() -> List[Callable[..., Any]]:
    """Load the document drafting tool group."""
    from legal_mcp_server.src.tools import drafting_tools

    return drafting_tools.TOOLS


def _court_tools() -> List[Callable[..., Any]]:
    """Load the court status, directory and jurisdiction tool group."""
    from legal_mcp_server.src.tools import court_tools

    return court_tools.TOOLS


def _annotations_for(fn: Callable[..., Any]) -> Optional[ToolAnnotations]:
    """Return the Connectors-Directory annotations registered for a tool.

    Reads the per-tool metadata declared in ``tool_annotations.py`` and
    materialises it as an MCP ``ToolAnnotations`` object. A tool with no
    declared metadata logs a warning so a missing entry cannot slip through
    silently during directory preparation.
    """
    from legal_mcp_server.src.tool_annotations import TOOL_ANNOTATIONS

    meta = TOOL_ANNOTATIONS.get(fn.__name__)
    if meta is None:
        logger.warning(
            f"Tool '{fn.__name__}' has no declared title/readOnlyHint/destructiveHint; "
            "add it to legal_mcp_server/src/tool_annotations.py"
        )
        return None
    return ToolAnnotations(
        title=meta.get("title"),
        readOnlyHint=meta.get("readOnlyHint"),
        destructiveHint=meta.get("destructiveHint"),
    )


# Tool groups are loaded lazily so that a failure in one group is reported
# against that group by name rather than as an opaque import error.
TOOL_GROUPS: Dict[str, Callable[[], List[Callable[..., Any]]]] = {
    "research": _research_tools,
    "statute": _statute_tools,
    "deadline": _deadline_tools,
    "matter": _matter_tools,
    "document": _document_tools,
    "drafting": _drafting_tools,
    "court": _court_tools,
}


class LegalMCPServer:
    """Main Legal MCP Server implementation following tools-first architecture.

    This server provides only tools, not resources or prompts, adhering to
    the tools-first architectural pattern for MCP servers.
    """

    def __init__(self):
        """Initialize the MCP server with legal tools following tools-first architecture."""
        try:
            self.mcp = FastMCP(
                "legal",
                instructions=SERVER_INSTRUCTIONS.format(
                    state=settings.DEFAULT_STATE,
                    high_court=settings.DEFAULT_HIGH_COURT,
                ),
            )

            # Force reconfigure all loggers after FastMCP initialization to ensure structured logging
            force_reconfigure_all_loggers(settings.PYTHON_LOG_LEVEL)

            self._register_mcp_tools()

            logger.info("Legal MCP Server initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Legal MCP Server: {e}")
            raise

    def _register_mcp_tools(self) -> None:
        """Register every legal tool group with the FastMCP server instance.

        Groups are declared in TOOL_GROUPS; each returns a list of plain
        functions carrying the structured tool docstrings that MCP clients
        use for tool selection.
        """
        registered = 0
        for group, loader in TOOL_GROUPS.items():
            try:
                for fn in loader():
                    self.mcp.tool(annotations=_annotations_for(fn))(fn)
                    registered += 1
            except Exception as e:
                logger.error(f"Failed to register '{group}' tools: {e}")
                raise

        logger.info(f"Registered {registered} legal tools")
