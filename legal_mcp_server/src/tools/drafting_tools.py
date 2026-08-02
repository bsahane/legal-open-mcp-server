"""Document drafting tools for the Legal MCP Server.

Templates are Jinja2 files in ``src/templates/documents/`` described by
``src/templates/manifest.yaml``. Each template carries its own procedural
checklist and next steps, so the requirements travel with the document rather
than depending on the model to recall them.

A rendered draft is a starting point. Every draft returned here is accompanied
by its checklist and by an instruction to run the citation sweep before the
document is used.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError

from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "templates"
DOCUMENT_DIR = TEMPLATE_ROOT / "documents"
MANIFEST_PATH = TEMPLATE_ROOT / "manifest.yaml"


@lru_cache(maxsize=1)
def load_manifest() -> Dict[str, Dict[str, Any]]:
    """Load the template manifest, keyed by template key."""
    if not MANIFEST_PATH.is_file():
        logger.error(f"Template manifest not found at {MANIFEST_PATH}")
        return {}

    raw = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8")) or {}
    return {entry["key"]: entry for entry in raw.get("templates", [])}


def inr(value: Any) -> str:
    """Format a number in the Indian digit grouping used in legal documents.

    Indian convention groups the last three digits, then in pairs:
    ``200000`` becomes ``2,00,000``, not ``200,000``. Getting this wrong on a
    demand notice looks careless in exactly the setting where it should not.

    Args:
        value: A number, or a string that parses as one.

    Returns:
        The grouped figure, or the input unchanged if it is not numeric.
    """
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return str(value)

    sign = "-" if number < 0 else ""
    digits = str(abs(number))

    if len(digits) <= 3:
        return f"{sign}{digits}"

    last_three = digits[-3:]
    rest = digits[:-3]
    groups: List[str] = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)

    return f"{sign}{','.join(groups)},{last_three}"


@lru_cache(maxsize=1)
def _environment() -> Environment:
    """Jinja2 environment configured to fail loudly on missing variables."""
    env = Environment(
        loader=FileSystemLoader(str(DOCUMENT_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,  # plain-text legal documents, not HTML
        keep_trailing_newline=True,
    )
    env.filters["inr"] = inr
    return env


def reload_templates() -> None:
    """Drop cached manifest and environment so changes on disk take effect."""
    load_manifest.cache_clear()
    _environment.cache_clear()


def list_templates(category: Optional[str] = None) -> Dict[str, Any]:
    """List the drafting templates available and what each needs.

    TOOL_NAME=list_templates
    DISPLAY_NAME=List Drafting Templates
    USECASE=See what documents can be drafted and exactly which facts each one requires, before gathering instructions from the user
    INSTRUCTIONS=1. Call before drafting, 2. Read the required parameters and collect every one from the user - a template will refuse to render with a placeholder, 3. Read the checklist, which states the procedural pre-conditions
    INPUT_DESCRIPTION=category (string, optional): filter by "notice", "pleading", "application" or "affidavit"
    OUTPUT_DESCRIPTION=Dictionary with status, templates with key, title, description, required and optional parameters, procedural checklist, governing authority and next steps
    EXAMPLES=list_templates(), list_templates(category="notice")
    PREREQUISITES=None
    RELATED_TOOLS=draft_document to render one; review_draft to check a draft against its checklist

    CPU-bound operation - uses def for local manifest inspection.

    Args:
        category: Optional category filter.

    Returns:
        Dict describing the available templates.
    """
    try:
        manifest = load_manifest()
        if not manifest:
            return {
                "status": "unavailable",
                "operation": "list_templates",
                "message": (
                    f"No template manifest found at {MANIFEST_PATH}. Drafting is "
                    "unavailable; do not improvise a document format in its place."
                ),
            }

        entries = [
            entry
            for entry in manifest.values()
            if category is None or entry.get("category") == category
        ]

        return {
            "status": "success",
            "operation": "list_templates",
            "templates": entries,
            "template_count": len(entries),
            "categories": sorted(
                {e.get("category", "other") for e in manifest.values()}
            ),
            "message": (
                f"{len(entries)} templates available. Collect every required "
                "parameter from the user before drafting - these templates fail "
                "rather than render with a placeholder, which is deliberate."
            ),
        }

    except Exception as e:
        logger.error(f"Error in list_templates: {e}")
        return {
            "status": "error",
            "operation": "list_templates",
            "error": str(e),
            "message": "Failed to list templates",
        }


def draft_document(template_key: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Render a legal document from a template and a set of facts.

    TOOL_NAME=draft_document
    DISPLAY_NAME=Draft Legal Document
    USECASE=Produce a notice, complaint, application or affidavit in correct Indian form from facts the user has supplied
    INSTRUCTIONS=1. Call list_templates first to learn the required parameters, 2. Collect every required parameter from the user - never invent names, addresses, amounts or dates, 3. Render, 4. Give the user the draft together with its checklist, 5. Run verify_all_citations over the draft if it cites any authority
    INPUT_DESCRIPTION=template_key (string, required): key from list_templates, e.g. "ni_138_notice". parameters (object, required): the facts, matching the template's required and optional parameters. List parameters such as facts, demands and reliefs take arrays of strings.
    OUTPUT_DESCRIPTION=Dictionary with status, the rendered draft, the template's procedural checklist, governing authority, next steps, and a reminder that the draft is unsigned and unserved
    EXAMPLES=draft_document("rti_application", {"public_authority": "Municipal Corporation of Greater Mumbai", "authority_address": "...", "application_date": "2026-08-02", "information_sought": ["Copy of building plan approval for CTS 123"], "applicant_name": "...", "applicant_address": "..."})
    PREREQUISITES=None - fully offline
    RELATED_TOOLS=list_templates for parameters; review_draft to check the result; compute_cheque_bounce_timeline before a s.138 notice

    CPU-bound operation - uses def for template rendering.

    Args:
        template_key: Which template to render.
        parameters: The facts to render into it.

    Returns:
        Dict with the rendered draft and its checklist.
    """
    try:
        manifest = load_manifest()
        entry = manifest.get(template_key)
        if entry is None:
            return {
                "status": "not_found",
                "operation": "draft_document",
                "template_key": template_key,
                "available": sorted(manifest),
                "message": (
                    f"No template '{template_key}'. Available: "
                    f"{', '.join(sorted(manifest))}. Do not improvise a format - "
                    "ask the user whether one of these fits."
                ),
            }

        if not isinstance(parameters, dict):
            raise ValueError("parameters must be an object")

        required = entry.get("required", [])
        missing = [
            name
            for name in required
            if name not in parameters
            or parameters[name] is None
            or parameters[name] == ""
        ]
        if missing:
            return {
                "status": "incomplete",
                "operation": "draft_document",
                "template_key": template_key,
                "missing_parameters": missing,
                "required_parameters": required,
                "message": (
                    f"Cannot draft: {len(missing)} required parameter(s) missing - "
                    f"{', '.join(missing)}. Ask the user for these. Do not "
                    "substitute placeholders, invented names or specimen amounts "
                    "into a legal document."
                ),
            }

        # StrictUndefined is deliberate: it stops a template rendering with a
        # silent blank where a required fact should be. Declared optional
        # parameters are seeded to None first so that omitting them is fine,
        # while a genuinely unknown name in a template still raises.
        context: Dict[str, Any] = {name: None for name in entry.get("optional", [])}
        context.update(parameters)

        unknown = set(parameters) - set(required) - set(entry.get("optional", []))
        if unknown:
            logger.warning(
                f"Template '{template_key}' received undeclared parameter(s): "
                f"{sorted(unknown)}"
            )

        template = _environment().get_template(entry["file"])
        rendered = template.render(**context)

        logger.info(f"Drafted document from template '{template_key}'")

        return {
            "status": "success",
            "operation": "draft_document",
            "template_key": template_key,
            "title": entry["title"],
            "category": entry.get("category"),
            "draft": rendered,
            "checklist": entry.get("checklist", []),
            "authority": entry.get("authority"),
            "next_steps": entry.get("next_steps", []),
            "message": (
                f"Drafted '{entry['title']}'. Present the checklist to the user "
                "alongside the draft. This document is unsigned and unserved - "
                "this server does not send, file or serve anything."
            ),
            "disclaimer": (
                "A template gets the form right; it cannot tell whether this is "
                "the right document to send. For anything of consequence the "
                "draft should be settled by an advocate before it goes out."
            ),
        }

    except TemplateError as e:
        logger.error(f"Template rendering failed for '{template_key}': {e}")
        return {
            "status": "error",
            "operation": "draft_document",
            "template_key": template_key,
            "error": str(e),
            "message": (
                f"The template could not be rendered: {e}. This usually means a "
                "parameter is missing or is the wrong shape - list parameters such "
                "as facts, demands and reliefs must be arrays of strings."
            ),
        }
    except Exception as e:
        logger.error(f"Error in draft_document: {e}")
        return {
            "status": "error",
            "operation": "draft_document",
            "error": str(e),
            "message": "Failed to draft document",
        }


def review_draft(draft_text: str, template_key: Optional[str] = None) -> Dict[str, Any]:
    """Check a draft for structural and procedural defects before it is used.

    TOOL_NAME=review_draft
    DISPLAY_NAME=Review Draft Document
    USECASE=Catch unfilled placeholders, missing verification, absent limitation pleadings and unmet procedural pre-conditions before a document is signed or filed
    INSTRUCTIONS=1. Pass the draft text, 2. Pass the template_key where the draft came from one, so its specific checklist is applied, 3. Fix every issue reported before the document goes out, 4. Run verify_all_citations separately if the draft cites authority
    INPUT_DESCRIPTION=draft_text (string, required): the full draft. template_key (string, optional): the template it was drafted from.
    OUTPUT_DESCRIPTION=Dictionary with status, structural issues found with severity, the template's procedural checklist, and a summary
    EXAMPLES=review_draft(draft_text, template_key="consumer_complaint"), review_draft(pasted_notice_text)
    PREREQUISITES=None - fully offline
    RELATED_TOOLS=verify_all_citations for the authorities cited; draft_document to produce a compliant draft in the first place

    CPU-bound operation - uses def for pattern checks.

    Args:
        draft_text: The draft to review.
        template_key: Template the draft was produced from, if any.

    Returns:
        Dict with the issues found and the applicable checklist.
    """
    try:
        if not draft_text or not draft_text.strip():
            raise ValueError("draft_text must be a non-empty string")

        import re

        issues: List[Dict[str, str]] = []
        text = draft_text
        lowered = text.lower()

        placeholder_patterns = [
            (r"\{\{.*?\}\}", "An unrendered Jinja placeholder remains in the text"),
            (
                r"\[\s*(?:insert|name|address|date|amount|xxx)[^\]]*\]",
                "A bracketed placeholder has not been filled in",
            ),
            (r"\bXXX+\b", "A literal XXX placeholder remains"),
            (
                r"\bTBD\b|\bTO BE (?:FILLED|DECIDED)\b",
                "A 'to be decided' marker remains",
            ),
            (r"\bLorem ipsum\b", "Filler text remains in the document"),
        ]
        for pattern, description in placeholder_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                issues.append(
                    {
                        "severity": "high",
                        "issue": description,
                        "excerpt": match.group(0)[:80],
                    }
                )
                break  # one report per pattern is enough

        if re.search(r"\b(?:complaint|petition|plaint|application)\b", lowered):
            if "verification" not in lowered and "verify" not in lowered:
                issues.append(
                    {
                        "severity": "high",
                        "issue": (
                            "This reads as a pleading but has no verification "
                            "clause. An unverified pleading is liable to be "
                            "returned."
                        ),
                        "excerpt": "(no verification clause found)",
                    }
                )
            if "prayer" not in lowered and "pleased to" not in lowered:
                issues.append(
                    {
                        "severity": "high",
                        "issue": "No prayer clause found - the relief sought is not stated.",
                        "excerpt": "(no prayer clause found)",
                    }
                )
            if "limitation" not in lowered and "within two years" not in lowered:
                issues.append(
                    {
                        "severity": "medium",
                        "issue": (
                            "Limitation is not pleaded. Section 3 of the Limitation "
                            "Act obliges the court to dismiss a time-barred claim "
                            "of its own motion, so the pleading should show it is "
                            "in time."
                        ),
                        "excerpt": "(no limitation averment found)",
                    }
                )
            if "jurisdiction" not in lowered:
                issues.append(
                    {
                        "severity": "medium",
                        "issue": "Jurisdiction is not pleaded.",
                        "excerpt": "(no jurisdiction averment found)",
                    }
                )

        if "affidavit" in lowered and "solemnly affirm" not in lowered:
            issues.append(
                {
                    "severity": "high",
                    "issue": "An affidavit without a solemn affirmation clause.",
                    "excerpt": "(no affirmation clause found)",
                }
            )

        if re.search(r"\bnotice\b", lowered) and "registered post" not in lowered:
            issues.append(
                {
                    "severity": "low",
                    "issue": (
                        "No mode of service is stated. Recording service by "
                        "registered post AD on the face of the notice helps prove "
                        "dispatch later."
                    ),
                    "excerpt": "(no service mode stated)",
                }
            )

        if not re.search(r"\bdate[d]?\s*[:\-]", lowered) and not re.search(
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text
        ):
            issues.append(
                {
                    "severity": "medium",
                    "issue": "No date appears on the document.",
                    "excerpt": "(no date found)",
                }
            )

        entry = load_manifest().get(template_key) if template_key else None
        checklist = entry.get("checklist", []) if entry else []

        high = sum(1 for i in issues if i["severity"] == "high")

        return {
            "status": "success",
            "operation": "review_draft",
            "template_key": template_key,
            "issues": issues,
            "issue_count": len(issues),
            "high_severity_count": high,
            "procedural_checklist": checklist,
            "message": (
                f"{len(issues)} structural issues found, {high} of them high "
                "severity."
                + (
                    " Work through the procedural checklist as well - those are "
                    "requirements the text alone cannot show were met."
                    if checklist
                    else ""
                )
                + " Run verify_all_citations separately if the draft cites any "
                "authority; this check does not look at citations."
            ),
        }

    except Exception as e:
        logger.error(f"Error in review_draft: {e}")
        return {
            "status": "error",
            "operation": "review_draft",
            "error": str(e),
            "message": "Failed to review draft",
        }


TOOLS: List[Any] = [
    list_templates,
    draft_document,
    review_draft,
]
