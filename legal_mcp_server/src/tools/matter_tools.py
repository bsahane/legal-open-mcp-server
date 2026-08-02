"""Matter, hearing and timeline tools for the Legal MCP Server.

A matter is the unit of work: a dispute, a case, a transaction. Everything else
- documents, research, deadlines - hangs off it. All of this data lives in the
user's own PostgreSQL instance and never leaves it.
"""

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, cast

from legal_mcp_server.src.storage.legal_store import (
    get_store,
    unavailable_response,
)
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()

MATTER_TYPES = [
    "civil_suit",
    "criminal_complaint",
    "cheque_bounce",
    "consumer_complaint",
    "arbitration",
    "writ_petition",
    "appeal",
    "matrimonial",
    "property_dispute",
    "employment",
    "contract_dispute",
    "rti",
    "tax",
    "company_insolvency",
    "notice_only",
    "advisory",
    "other",
]

MATTER_STATUSES = [
    "open",
    "pending_filing",
    "in_court",
    "reserved",
    "disposed",
    "closed",
    "on_hold",
]


def _parse_date(value: Optional[str], field: str) -> Optional[date]:
    """Parse a YYYY-MM-DD string, raising a clear error if malformed."""
    if value is None or value == "":
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError) as e:
        raise ValueError(f"{field} must be in YYYY-MM-DD form, got '{value}'") from e


def _row_to_matter(row: Any) -> Dict[str, Any]:
    """Convert a matters row into a plain dictionary."""
    payload = dict(row)
    for key in (
        "cause_of_action_date",
        "filing_date",
        "limitation_expiry",
    ):
        if payload.get(key) is not None:
            payload[key] = payload[key].isoformat()
    for key in ("created_at", "updated_at"):
        if payload.get(key) is not None:
            payload[key] = payload[key].isoformat()
    if isinstance(payload.get("parties"), str):
        payload["parties"] = json.loads(payload["parties"])
    if payload.get("claim_value") is not None:
        payload["claim_value"] = float(payload["claim_value"])
    return payload


async def create_matter(
    title: str,
    matter_type: str,
    parties: Optional[List[Dict[str, str]]] = None,
    court: Optional[str] = None,
    case_number: Optional[str] = None,
    cnr: Optional[str] = None,
    cause_of_action_date: Optional[str] = None,
    filing_date: Optional[str] = None,
    limitation_expiry: Optional[str] = None,
    claim_value: Optional[float] = None,
    reference: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a matter record to track a dispute, case or transaction.

    TOOL_NAME=create_matter
    DISPLAY_NAME=Create Matter
    USECASE=Open a tracked record for a legal matter so hearings, documents, deadlines and events can be attached to it
    INSTRUCTIONS=1. Give a descriptive title and a matter_type from the supported list, 2. Record the cause-of-action date whenever it is known - limitation depends on it, 3. Compute the limitation expiry with compute_limitation and store it here, 4. Add parties as objects with name and role
    INPUT_DESCRIPTION=title (string, required). matter_type (string, required): one of civil_suit, criminal_complaint, cheque_bounce, consumer_complaint, arbitration, writ_petition, appeal, matrimonial, property_dispute, employment, contract_dispute, rti, tax, company_insolvency, notice_only, advisory, other. parties (list of objects, optional): [{"name": "...", "role": "plaintiff"}]. court, case_number, cnr, reference, notes (string, optional). cause_of_action_date, filing_date, limitation_expiry (string, optional): YYYY-MM-DD. claim_value (number, optional).
    OUTPUT_DESCRIPTION=Dictionary with status, the created matter including its id, and a prompt to compute limitation if it was not supplied
    EXAMPLES=create_matter("Cheque dishonour - Sharma Traders", "cheque_bounce", parties=[{"name": "Sharma Traders", "role": "accused"}], cause_of_action_date="2026-07-15", claim_value=200000)
    PREREQUISITES=PostgreSQL running and POSTGRES_* configured
    RELATED_TOOLS=compute_limitation to fill limitation_expiry; add_hearing and log_matter_event to build the record; ingest_document to attach files

    I/O-bound operation - uses async def for database access.

    Args:
        title: Short descriptive title.
        matter_type: One of the supported matter types.
        parties: Party records with name and role.
        court: Court or forum.
        case_number: Court case number, once filed.
        cnr: eCourts CNR number.
        cause_of_action_date: When the cause of action arose.
        filing_date: When the matter was filed.
        limitation_expiry: Computed limitation expiry.
        claim_value: Value of the claim.
        reference: Your own file reference.
        notes: Free-text notes.

    Returns:
        Dict with the created matter.
    """
    try:
        if not title or not title.strip():
            raise ValueError("title must be a non-empty string")
        if matter_type not in MATTER_TYPES:
            raise ValueError(
                f"matter_type must be one of {MATTER_TYPES}, got '{matter_type}'"
            )

        store = get_store()
        row = await store.fetchrow(
            """
            INSERT INTO matters (
                reference, title, matter_type, court, case_number, cnr, parties,
                cause_of_action_date, filing_date, limitation_expiry, claim_value, notes
            ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11,$12)
            RETURNING *
            """,
            reference,
            title.strip(),
            matter_type,
            court,
            case_number,
            cnr,
            json.dumps(parties or []),
            _parse_date(cause_of_action_date, "cause_of_action_date"),
            _parse_date(filing_date, "filing_date"),
            _parse_date(limitation_expiry, "limitation_expiry"),
            claim_value,
            notes,
        )

        matter = _row_to_matter(row)
        logger.info(f"Created matter {matter['id']}: {title}")

        prompt = None
        if not limitation_expiry:
            prompt = (
                "No limitation expiry is recorded. Run compute_limitation for this "
                "claim and update the matter - an untracked limitation date is the "
                "single most dangerous gap in a matter file."
            )

        return {
            "status": "success",
            "operation": "create_matter",
            "matter": matter,
            "next_step": prompt,
            "message": f"Created matter #{matter['id']}: {matter['title']}.",
        }

    except ConnectionError as e:
        return unavailable_response("create_matter", e)
    except Exception as e:
        logger.error(f"Error in create_matter: {e}")
        return {
            "status": "error",
            "operation": "create_matter",
            "error": str(e),
            "message": "Failed to create matter",
        }


async def update_matter(
    matter_id: int,
    title: Optional[str] = None,
    matter_type: Optional[str] = None,
    status: Optional[str] = None,
    court: Optional[str] = None,
    case_number: Optional[str] = None,
    cnr: Optional[str] = None,
    reference: Optional[str] = None,
    notes: Optional[str] = None,
    opposing_counsel: Optional[str] = None,
    cause_of_action_date: Optional[str] = None,
    filing_date: Optional[str] = None,
    limitation_expiry: Optional[str] = None,
    claim_value: Optional[float] = None,
    parties: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Update fields on an existing matter.

    TOOL_NAME=update_matter
    DISPLAY_NAME=Update Matter
    USECASE=Record a change to a matter - it has been filed, a case number issued, the status has moved on, the limitation date is now known
    INSTRUCTIONS=1. Give the matter id, 2. Pass only the fields that changed, 3. Log a matter event as well when the change is substantive
    INPUT_DESCRIPTION=matter_id (int, required). Any of: title, matter_type, status (open, pending_filing, in_court, reserved, disposed, closed, on_hold), court, case_number, cnr, notes, opposing_counsel (string); cause_of_action_date, filing_date, limitation_expiry (YYYY-MM-DD); claim_value (number); parties (list of objects).
    OUTPUT_DESCRIPTION=Dictionary with status, the updated matter, and the list of fields changed
    EXAMPLES=update_matter(3, status="in_court", case_number="CC/1234/2026"), update_matter(3, limitation_expiry="2026-09-08")
    PREREQUISITES=PostgreSQL running; the matter must exist
    RELATED_TOOLS=get_matter to read current values; log_matter_event to record why the change happened

    I/O-bound operation - uses async def for database access.

    Args:
        matter_id: The matter to update.
        **fields: Fields to change.

    Returns:
        Dict with the updated matter.
    """
    try:
        if not isinstance(matter_id, int) or matter_id <= 0:
            raise ValueError("matter_id must be a positive integer")

        # Only fields the caller actually supplied are written, so omitting a
        # field leaves it alone rather than nulling it.
        candidates = {
            "title": title,
            "matter_type": matter_type,
            "status": status,
            "court": court,
            "case_number": case_number,
            "cnr": cnr,
            "reference": reference,
            "notes": notes,
            "opposing_counsel": opposing_counsel,
            "cause_of_action_date": cause_of_action_date,
            "filing_date": filing_date,
            "limitation_expiry": limitation_expiry,
            "claim_value": claim_value,
            "parties": parties,
        }
        fields = {k: v for k, v in candidates.items() if v is not None}

        date_fields = {"cause_of_action_date", "filing_date", "limitation_expiry"}

        if not fields:
            raise ValueError("at least one field to update must be given")
        if matter_type is not None and matter_type not in MATTER_TYPES:
            raise ValueError(f"matter_type must be one of {MATTER_TYPES}")
        if status is not None and status not in MATTER_STATUSES:
            raise ValueError(f"status must be one of {MATTER_STATUSES}")

        assignments = []
        values: List[Any] = []
        for index, (name, value) in enumerate(fields.items(), start=1):
            if name in date_fields:
                # date_fields only ever holds the str-typed date parameters.
                values.append(_parse_date(cast(Optional[str], value), name))
                assignments.append(f"{name} = ${index}")
            elif name == "parties":
                values.append(json.dumps(value))
                assignments.append(f"{name} = ${index}::jsonb")
            else:
                values.append(value)
                assignments.append(f"{name} = ${index}")

        assignments.append("updated_at = now()")
        values.append(matter_id)

        store = get_store()
        row = await store.fetchrow(
            f"UPDATE matters SET {', '.join(assignments)} "
            f"WHERE id = ${len(values)} RETURNING *",
            *values,
        )

        if row is None:
            return {
                "status": "not_found",
                "operation": "update_matter",
                "matter_id": matter_id,
                "message": f"No matter with id {matter_id}.",
            }

        return {
            "status": "success",
            "operation": "update_matter",
            "matter": _row_to_matter(row),
            "fields_changed": sorted(fields),
            "message": f"Updated matter #{matter_id}: {', '.join(sorted(fields))}.",
        }

    except ConnectionError as e:
        return unavailable_response("update_matter", e)
    except Exception as e:
        logger.error(f"Error in update_matter: {e}")
        return {
            "status": "error",
            "operation": "update_matter",
            "error": str(e),
            "message": "Failed to update matter",
        }


async def list_matters(
    status: Optional[str] = None,
    matter_type: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """List tracked matters, optionally filtered.

    TOOL_NAME=list_matters
    DISPLAY_NAME=List Matters
    USECASE=See what is on the file, and spot matters whose limitation date is approaching
    INSTRUCTIONS=1. Call with no filters for everything open, 2. Read the limitation_alerts block first - it flags matters running out of time
    INPUT_DESCRIPTION=status (string, optional): open, pending_filing, in_court, reserved, disposed, closed, on_hold. matter_type (string, optional). limit (int, optional, default 50).
    OUTPUT_DESCRIPTION=Dictionary with status, the matters, counts by status, and limitation_alerts listing matters expiring within 60 days or already expired
    EXAMPLES=list_matters(), list_matters(status="in_court"), list_matters(matter_type="cheque_bounce")
    PREREQUISITES=PostgreSQL running
    RELATED_TOOLS=get_matter for full detail; list_upcoming_hearings for the diary

    I/O-bound operation - uses async def for database access.

    Args:
        status: Optional status filter.
        matter_type: Optional type filter.
        limit: Maximum matters to return.

    Returns:
        Dict with the matters and limitation alerts.
    """
    try:
        clauses = []
        values: List[Any] = []
        if status:
            values.append(status)
            clauses.append(f"status = ${len(values)}")
        if matter_type:
            values.append(matter_type)
            clauses.append(f"matter_type = ${len(values)}")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(max(1, min(limit, 500)))

        store = get_store()
        rows = await store.fetch(
            f"SELECT * FROM matters {where} ORDER BY "
            f"limitation_expiry ASC NULLS LAST, updated_at DESC LIMIT ${len(values)}",
            *values,
        )

        matters = [_row_to_matter(r) for r in rows]

        today = date.today()
        horizon = today + timedelta(days=60)
        alerts = []
        for matter in matters:
            expiry = matter.get("limitation_expiry")
            if not expiry or matter.get("status") in {"disposed", "closed"}:
                continue
            expiry_date = date.fromisoformat(str(expiry))
            if expiry_date <= horizon:
                alerts.append(
                    {
                        "matter_id": matter["id"],
                        "title": matter["title"],
                        "limitation_expiry": expiry,
                        "days_remaining": (expiry_date - today).days,
                        "expired": expiry_date < today,
                    }
                )

        counts: Dict[str, int] = {}
        for matter in matters:
            counts[matter["status"]] = counts.get(matter["status"], 0) + 1

        return {
            "status": "success",
            "operation": "list_matters",
            "matters": matters,
            "matter_count": len(matters),
            "counts_by_status": counts,
            "limitation_alerts": alerts,
            "message": (
                f"{len(matters)} matters."
                + (
                    f" {len(alerts)} have a limitation date within 60 days or "
                    "already past - raise these with the user first."
                    if alerts
                    else ""
                )
            ),
        }

    except ConnectionError as e:
        return unavailable_response("list_matters", e)
    except Exception as e:
        logger.error(f"Error in list_matters: {e}")
        return {
            "status": "error",
            "operation": "list_matters",
            "error": str(e),
            "message": "Failed to list matters",
        }


async def get_matter(matter_id: int) -> Dict[str, Any]:
    """Retrieve one matter with its hearings, events and documents.

    TOOL_NAME=get_matter
    DISPLAY_NAME=Get Matter Detail
    USECASE=Load everything known about a matter before advising on it or drafting in it
    INSTRUCTIONS=1. Call with the matter id, 2. Read the timeline before the notes - the chronology usually answers the question
    INPUT_DESCRIPTION=matter_id (int, required)
    OUTPUT_DESCRIPTION=Dictionary with status, the matter, its hearings, its event timeline, attached documents, and the limitation position
    EXAMPLES=get_matter(3)
    PREREQUISITES=PostgreSQL running
    RELATED_TOOLS=get_matter_timeline for the chronology alone; search_my_documents to search within the attached documents

    I/O-bound operation - uses async def for database access.

    Args:
        matter_id: The matter to load.

    Returns:
        Dict with the matter and all attached records.
    """
    try:
        if not isinstance(matter_id, int) or matter_id <= 0:
            raise ValueError("matter_id must be a positive integer")

        store = get_store()
        row = await store.fetchrow("SELECT * FROM matters WHERE id = $1", matter_id)
        if row is None:
            return {
                "status": "not_found",
                "operation": "get_matter",
                "matter_id": matter_id,
                "message": f"No matter with id {matter_id}.",
            }

        matter = _row_to_matter(row)

        hearings = await store.fetch(
            "SELECT id, hearing_date, purpose, bench, outcome, next_date "
            "FROM hearings WHERE matter_id = $1 ORDER BY hearing_date DESC",
            matter_id,
        )
        events = await store.fetch(
            "SELECT id, event_date, event_type, description FROM matter_events "
            "WHERE matter_id = $1 ORDER BY event_date DESC, id DESC",
            matter_id,
        )
        documents = await store.fetch(
            "SELECT id, title, doc_type, page_count, created_at FROM documents "
            "WHERE matter_id = $1 ORDER BY created_at DESC",
            matter_id,
        )

        limitation_status = None
        if matter.get("limitation_expiry"):
            expiry = date.fromisoformat(str(matter["limitation_expiry"]))
            days = (expiry - date.today()).days
            limitation_status = {
                "expiry": matter["limitation_expiry"],
                "days_remaining": days,
                "expired": days < 0,
                "urgency": "EXPIRED"
                if days < 0
                else "CRITICAL"
                if days <= 30
                else "OK",
            }

        return {
            "status": "success",
            "operation": "get_matter",
            "matter": matter,
            "hearings": [
                {
                    **dict(h),
                    "hearing_date": h["hearing_date"].isoformat(),
                    "next_date": h["next_date"].isoformat() if h["next_date"] else None,
                }
                for h in hearings
            ],
            "timeline": [
                {**dict(e), "event_date": e["event_date"].isoformat()} for e in events
            ],
            "documents": [
                {**dict(d), "created_at": d["created_at"].isoformat()}
                for d in documents
            ],
            "limitation_status": limitation_status,
            "message": (
                f"Matter #{matter_id}: {matter['title']}. "
                f"{len(hearings)} hearings, {len(events)} events, "
                f"{len(documents)} documents."
                + (
                    f" LIMITATION {limitation_status['urgency']}."
                    if limitation_status and limitation_status["urgency"] != "OK"
                    else ""
                )
            ),
        }

    except ConnectionError as e:
        return unavailable_response("get_matter", e)
    except Exception as e:
        logger.error(f"Error in get_matter: {e}")
        return {
            "status": "error",
            "operation": "get_matter",
            "error": str(e),
            "message": "Failed to load matter",
        }


async def add_hearing(
    matter_id: int,
    hearing_date: str,
    purpose: Optional[str] = None,
    bench: Optional[str] = None,
    outcome: Optional[str] = None,
    next_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a hearing on a matter.

    TOOL_NAME=add_hearing
    DISPLAY_NAME=Record Hearing
    USECASE=Log a court date, what it was for, what happened, and when the matter next comes up
    INSTRUCTIONS=1. Record the hearing as soon as the date is known, 2. Fill outcome and next_date after it happens, 3. Keep next_date accurate - it drives the diary
    INPUT_DESCRIPTION=matter_id (int, required). hearing_date (string, required): YYYY-MM-DD. purpose (string, optional): e.g. "framing of issues". bench (string, optional). outcome (string, optional). next_date (string, optional): YYYY-MM-DD.
    OUTPUT_DESCRIPTION=Dictionary with status and the created hearing record
    EXAMPLES=add_hearing(3, "2026-09-12", purpose="Appearance and framing of charge"), add_hearing(3, "2026-09-12", outcome="Adjourned", next_date="2026-10-20")
    PREREQUISITES=PostgreSQL running; the matter must exist
    RELATED_TOOLS=list_upcoming_hearings for the diary; log_matter_event for non-hearing developments

    I/O-bound operation - uses async def for database access.

    Args:
        matter_id: The matter the hearing belongs to.
        hearing_date: Date of the hearing.
        purpose: What the hearing is for.
        bench: The bench or judge.
        outcome: What happened.
        next_date: The next date given.

    Returns:
        Dict with the created hearing.
    """
    try:
        if not isinstance(matter_id, int) or matter_id <= 0:
            raise ValueError("matter_id must be a positive integer")

        parsed = _parse_date(hearing_date, "hearing_date")
        if parsed is None:
            raise ValueError("hearing_date is required")

        store = get_store()
        exists = await store.fetchval("SELECT 1 FROM matters WHERE id = $1", matter_id)
        if not exists:
            return {
                "status": "not_found",
                "operation": "add_hearing",
                "matter_id": matter_id,
                "message": f"No matter with id {matter_id}.",
            }

        row = await store.fetchrow(
            "INSERT INTO hearings (matter_id, hearing_date, purpose, bench, outcome, next_date) "
            "VALUES ($1,$2,$3,$4,$5,$6) RETURNING *",
            matter_id,
            parsed,
            purpose,
            bench,
            outcome,
            _parse_date(next_date, "next_date"),
        )

        assert row is not None  # INSERT ... RETURNING * always yields a row
        record = dict(row)
        record["hearing_date"] = record["hearing_date"].isoformat()
        record["next_date"] = (
            record["next_date"].isoformat() if record["next_date"] else None
        )
        record["created_at"] = record["created_at"].isoformat()

        return {
            "status": "success",
            "operation": "add_hearing",
            "hearing": record,
            "message": f"Recorded hearing on {parsed.isoformat()} for matter #{matter_id}.",
        }

    except ConnectionError as e:
        return unavailable_response("add_hearing", e)
    except Exception as e:
        logger.error(f"Error in add_hearing: {e}")
        return {
            "status": "error",
            "operation": "add_hearing",
            "error": str(e),
            "message": "Failed to record hearing",
        }


async def list_upcoming_hearings(days: int = 30) -> Dict[str, Any]:
    """List hearings and next dates falling within a window.

    TOOL_NAME=list_upcoming_hearings
    DISPLAY_NAME=Hearing Diary
    USECASE=See what is coming up across every matter, so nothing is walked into unprepared
    INSTRUCTIONS=1. Call with the window you care about, 2. Report anything within seven days first
    INPUT_DESCRIPTION=days (int, optional, default 30): how far ahead to look
    OUTPUT_DESCRIPTION=Dictionary with status, upcoming hearings with matter title and days away, and the count
    EXAMPLES=list_upcoming_hearings(), list_upcoming_hearings(days=7)
    PREREQUISITES=PostgreSQL running
    RELATED_TOOLS=add_hearing to record dates; list_matters for limitation alerts

    I/O-bound operation - uses async def for database access.

    Args:
        days: Size of the look-ahead window.

    Returns:
        Dict with the upcoming hearings.
    """
    try:
        window = max(1, min(days, 365))
        today = date.today()
        until = today + timedelta(days=window)

        store = get_store()
        rows = await store.fetch(
            """
            SELECT h.id, h.matter_id, m.title, m.case_number, m.court,
                   COALESCE(h.next_date, h.hearing_date) AS listed_date,
                   h.purpose, h.bench
            FROM hearings h
            JOIN matters m ON m.id = h.matter_id
            WHERE COALESCE(h.next_date, h.hearing_date) BETWEEN $1 AND $2
              AND m.status NOT IN ('disposed', 'closed')
            ORDER BY listed_date ASC
            """,
            today,
            until,
        )

        hearings = []
        for row in rows:
            listed = row["listed_date"]
            hearings.append(
                {
                    **dict(row),
                    "listed_date": listed.isoformat(),
                    "days_away": (listed - today).days,
                }
            )

        imminent = [h for h in hearings if h["days_away"] <= 7]

        return {
            "status": "success",
            "operation": "list_upcoming_hearings",
            "window_days": window,
            "hearings": hearings,
            "hearing_count": len(hearings),
            "imminent": imminent,
            "message": (
                f"{len(hearings)} listings in the next {window} days"
                + (f", {len(imminent)} within a week." if imminent else ".")
            ),
        }

    except ConnectionError as e:
        return unavailable_response("list_upcoming_hearings", e)
    except Exception as e:
        logger.error(f"Error in list_upcoming_hearings: {e}")
        return {
            "status": "error",
            "operation": "list_upcoming_hearings",
            "error": str(e),
            "message": "Failed to list upcoming hearings",
        }


async def log_matter_event(
    matter_id: int, event_type: str, description: str, event_date: Optional[str] = None
) -> Dict[str, Any]:
    """Append an event to a matter's chronology.

    TOOL_NAME=log_matter_event
    DISPLAY_NAME=Log Matter Event
    USECASE=Build the chronology that a brief, a plaint or an opinion will eventually be written from
    INSTRUCTIONS=1. Log events as they happen with their real dates, not the date you recorded them, 2. Describe what happened factually, without characterising it
    INPUT_DESCRIPTION=matter_id (int, required). event_type (string, required): e.g. "notice_sent", "notice_served", "reply_received", "filed", "order_passed", "payment_received", "meeting". description (string, required). event_date (string, optional): YYYY-MM-DD, defaults to today.
    OUTPUT_DESCRIPTION=Dictionary with status and the created event
    EXAMPLES=log_matter_event(3, "notice_sent", "Statutory notice under s.138 dispatched by RPAD, receipt no. RX123", event_date="2026-07-20")
    PREREQUISITES=PostgreSQL running; the matter must exist
    RELATED_TOOLS=get_matter_timeline to read the chronology back

    I/O-bound operation - uses async def for database access.

    Args:
        matter_id: The matter to append to.
        event_type: Short event category.
        description: What happened.
        event_date: When it happened.

    Returns:
        Dict with the created event.
    """
    try:
        if not isinstance(matter_id, int) or matter_id <= 0:
            raise ValueError("matter_id must be a positive integer")
        if not event_type or not event_type.strip():
            raise ValueError("event_type must be a non-empty string")
        if not description or not description.strip():
            raise ValueError("description must be a non-empty string")

        when = _parse_date(event_date, "event_date") or date.today()

        store = get_store()
        exists = await store.fetchval("SELECT 1 FROM matters WHERE id = $1", matter_id)
        if not exists:
            return {
                "status": "not_found",
                "operation": "log_matter_event",
                "matter_id": matter_id,
                "message": f"No matter with id {matter_id}.",
            }

        row = await store.fetchrow(
            "INSERT INTO matter_events (matter_id, event_date, event_type, description) "
            "VALUES ($1,$2,$3,$4) RETURNING *",
            matter_id,
            when,
            event_type.strip(),
            description.strip(),
        )

        assert row is not None  # INSERT ... RETURNING * always yields a row
        record = dict(row)
        record["event_date"] = record["event_date"].isoformat()
        record["created_at"] = record["created_at"].isoformat()

        return {
            "status": "success",
            "operation": "log_matter_event",
            "event": record,
            "message": f"Logged '{event_type}' on {when.isoformat()} for matter #{matter_id}.",
        }

    except ConnectionError as e:
        return unavailable_response("log_matter_event", e)
    except Exception as e:
        logger.error(f"Error in log_matter_event: {e}")
        return {
            "status": "error",
            "operation": "log_matter_event",
            "error": str(e),
            "message": "Failed to log matter event",
        }


async def get_matter_timeline(matter_id: int) -> Dict[str, Any]:
    """Retrieve a matter's full chronology, merging events and hearings.

    TOOL_NAME=get_matter_timeline
    DISPLAY_NAME=Matter Chronology
    USECASE=Produce the dated chronology that every brief, plaint and opinion needs, in one call
    INSTRUCTIONS=1. Call with the matter id, 2. Use the chronology as the factual spine of any document you draft for this matter
    INPUT_DESCRIPTION=matter_id (int, required)
    OUTPUT_DESCRIPTION=Dictionary with status, a single merged chronology in date order combining events and hearings, and the matter title
    EXAMPLES=get_matter_timeline(3)
    PREREQUISITES=PostgreSQL running
    RELATED_TOOLS=log_matter_event and add_hearing to populate it

    I/O-bound operation - uses async def for database access.

    Args:
        matter_id: The matter whose chronology to load.

    Returns:
        Dict with the merged chronology.
    """
    try:
        if not isinstance(matter_id, int) or matter_id <= 0:
            raise ValueError("matter_id must be a positive integer")

        store = get_store()
        matter = await store.fetchrow(
            "SELECT id, title, cause_of_action_date, filing_date FROM matters WHERE id = $1",
            matter_id,
        )
        if matter is None:
            return {
                "status": "not_found",
                "operation": "get_matter_timeline",
                "matter_id": matter_id,
                "message": f"No matter with id {matter_id}.",
            }

        events = await store.fetch(
            "SELECT event_date AS d, event_type AS kind, description FROM matter_events "
            "WHERE matter_id = $1",
            matter_id,
        )
        hearings = await store.fetch(
            "SELECT hearing_date AS d, purpose, outcome, bench FROM hearings "
            "WHERE matter_id = $1",
            matter_id,
        )

        entries: List[Dict[str, Any]] = []
        if matter["cause_of_action_date"]:
            entries.append(
                {
                    "date": matter["cause_of_action_date"].isoformat(),
                    "kind": "cause_of_action",
                    "description": "Cause of action arose",
                }
            )
        if matter["filing_date"]:
            entries.append(
                {
                    "date": matter["filing_date"].isoformat(),
                    "kind": "filed",
                    "description": "Matter filed",
                }
            )
        for event in events:
            entries.append(
                {
                    "date": event["d"].isoformat(),
                    "kind": event["kind"],
                    "description": event["description"],
                }
            )
        for hearing in hearings:
            parts = [p for p in [hearing["purpose"], hearing["outcome"]] if p]
            entries.append(
                {
                    "date": hearing["d"].isoformat(),
                    "kind": "hearing",
                    "description": " - ".join(parts) or "Hearing",
                    "bench": hearing["bench"],
                }
            )

        entries.sort(key=lambda e: e["date"])

        return {
            "status": "success",
            "operation": "get_matter_timeline",
            "matter_id": matter_id,
            "title": matter["title"],
            "chronology": entries,
            "entry_count": len(entries),
            "message": f"{len(entries)} chronology entries for matter #{matter_id}.",
        }

    except ConnectionError as e:
        return unavailable_response("get_matter_timeline", e)
    except Exception as e:
        logger.error(f"Error in get_matter_timeline: {e}")
        return {
            "status": "error",
            "operation": "get_matter_timeline",
            "error": str(e),
            "message": "Failed to load matter timeline",
        }


TOOLS: List[Any] = [
    create_matter,
    update_matter,
    list_matters,
    get_matter,
    add_hearing,
    list_upcoming_hearings,
    log_matter_event,
    get_matter_timeline,
]
