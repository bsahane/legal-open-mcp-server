"""Case status and cause lists, via a pluggable adapter.

The official eCourts portal at ``services.ecourts.gov.in`` has no public API and
is CAPTCHA-gated. **This server does not solve CAPTCHAs and does not scrape the
official portal.** Defeating a bot check to take data a public body has chosen
not to expose programmatically is not something this tool will do quietly on the
user's behalf.

Three adapters instead, selected by ``ECOURTS_ADAPTER``:

``manual`` (default)
    Returns the exact portal URL and the steps to follow, and accepts the result
    pasted back in. Fully functional, human in the loop.
``api``
    Calls a licensed third-party provider using ``ECOURTS_API_KEY``.
``disabled``
    Court status tools report themselves as switched off.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from legal_mcp_server.src.settings import settings
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()

PORTAL_BASE = "https://services.ecourts.gov.in/ecourtindia_v6"
HC_PORTAL_BASE = "https://hcservices.ecourts.gov.in/hcservices"
NJDG_BASE = "https://njdg.ecourts.gov.in"

REQUEST_TIMEOUT_SECONDS = 30.0


class CourtDataUnavailable(RuntimeError):
    """Raised when court data cannot be retrieved through the active adapter."""


def manual_case_status_instructions(
    cnr: Optional[str] = None,
    case_number: Optional[str] = None,
    court: Optional[str] = None,
) -> Dict[str, Any]:
    """Build step-by-step instructions for looking a case up by hand.

    Args:
        cnr: CNR number, if known. The CNR is the fastest route.
        case_number: Case number, where the CNR is unknown.
        court: Court name, needed when searching by case number.

    Returns:
        Dict with the portal URL, the steps, and what to paste back.
    """
    if cnr:
        return {
            "method": "cnr_lookup",
            "url": f"{PORTAL_BASE}/?p=cnr_status/index",
            "steps": [
                f"Open {PORTAL_BASE}/?p=cnr_status/index",
                f"Enter the CNR number {cnr}",
                "Enter the CAPTCHA shown on the page",
                "Click 'Search'",
            ],
            "capture": [
                "Case type and number",
                "Filing date and registration date",
                "Petitioner and respondent",
                "Current stage and the next hearing date",
                "The court and the presiding judge",
                "Any orders listed",
            ],
            "then": (
                "Record what you find with add_hearing and log_matter_event so the "
                "matter file stays current."
            ),
        }

    search_url = f"{PORTAL_BASE}/?p=casestatus/index"
    return {
        "method": "case_number_search",
        "url": search_url,
        "steps": [
            f"Open {search_url}",
            "Select the State, District and Court Complex"
            + (f" for {court}" if court else ""),
            "Choose the 'Case Number' tab",
            "Enter the case type, number and year"
            + (f" for {case_number}" if case_number else ""),
            "Enter the CAPTCHA and search",
            "Note the CNR number from the result - future lookups are faster with it",
        ],
        "capture": [
            "CNR number",
            "Current stage and next hearing date",
            "Parties and their advocates",
            "Orders and their dates",
        ],
        "then": (
            "Save the CNR to the matter with update_matter so subsequent lookups "
            "can use the faster CNR route."
        ),
    }


async def fetch_case_status_via_api(
    cnr: Optional[str] = None,
    case_number: Optional[str] = None,
    court: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch case status from the configured third-party provider.

    Args:
        cnr: CNR number.
        case_number: Case number.
        court: Court identifier.

    Returns:
        The provider's response payload.

    Raises:
        CourtDataUnavailable: If the provider is unconfigured or the call fails.
    """
    if not settings.ECOURTS_API_KEY:
        raise CourtDataUnavailable(
            "ECOURTS_ADAPTER is 'api' but ECOURTS_API_KEY is not set."
        )

    base = settings.ECOURTS_API_BASE_URL.rstrip("/")
    if cnr:
        url = f"{base}/case/cnr/{quote(cnr)}"
    elif case_number:
        url = f"{base}/case/search?number={quote(case_number)}"
        if court:
            url += f"&court={quote(court)}"
    else:
        raise CourtDataUnavailable("either cnr or case_number must be supplied")

    headers = {
        "Authorization": f"Bearer {settings.ECOURTS_API_KEY}",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 401:
                raise CourtDataUnavailable(
                    "The court data provider rejected the API key (401)."
                )
            if response.status_code == 404:
                return {"found": False, "message": "No case matched."}
            response.raise_for_status()
            return {"found": True, **response.json()}
    except CourtDataUnavailable:
        raise
    except Exception as e:
        raise CourtDataUnavailable(
            f"The court data provider could not be reached: {e}"
        ) from e


def adapter_status() -> Dict[str, Any]:
    """Describe the active court-data adapter for tool output."""
    adapter = settings.ECOURTS_ADAPTER
    return {
        "adapter": adapter,
        "automated": adapter == "api",
        "api_key_configured": bool(settings.ECOURTS_API_KEY),
        "note": {
            "manual": (
                "Case status is returned as portal instructions for a human to "
                "follow. The official eCourts portal is CAPTCHA-gated and this "
                "server does not automate it."
            ),
            "api": "Case status is fetched from a licensed third-party provider.",
            "disabled": "Court status lookups are switched off.",
        }[adapter],
    }
