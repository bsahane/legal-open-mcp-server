"""Court working days and holidays.

Section 4 of the Limitation Act saves a filing whose deadline falls on a day the
court is closed, so knowing the calendar changes real deadlines.

Indian court holiday lists are published annually by each High Court and are
mostly festival-dependent, which means their dates move every year and cannot be
derived. This module therefore takes a strict line:

* **Weekends and fixed-date national holidays** are known with certainty and are
  applied automatically.
* **Everything else** - Diwali, Holi, Eid, Ganesh Chaturthi, the court's own
  vacations - must come from a calendar file the user installs at
  ``data/reference/court_holidays.json``. None of it is guessed.
* Every answer states which years it actually has data for, so a "working day"
  result is never silently based on an empty calendar.

Calendar file format::

    {
      "Bombay High Court": {
        "2026": [
          {"date": "2026-03-04", "occasion": "Holi"},
          {"date": "2026-10-20", "occasion": "Diwali"}
        ]
      }
    }
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from legal_mcp_server.src.settings import settings
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()

CALENDAR_FILENAME = "court_holidays.json"

#: Holidays that fall on the same date every year and are gazetted nationally.
FIXED_NATIONAL_HOLIDAYS: Dict[Tuple[int, int], str] = {
    (1, 26): "Republic Day",
    (5, 1): "Maharashtra Day / Labour Day",
    (8, 15): "Independence Day",
    (10, 2): "Gandhi Jayanti",
    (12, 25): "Christmas Day",
}


def _calendar_path() -> Path:
    return Path(settings.LEGAL_DATA_PATH).expanduser() / "reference" / CALENDAR_FILENAME


@lru_cache(maxsize=1)
def load_calendar() -> Dict[str, Dict[int, Dict[date, str]]]:
    """Load the installed court holiday calendar.

    Returns:
        Nested mapping of court name -> year -> date -> occasion. Empty if no
        calendar file is installed.
    """
    path = _calendar_path()
    if not path.is_file():
        logger.info(
            f"No court holiday calendar at {path}. Only weekends and fixed-date "
            "national holidays will be treated as closures."
        )
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Could not read court holiday calendar at {path}: {e}")
        return {}

    calendar: Dict[str, Dict[int, Dict[date, str]]] = {}
    for court, years in raw.items():
        calendar[court] = {}
        for year, entries in years.items():
            try:
                year_int = int(year)
            except (TypeError, ValueError):
                logger.warning(f"Skipping non-numeric year '{year}' for {court}")
                continue
            day_map: Dict[date, str] = {}
            for entry in entries:
                try:
                    day = date.fromisoformat(entry["date"])
                except Exception:
                    logger.warning(
                        f"Skipping malformed holiday entry for {court}: {entry}"
                    )
                    continue
                day_map[day] = entry.get("occasion", "court holiday")
            calendar[court][year_int] = day_map

    logger.info(f"Loaded holiday calendars for {len(calendar)} court(s)")
    return calendar


def reload_calendar() -> None:
    """Drop the cached calendar so the next call re-reads from disk."""
    load_calendar.cache_clear()


def covered_years(court: Optional[str] = None) -> List[int]:
    """Years for which a holiday calendar is installed for a court."""
    calendar = load_calendar()
    name = court or f"{settings.DEFAULT_HIGH_COURT} High Court"
    return sorted(calendar.get(name, {}).keys())


def has_calendar_for(day: date, court: Optional[str] = None) -> bool:
    """Whether a published calendar covering ``day`` is installed."""
    return day.year in covered_years(court)


def holiday_reason(day: date, court: Optional[str] = None) -> Optional[str]:
    """Why the court is closed on ``day``, or None if it is a working day.

    Args:
        day: The date to test.
        court: Court name; defaults to the configured High Court.

    Returns:
        The occasion, or None. A None result for a year with no installed
        calendar means "no known closure", not "certainly open" - check
        :func:`has_calendar_for`.
    """
    if day.weekday() == 6:
        return "Sunday"
    if day.weekday() == 5:
        return "Saturday"

    fixed = FIXED_NATIONAL_HOLIDAYS.get((day.month, day.day))
    if fixed:
        return fixed

    calendar = load_calendar()
    name = court or f"{settings.DEFAULT_HIGH_COURT} High Court"
    return calendar.get(name, {}).get(day.year, {}).get(day)


def is_court_closed(day: date, court: Optional[str] = None) -> bool:
    """Whether the court is known to be closed on ``day``."""
    return holiday_reason(day, court) is not None


def next_working_day(day: date, court: Optional[str] = None) -> date:
    """The first day on or after ``day`` that the court is known to be open."""
    candidate = day
    for _ in range(60):
        if not is_court_closed(candidate, court):
            return candidate
        candidate += timedelta(days=1)
    return candidate


def add_working_days(start: date, count: int, court: Optional[str] = None) -> date:
    """Add a number of working days to a date.

    Args:
        start: The date to count from; not itself counted.
        count: Number of working days to add.
        court: Court whose calendar governs.

    Returns:
        The resulting date.
    """
    current = start
    remaining = count
    guard = 0
    while remaining > 0 and guard < count * 5 + 60:
        current += timedelta(days=1)
        guard += 1
        if not is_court_closed(current, court):
            remaining -= 1
    return current


def working_days_between(start: date, end: date, court: Optional[str] = None) -> int:
    """Count working days in the half-open interval (start, end]."""
    if end <= start:
        return 0
    count = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if not is_court_closed(current, court):
            count += 1
    return count


def calendar_confidence(day: date, court: Optional[str] = None) -> Dict[str, object]:
    """Describe how much the calendar can be trusted for a given date.

    Deadline arithmetic that silently assumes an empty calendar is worse than
    arithmetic that admits what it does not know, so every deadline tool
    attaches this to its result.
    """
    name = court or f"{settings.DEFAULT_HIGH_COURT} High Court"
    years = covered_years(name)
    covered = day.year in years

    return {
        "court": name,
        "date": day.isoformat(),
        "calendar_installed": bool(years),
        "year_covered": covered,
        "years_available": years,
        "basis": (
            "Weekends, fixed-date national holidays and the installed court calendar."
            if covered
            else "Weekends and fixed-date national holidays ONLY."
        ),
        "caveat": (
            None
            if covered
            else (
                f"No holiday calendar is installed for {name} for {day.year}, so "
                "festival holidays and court vacations are not accounted for. A "
                "date reported here as a working day may in fact be a holiday. "
                "Verify against the court's published calendar before relying on "
                "a deadline that falls close to the limit, and install the "
                f"calendar at {_calendar_path()}."
            )
        ),
    }


def known_closures(year: int, court: Optional[str] = None) -> List[Dict[str, str]]:
    """Every known closure in a year, excluding weekends.

    Args:
        year: Calendar year.
        court: Court whose calendar to read.

    Returns:
        Sorted list of closure dates with their occasions.
    """
    name = court or f"{settings.DEFAULT_HIGH_COURT} High Court"
    entries: Dict[date, str] = {}

    for (month, day_of_month), occasion in FIXED_NATIONAL_HOLIDAYS.items():
        try:
            entries[date(year, month, day_of_month)] = occasion
        except ValueError:  # pragma: no cover - fixed dates are always valid
            continue

    # The installed calendar wins where it names the same day differently.
    entries.update(load_calendar().get(name, {}).get(year, {}))

    return [
        {"date": day.isoformat(), "occasion": entries[day]} for day in sorted(entries)
    ]
