"""Court status, directory and jurisdiction tools for the Legal MCP Server."""

from typing import Any, Dict, List, Optional

from legal_mcp_server.src.settings import settings
from legal_mcp_server.src.sources import ecourts
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()

# Bombay High Court and the Maharashtra hierarchy, plus the tribunals that come
# up most often. Not exhaustive - it names what it covers.
COURT_DIRECTORY: Dict[str, List[Dict[str, str]]] = {
    "supreme_court": [
        {
            "name": "Supreme Court of India",
            "seat": "New Delhi",
            "website": "https://www.sci.gov.in",
            "jurisdiction": "Appellate and original under Article 32; all India",
        }
    ],
    "high_court": [
        {
            "name": "Bombay High Court (Principal Seat)",
            "seat": "Mumbai",
            "website": "https://bombayhighcourt.nic.in",
            "jurisdiction": (
                "Maharashtra (Mumbai, Konkan and Western Maharashtra), plus "
                "original civil jurisdiction over Greater Mumbai above the "
                "notified pecuniary limit"
            ),
        },
        {
            "name": "Bombay High Court, Nagpur Bench",
            "seat": "Nagpur",
            "website": "https://bombayhighcourt.nic.in",
            "jurisdiction": "Vidarbha region of Maharashtra",
        },
        {
            "name": "Bombay High Court, Aurangabad Bench",
            "seat": "Chhatrapati Sambhajinagar (Aurangabad)",
            "website": "https://bombayhighcourt.nic.in",
            "jurisdiction": "Marathwada region of Maharashtra",
        },
        {
            "name": "Bombay High Court at Goa",
            "seat": "Panaji",
            "website": "https://bombayhighcourt.nic.in",
            "jurisdiction": "State of Goa, and Dadra and Nagar Haveli and Daman and Diu",
        },
    ],
    "district_court": [
        {
            "name": "City Civil and Sessions Court, Mumbai",
            "seat": "Dindoshi and Fort, Mumbai",
            "jurisdiction": "Greater Mumbai, civil and sessions",
        },
        {
            "name": "District and Sessions Court, Pune",
            "seat": "Pune",
            "jurisdiction": "Pune district",
        },
        {
            "name": "District and Sessions Court, Thane",
            "seat": "Thane",
            "jurisdiction": "Thane district",
        },
        {
            "name": "District and Sessions Court, Nagpur",
            "seat": "Nagpur",
            "jurisdiction": "Nagpur district",
        },
        {
            "name": "Small Causes Court, Mumbai",
            "seat": "Mumbai",
            "jurisdiction": (
                "Suits of a small-cause nature, and licence and tenancy disputes "
                "in Greater Mumbai"
            ),
        },
    ],
    "tribunal": [
        {
            "name": "National Company Law Tribunal, Mumbai Bench",
            "seat": "Mumbai",
            "website": "https://nclt.gov.in",
            "jurisdiction": "Companies Act, 2013 and Insolvency and Bankruptcy Code, 2016",
        },
        {
            "name": "State Consumer Disputes Redressal Commission, Maharashtra",
            "seat": "Mumbai",
            "jurisdiction": "Consumer Protection Act, 2019 appeals and higher-value complaints",
        },
        {
            "name": "Maharashtra Real Estate Regulatory Authority (MahaRERA)",
            "seat": "Mumbai",
            "website": "https://maharera.maharashtra.gov.in",
            "jurisdiction": "Real Estate (Regulation and Development) Act, 2016",
        },
        {
            "name": "Maharashtra Administrative Tribunal",
            "seat": "Mumbai, with benches at Nagpur and Aurangabad",
            "jurisdiction": "Service matters of State Government employees",
        },
        {
            "name": "Debts Recovery Tribunal, Mumbai",
            "seat": "Mumbai",
            "jurisdiction": "Recovery of Debts and Bankruptcy Act, 1993 and SARFAESI",
        },
        {
            "name": "Income Tax Appellate Tribunal, Mumbai Bench",
            "seat": "Mumbai",
            "jurisdiction": "Appeals under the Income-tax Act, 1961",
        },
    ],
}


async def get_case_status(
    cnr: Optional[str] = None,
    case_number: Optional[str] = None,
    court: Optional[str] = None,
) -> Dict[str, Any]:
    """Look up the status of a pending case.

    TOOL_NAME=get_case_status
    DISPLAY_NAME=Case Status Lookup
    USECASE=Find the current stage and next hearing date of a case on the eCourts system
    INSTRUCTIONS=1. Prefer the CNR number, which is unique and fastest, 2. In the default manual mode you receive portal steps to follow yourself - the official portal is CAPTCHA-gated and is not automated here, 3. Record what you find with add_hearing and log_matter_event
    INPUT_DESCRIPTION=cnr (string, optional): 16-character CNR number. case_number (string, optional): case type, number and year. court (string, optional): court name, needed when searching by case number.
    OUTPUT_DESCRIPTION=In api mode, the case record. In manual mode, the portal URL, the steps to follow, what to capture, and where to record it. Always includes which adapter was used.
    EXAMPLES=get_case_status(cnr="MHMU010123452026"), get_case_status(case_number="CC/1234/2026", court="City Civil Court, Mumbai")
    PREREQUISITES=Manual mode needs nothing. Automated lookup needs ECOURTS_ADAPTER=api and a licensed ECOURTS_API_KEY.
    RELATED_TOOLS=add_hearing and log_matter_event to record the result; update_matter to store the CNR

    I/O-bound operation - uses async def for external API calls.

    Args:
        cnr: CNR number.
        case_number: Case number.
        court: Court name.

    Returns:
        Dict with the case status or the instructions to obtain it.
    """
    try:
        if not cnr and not case_number:
            raise ValueError("either cnr or case_number must be supplied")

        status = ecourts.adapter_status()

        if settings.ECOURTS_ADAPTER == "disabled":
            return {
                "status": "unavailable",
                "operation": "get_case_status",
                "adapter_status": status,
                "message": (
                    "Court status lookups are disabled (ECOURTS_ADAPTER=disabled). "
                    "Set it to 'manual' for portal instructions."
                ),
            }

        if settings.ECOURTS_ADAPTER == "api":
            payload = await ecourts.fetch_case_status_via_api(cnr, case_number, court)
            return {
                "status": "success",
                "operation": "get_case_status",
                "source": "third_party_api",
                "adapter_status": status,
                **payload,
                "message": (
                    "Retrieved from the third-party provider. Third-party data can "
                    "lag the court's own record - verify anything date-critical "
                    "against the portal."
                ),
            }

        instructions = ecourts.manual_case_status_instructions(cnr, case_number, court)
        return {
            "status": "manual_action_required",
            "operation": "get_case_status",
            "adapter_status": status,
            "cnr": cnr,
            "case_number": case_number,
            **instructions,
            "message": (
                "The official eCourts portal is CAPTCHA-gated and this server does "
                "not automate it. Follow the steps above, then paste the result "
                "back and it will be recorded against the matter. Set "
                "ECOURTS_ADAPTER=api with a licensed provider key for automated "
                "lookups."
            ),
        }

    except ecourts.CourtDataUnavailable as e:
        return {
            "status": "unavailable",
            "operation": "get_case_status",
            "error": str(e),
            "message": (
                f"Court data could not be retrieved: {e}. Do not report a case "
                "stage or hearing date that was not actually retrieved."
            ),
        }
    except Exception as e:
        logger.error(f"Error in get_case_status: {e}")
        return {
            "status": "error",
            "operation": "get_case_status",
            "error": str(e),
            "message": "Failed to look up case status",
        }


def court_directory(court_type: Optional[str] = None) -> Dict[str, Any]:
    """List courts and tribunals with their seats and jurisdiction.

    TOOL_NAME=court_directory
    DISPLAY_NAME=Court Directory
    USECASE=Identify the right forum, its seat and its website before filing or advising on where a matter goes
    INSTRUCTIONS=1. Filter by type if you know it, 2. Read the jurisdiction line - it is what determines the correct forum, not the court's convenience
    INPUT_DESCRIPTION=court_type (string, optional): "supreme_court", "high_court", "district_court" or "tribunal"
    OUTPUT_DESCRIPTION=Dictionary with status, courts with name, seat, website and jurisdiction, plus a note on coverage
    EXAMPLES=court_directory(), court_directory(court_type="tribunal")
    PREREQUISITES=None - fully offline
    RELATED_TOOLS=determine_jurisdiction to work out which forum a specific dispute belongs in

    CPU-bound operation - uses def for local table lookup.

    Args:
        court_type: Optional category filter.

    Returns:
        Dict with the directory entries.
    """
    try:
        if court_type and court_type not in COURT_DIRECTORY:
            raise ValueError(
                f"court_type must be one of {sorted(COURT_DIRECTORY)} or omitted"
            )

        selected = (
            {court_type: COURT_DIRECTORY[court_type]} if court_type else COURT_DIRECTORY
        )
        total = sum(len(v) for v in selected.values())

        return {
            "status": "success",
            "operation": "court_directory",
            "default_state": settings.DEFAULT_STATE,
            "default_high_court": settings.DEFAULT_HIGH_COURT,
            "courts": selected,
            "court_count": total,
            "message": (
                f"{total} courts and tribunals listed. This directory covers the "
                f"Supreme Court, the {settings.DEFAULT_HIGH_COURT} High Court and "
                "its benches, the main Maharashtra district courts and the "
                "commonly used tribunals. It is not a complete list of every "
                "court in India - say so rather than implying a court does not "
                "exist because it is absent here."
            ),
        }

    except Exception as e:
        logger.error(f"Error in court_directory: {e}")
        return {
            "status": "error",
            "operation": "court_directory",
            "error": str(e),
            "message": "Failed to read the court directory",
        }


def determine_jurisdiction(
    subject_matter: str,
    claim_value: Optional[float] = None,
    cause_of_action_place: Optional[str] = None,
    defendant_place: Optional[str] = None,
) -> Dict[str, Any]:
    """Work out which forum a dispute belongs in.

    TOOL_NAME=determine_jurisdiction
    DISPLAY_NAME=Jurisdiction Analysis
    USECASE=Decide where a matter should be filed, covering subject-matter, pecuniary and territorial jurisdiction
    INSTRUCTIONS=1. Describe the subject matter, 2. Give the claim value and the places connected to the dispute, 3. Confirm the pecuniary limits against the current notification before filing - those limits change and this tool does not track amendments
    INPUT_DESCRIPTION=subject_matter (string, required): what the dispute is about. claim_value (number, optional): value in rupees. cause_of_action_place (string, optional): where the cause of action arose. defendant_place (string, optional): where the defendant resides or works.
    OUTPUT_DESCRIPTION=Dictionary with status, the suggested forum on subject matter, the territorial options with their statutory basis, notes on pecuniary jurisdiction, and the provisions to check
    EXAMPLES=determine_jurisdiction("dishonoured cheque", claim_value=200000, cause_of_action_place="Mumbai"), determine_jurisdiction("defective product bought online", claim_value=45000)
    PREREQUISITES=None - fully offline
    RELATED_TOOLS=court_directory for the forum's details; get_section for the jurisdiction provisions cited

    CPU-bound operation - uses def for rule evaluation.

    Args:
        subject_matter: What the dispute concerns.
        claim_value: Value of the claim in rupees.
        cause_of_action_place: Where the cause of action arose.
        defendant_place: Where the defendant resides or carries on business.

    Returns:
        Dict with the jurisdiction analysis.
    """
    try:
        if not subject_matter or not subject_matter.strip():
            raise ValueError("subject_matter must be a non-empty string")

        subject = subject_matter.lower()
        forum: Dict[str, Any]

        if "cheque" in subject or "138" in subject:
            forum = {
                "forum": "Judicial Magistrate First Class / Metropolitan Magistrate",
                "basis": "section 142, Negotiable Instruments Act, 1881",
                "territorial_rule": (
                    "Section 142(2)(a) fixes jurisdiction at the court within whose "
                    "local limits the payee's bank branch - where the cheque was "
                    "delivered for collection - is situated. This displaced the "
                    "earlier position and is often got wrong."
                ),
            }
        elif "consumer" in subject or "deficien" in subject or "defective" in subject:
            forum = {
                "forum": "District / State / National Consumer Disputes Redressal Commission",
                "basis": "sections 34, 47 and 58, Consumer Protection Act, 2019",
                "territorial_rule": (
                    "Section 34(2) allows filing where the opposite party resides "
                    "or carries on business, where the cause of action arose, or "
                    "where the complainant resides or personally works for gain - "
                    "the last limb is a significant convenience for consumers."
                ),
                "pecuniary_rule": (
                    "Pecuniary jurisdiction is fixed by the consideration PAID, "
                    "not by the compensation claimed. Confirm the current "
                    "thresholds against the latest notification."
                ),
            }
        elif "arbitrat" in subject:
            forum = {
                "forum": "The arbitral tribunal, supervised by the court at the seat",
                "basis": "Arbitration and Conciliation Act, 1996",
                "territorial_rule": (
                    "The seat of arbitration determines which court exercises "
                    "supervisory jurisdiction under sections 9, 11, 34 and 37. "
                    "Venue alone does not; establish the seat first."
                ),
            }
        elif (
            "fundamental right" in subject
            or "writ" in subject
            or "government" in subject
        ):
            forum = {
                "forum": f"{settings.DEFAULT_HIGH_COURT} High Court under Article 226, or the Supreme Court under Article 32",
                "basis": "Articles 226 and 32, Constitution of India",
                "territorial_rule": (
                    "Article 226(2) permits a High Court to act where the cause of "
                    "action arises wholly or in part within its territories, even "
                    "if the authority sits elsewhere."
                ),
            }
        elif "tenan" in subject or "rent" in subject or "licence" in subject:
            forum = {
                "forum": "Small Causes Court, or the Competent Authority under the Maharashtra Rent Control Act, 1999",
                "basis": "Maharashtra Rent Control Act, 1999",
                "territorial_rule": "The court within whose limits the premises are situated.",
            }
        elif "matrimon" in subject or "divorce" in subject or "maintenance" in subject:
            forum = {
                "forum": "Family Court",
                "basis": "Family Courts Act, 1984",
                "territorial_rule": (
                    "Where the marriage was solemnised, where the respondent "
                    "resides, or where the parties last resided together."
                ),
            }
        elif "insolven" in subject or "company" in subject or "winding up" in subject:
            forum = {
                "forum": "National Company Law Tribunal",
                "basis": "Companies Act, 2013 and Insolvency and Bankruptcy Code, 2016",
                "territorial_rule": "The bench in whose territory the registered office is situated.",
            }
        else:
            forum = {
                "forum": "Civil court of appropriate pecuniary jurisdiction",
                "basis": "sections 15 to 20, Code of Civil Procedure, 1908",
                "territorial_rule": (
                    "Section 20 CPC: where the defendant resides or carries on "
                    "business, or where the cause of action arises wholly or in "
                    "part. Section 16 puts suits concerning immovable property "
                    "where the property is situated."
                ),
                "pecuniary_rule": (
                    "Section 15 CPC requires a suit to be instituted in the court "
                    "of the lowest grade competent to try it."
                ),
            }

        options = []
        if cause_of_action_place:
            options.append(
                {
                    "place": cause_of_action_place,
                    "basis": "where the cause of action arose",
                }
            )
        if defendant_place:
            options.append(
                {
                    "place": defendant_place,
                    "basis": "where the defendant resides or carries on business",
                }
            )

        return {
            "status": "success",
            "operation": "determine_jurisdiction",
            "subject_matter": subject_matter,
            "claim_value": claim_value,
            **forum,
            "territorial_options": options,
            "message": (
                f"Subject matter points to: {forum['forum']} ({forum['basis']})."
                + (
                    " More than one court may have territorial jurisdiction; the "
                    "choice between them is tactical."
                    if len(options) > 1
                    else ""
                )
            ),
            "caution": (
                "Pecuniary thresholds are revised by notification and are not "
                "tracked by this tool, so confirm the current limit before filing. "
                "Filing in the wrong forum wastes the limitation period, although "
                "section 14 of the Limitation Act may excuse time spent bona fide "
                "in a court without jurisdiction."
            ),
        }

    except Exception as e:
        logger.error(f"Error in determine_jurisdiction: {e}")
        return {
            "status": "error",
            "operation": "determine_jurisdiction",
            "error": str(e),
            "message": "Failed to analyse jurisdiction",
        }


TOOLS: List[Any] = [
    get_case_status,
    court_directory,
    determine_jurisdiction,
]
