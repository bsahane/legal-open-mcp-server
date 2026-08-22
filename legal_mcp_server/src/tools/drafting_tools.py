"""Document drafting tools for the Legal MCP Server.

Templates are Jinja2 files in ``src/templates/documents/`` described by
``src/templates/manifest.yaml``. Each template carries its own procedural
checklist and next steps, so the requirements travel with the document rather
than depending on the model to recall them.

A rendered draft is a starting point. Every draft returned here is accompanied
by its checklist and by an instruction to run the citation sweep before the
document is used.
"""

import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from jinja2 import (
    Environment,
    FileSystemBytecodeCache,
    FileSystemLoader,
    StrictUndefined,
    TemplateError,
)

from legal_mcp_server.src.settings import settings
from legal_mcp_server.src.templates.languages import (
    SUPPORTED_LANGUAGES,
    translation_entries,
    validate_language,
)
from legal_mcp_server.src.templates.languages import (
    t as _t,
)
from legal_mcp_server.src.tools.research_tools import verify_all_citations
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "templates"
DOCUMENT_DIR = TEMPLATE_ROOT / "documents"
BASE_DIR = TEMPLATE_ROOT / "base"
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
    """Jinja2 environment configured to fail loudly on missing variables.

    Compiled templates are cached on disk under ``LEGAL_DATA_PATH/cache/jinja2``
    so the first render of each template in a process is the only compile.
    """
    cache_dir = Path(settings.LEGAL_DATA_PATH) / "cache" / "jinja2"
    cache_dir.mkdir(parents=True, exist_ok=True)
    env = Environment(
        loader=FileSystemLoader([str(DOCUMENT_DIR), str(BASE_DIR)]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,  # nosec B701 - plain-text legal documents, not HTML
        keep_trailing_newline=True,
        bytecode_cache=FileSystemBytecodeCache(str(cache_dir), "%s.cache"),
        auto_reload=False,  # call reload_templates() when templates change
    )
    env.filters["inr"] = inr
    env.globals["t"] = _t
    return env


def reload_templates() -> None:
    """Drop cached manifest and environment so changes on disk take effect."""
    load_manifest.cache_clear()
    _environment.cache_clear()
    cache_dir = Path(settings.LEGAL_DATA_PATH) / "cache" / "jinja2"
    if cache_dir.is_dir():
        for cached in cache_dir.glob("*.cache"):
            cached.unlink(missing_ok=True)


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


def draft_document(
    template_key: str,
    parameters: Dict[str, Any],
    language: Optional[str] = None,
    auto_verify: bool = False,
    branding: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Render a legal document from a template and a set of facts.

    TOOL_NAME=draft_document
    DISPLAY_NAME=Draft Legal Document
    USECASE=Produce a notice, complaint, application or affidavit in correct Indian form from facts the user has supplied
    INSTRUCTIONS=1. Call list_templates first to learn the required parameters, 2. Collect every required parameter from the user - never invent names, addresses, amounts or dates, 3. Pass language (e.g. "hi") to draft in a translated language where the template supports it, 4. Optionally pass branding (advocate_name, enrollment, firm_name, office_address, mobile, email, logo_base64, separator_style, date_format) for letterhead formatting, 5. Render, 6. Give the user the draft together with its checklist, 7. If auto_verify is True, the draft is automatically swept for citations
    INPUT_DESCRIPTION=template_key (string, required): key from list_templates, e.g. "notice_ni138". parameters (object, required): the facts, matching the template's required and optional parameters. List parameters such as facts, demands and reliefs take arrays of strings. language (string, optional): one of the codes listed by get_document_languages (e.g. "en", "hi") - the static text of the template is rendered in that language; parameters you pass are used verbatim. auto_verify (bool, optional, default False): if True, runs verify_all_citations on the rendered draft. branding (object, optional): advocate branding for letterhead - advocate_name, enrollment, firm_name, office_address, mobile, email, logo_base64, separator_style, date_format.
    OUTPUT_DESCRIPTION=Dictionary with status, the rendered draft, the template's procedural checklist, governing authority, next steps, verification result (if auto_verify), and a reminder that the draft is unsigned and unserved
    EXAMPLES=draft_document("rti_application", {"public_authority": "Municipal Corporation of Greater Mumbai", "authority_address": "...", "application_date": "2026-08-02", "information_sought": ["Copy of building plan approval for CTS 123"], "applicant_name": "...", "applicant_address": "..."}), draft_document("notice_ni138", {"sender_name": "...", "sender_address": "...", "notice_date": "2026-08-16", "recipient_name": "...", "recipient_address": "...", "client_name": "...", "client_address": "...", "liability_description": "...", "cheque_number": "123456", "cheque_date": "2026-07-01", "cheque_amount": 100000, "amount_in_words": "One Lakh Only", "drawee_bank": "...", "drawee_branch": "...", "payee_bank": "...", "payee_branch": "...", "presentation_date": "2026-07-02", "dishonour_reason": "Insufficient funds", "dishonour_memo_date": "2026-07-03", "dishonour_date": "2026-07-03"}, language="hi", auto_verify=True, branding={"advocate_name": "Bhushan Sahane", "enrollment": "MAH/1234/2020", "firm_name": "Bhushan Sahane & Associates", "office_address": "504, FcyMax-3, Udyog Vihar, Sector-3, Gurgaon, Haryana-122002", "mobile": "8552019001", "separator_style": "equals", "date_format": "DD@MM@YYYY"})
    PREREQUISITES=None - fully offline
    RELATED_TOOLS=list_templates for parameters; get_document_languages for the language codes a template supports; review_draft to check the result; verify_all_citations for manual citation sweep; compute_cheque_bounce_timeline before a s.138 notice

    CPU-bound operation - uses def for template rendering.

    Args:
        template_key: Which template to render.
        parameters: The facts to render into it.
        language: Optional language code for the static template text.
        auto_verify: If True, runs verify_all_citations on the rendered draft.
        branding: Optional advocate branding for letterhead formatting.

    Returns:
        Dict with the rendered draft, its checklist, and verification result (if auto_verify).
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

        language = validate_language(language) if language else "en"
        supported = entry.get("languages", [])
        if supported and language not in supported:
            return {
                "status": "unsupported_language",
                "operation": "draft_document",
                "template_key": template_key,
                "requested_language": language,
                "supported_languages": supported,
                "message": (
                    f"Template '{template_key}' supports {', '.join(supported)}; "
                    f"'{language}' is not among them. Either pass one of those "
                    "codes, or omit language for the default."
                ),
            }

        # Default branding from manifest if not provided
        default_branding = entry.get("branding", {})
        if branding:
            # User-provided branding overrides defaults
            final_branding = {**default_branding, **branding}
        else:
            final_branding = default_branding

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
        context["language"] = language
        context["branding"] = final_branding

        # Ensure branding has required defaults
        branding_defaults = {
            "advocate_name": "Advocate Name",
            "enrollment": "",
            "firm_name": "",
            "office_address": "",
            "mobile": "",
            "email": "",
            "logo_base64": "",
            "separator_style": "equals",
            "date_format": "DD@MM@YYYY",
        }
        for key, default_val in branding_defaults.items():
            if key not in final_branding:
                final_branding[key] = default_val

        unknown = set(parameters) - set(required) - set(entry.get("optional", []))
        if unknown:
            logger.warning(
                f"Template '{template_key}' received undeclared parameter(s): "
                f"{sorted(unknown)}"
            )

        template = _environment().get_template(entry["file"])
        rendered = template.render(**context)

        logger.info(f"Drafted document from template '{template_key}'")

        # Auto-verify citations if requested
        verification_result = None
        if auto_verify and rendered.strip():
            try:
                verification_result = asyncio.run(
                    verify_all_citations(rendered, max_citations=25)
                )
            except Exception as e:
                logger.warning(f"Auto-verification failed: {e}")
                verification_result = {
                    "status": "error",
                    "operation": "verify_all_citations",
                    "error": str(e),
                }

        return {
            "status": "success",
            "operation": "draft_document",
            "template_key": template_key,
            "title": entry["title"],
            "category": entry.get("category"),
            "language": language,
            "draft": rendered,
            "checklist": entry.get("checklist", []),
            "authority": entry.get("authority"),
            "next_steps": entry.get("next_steps", []),
            "verification_result": verification_result,
            "message": (
                f"Drafted '{entry['title']}' in {language}. Present the checklist "
                "to the user alongside the draft. This document is unsigned and "
                "unserved - this server does not send, file or serve anything."
                + (
                    f" Auto-verification: {verification_result['verification_summary']['verified']}/{verification_result['verification_summary']['total']} citations verified (confidence: {verification_result['verification_summary']['avg_confidence']:.0%}). "
                    if verification_result
                    and verification_result.get("status") == "success"
                    else " Auto-verification disabled or failed. "
                )
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


def get_document_languages(template_key: str) -> Dict[str, Any]:
    """Report the languages a drafting template can render its static text in.

    TOOL_NAME=get_document_languages
    DISPLAY_NAME=Get Document Languages
    USECASE=Check which languages a document template supports before drafting, so the user is not asked for a language the template cannot honour
    INSTRUCTIONS=1. Call before drafting when the user asks for a document in a particular language, 2. If the requested language is not supported, either pick a supported one or note that only the static text is translated while user-supplied facts stay verbatim
    INPUT_DESCRIPTION=template_key (string, required): the template key, e.g. "writ_petition"
    OUTPUT_DESCRIPTION=Dictionary with status, the template, the supported language codes and their English names, and a note on how translation behaves
    EXAMPLES=get_document_languages("writ_petition"), get_document_languages("ni_138_notice")
    PREREQUISITES=None - fully offline
    RELATED_TOOLS=draft_document, which takes the language code; list_templates

    CPU-bound operation - uses def for manifest and language inspection.

    Args:
        template_key: The template to inspect.

    Returns:
        Dict describing the supported languages.
    """
    try:
        manifest = load_manifest()
        entry = manifest.get(template_key)
        if entry is None:
            return {
                "status": "not_found",
                "operation": "get_document_languages",
                "template_key": template_key,
                "available": sorted(manifest),
                "message": (
                    f"No template '{template_key}'. Available: "
                    f"{', '.join(sorted(manifest))}."
                ),
            }

        supported = entry.get("languages", [])
        names = {
            "en": "English",
            "hi": "Hindi",
            "mr": "Marathi",
            "ta": "Tamil",
            "te": "Telugu",
        }

        return {
            "status": "success",
            "operation": "get_document_languages",
            "template_key": template_key,
            "title": entry["title"],
            "languages": supported,
            "language_names": {code: names.get(code, code) for code in supported},
            "message": (
                f"'{template_key}' can render its static text in: "
                f"{', '.join(supported)}. Only the template's static text is "
                "translated - the facts you pass are used exactly as given, so "
                "names, addresses and amounts appear verbatim in the document."
            ),
        }

    except Exception as e:
        logger.error(f"Error in get_document_languages: {e}")
        return {
            "status": "error",
            "operation": "get_document_languages",
            "error": str(e),
            "message": "Failed to inspect template languages",
        }


def _sentence_pattern(english: str) -> str:
    """Build a regex that matches an English template sentence as rendered.

    The translations dictionary stores ``{{ name }}`` placeholders for
    user-supplied values; in a rendered draft those have been replaced by the
    actual facts.  Each placeholder becomes a named capture group so the
    values can be carried into the translated sentence.

    Args:
        english: The English template sentence.

    Returns:
        A compiled-searchable regex string.
    """
    import re

    parts = re.split(r"\{\{\s*(\w+)\s*\}\}", english)
    pattern = ""
    for i, part in enumerate(parts):
        if i % 2 == 0:
            pattern += re.escape(part)
        else:
            pattern += f"(?P<{part}>.*?)"
    return pattern


def _substitute(sentence: str, captured: Dict[str, str]) -> str:
    """Fill ``{{ name }}`` placeholders in a translated sentence.

    Values come from the facts captured from the English draft; unknown
    placeholders are left verbatim so gaps stay visible.
    """
    import re

    return re.sub(
        r"\{\{\s*(\w+)\s*\}\}",
        lambda m: captured.get(m.group(1), m.group(0)),
        sentence,
    )


def translate_document(
    draft_text: str,
    target_language: str,
    source_language: Optional[str] = None,
) -> Dict[str, Any]:
    """Translate the static prose of a rendered draft into another language.

    Only templated prose is translated into a supported Indian language;
    names, addresses, amounts, case numbers and legal citations are left
    untouched.

    TOOL_NAME=translate_document
    DISPLAY_NAME=Translate Draft Document
    USECASE=Produce a translated version of a draft when the user asks for one, or when the facts are available in English but the document must be filed in a regional language
    INSTRUCTIONS=1. Pass the draft text, 2. Pass the target_language code (en/hi/mr/ta/te), 3. Only the static template prose is translated - names, addresses, amounts, case numbers and citations are preserved verbatim, 4. For a truly filing-ready document, settle the translation with a translator or advocate before use
    INPUT_DESCRIPTION=draft_text (string, required): the rendered draft. target_language (string, required): one of en/hi/mr/ta/te. source_language (string, optional): the language the draft is currently in, defaulting to en.
    OUTPUT_DESCRIPTION=Dictionary with status, the translated draft, the languages involved, and a disclaimer
    EXAMPLES=translate_document(draft, target_language="hi"), translate_document(draft, target_language="mr", source_language="en")
    PREREQUISITES=None - fully offline, rule-based
    RELATED_TOOLS=draft_document, which accepts a language natively; get_document_languages

    CPU-bound operation - uses def for rule-based translation.

    Args:
        draft_text: The draft to translate.
        target_language: Language code to translate the static prose into.
        source_language: Language the draft is currently in (default "en").

    Returns:
        Dict with the translated draft and disclaimer.
    """
    try:
        if not draft_text or not draft_text.strip():
            raise ValueError("draft_text must be a non-empty string")
        target_language = validate_language(target_language)
        source_language = (
            validate_language(source_language) if source_language else "en"
        )

        if source_language == target_language:
            return {
                "status": "success",
                "operation": "translate_document",
                "source_language": source_language,
                "target_language": target_language,
                "translated_draft": draft_text,
                "message": (
                    f"Source and target are both '{target_language}'; the draft "
                    "was returned unchanged."
                ),
            }

        if source_language not in SUPPORTED_LANGUAGES:
            return {
                "status": "unsupported_language",
                "operation": "translate_document",
                "source_language": source_language,
                "supported_languages": sorted(SUPPORTED_LANGUAGES),
                "message": f"Source language '{source_language}' is not supported.",
            }

        import re

        # The translations dictionary holds the English template sentences
        # exactly as they render (before user values replace the {{ }} slots).
        # Reverse-match each English sentence in the draft, then emit the
        # target-language sentence with the captured values substituted back
        # in. Unknown text - names, addresses, amounts, case numbers, free-form
        # facts - is left untouched.
        entries = translation_entries()
        translated = draft_text
        replaced = 0
        for key, langs in entries.items():
            english = langs.get("en")
            target = langs.get(target_language)
            if not english or not target:
                continue  # no English form or no translation available

            pattern = _sentence_pattern(english)
            matcher = re.compile(pattern, re.IGNORECASE)
            target_sentence: str = target

            def repl(match: re.Match, target_sentence: str = target_sentence) -> str:
                return _substitute(target_sentence, match.groupdict())

            translated, count = matcher.subn(repl, translated)
            replaced += count

        return {
            "status": "success",
            "operation": "translate_document",
            "source_language": source_language,
            "target_language": target_language,
            "translated_draft": translated,
            "sentences_translated": replaced,
            "message": (
                f"{replaced} standard clause(s) were translated from "
                f"'{source_language}' to '{target_language}'. Names, addresses, "
                "amounts, case numbers and citations were left untouched. For a "
                "filing-ready document, have the result settled by a translator "
                "or advocate - this is a rule-based pass over the standard "
                "clauses, not a professional translation."
            ),
        }

    except Exception as e:
        logger.error(f"Error in translate_document: {e}")
        return {
            "status": "error",
            "operation": "translate_document",
            "error": str(e),
            "message": "Failed to translate document",
        }


TOOLS: List[Any] = [
    list_templates,
    draft_document,
    review_draft,
    get_document_languages,
    translate_document,
]
