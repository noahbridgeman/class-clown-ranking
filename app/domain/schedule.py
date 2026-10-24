"""Voting windows in the group's local time (VOT-01, PER-04, PER-05, VOT-10).

Daily: [13:00, 13:00 next day). Weekly: [Sunday 00:00, Monday 13:00). Windows
are half-open. Local wall times are resolved with fold=0: a time inside a DST
gap moves forward by the length of the gap (02:30 → 03:30, and 00:00 at a
midnight gap → 01:00), a repeated time resolves to its first occurrence. A
calendar day that is skipped entirely yields no window of its own.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.domain.types import Cadence

UPDATE_TIME = time(13, 0)
WEEKLY_OPEN_TIME = time(0, 0)
SUNDAY = 6  # date.weekday()
# Anchors searched around the local date of `now`; covers any window containing
# or following it.
SEARCH_DAYS_BEFORE = 7
SEARCH_DAYS_AFTER = 8


@dataclass(frozen=True)
class Window:
    opens_at: datetime  # UTC
    closes_at: datetime  # UTC

    def contains(self, at: datetime) -> bool:
        return self.opens_at <= at < self.closes_at


def window_at(now: datetime, cadence: Cadence, tz: str) -> Window | None:
    """The window that contains `now`, or None between weekly windows."""
    return next((w for w in _windows_around(now, cadence, tz) if w.contains(now)), None)


def next_window(now: datetime, cadence: Cadence, tz: str) -> Window:
    """The first window with opens_at > now (VOT-10)."""
    return next(w for w in _windows_around(now, cadence, tz) if w.opens_at > now)


def _windows_around(now: datetime, cadence: Cadence, tz: str) -> Iterator[Window]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    zone = ZoneInfo(tz)
    local_date = now.astimezone(zone).date()
    for offset in range(-SEARCH_DAYS_BEFORE, SEARCH_DAYS_AFTER + 1):
        anchor = local_date + timedelta(days=offset)
        if cadence == Cadence.DAILY:
            window = Window(
                _to_utc(anchor, UPDATE_TIME, zone),
                _to_utc(anchor + timedelta(days=1), UPDATE_TIME, zone),
            )
        elif anchor.weekday() == SUNDAY:
            window = Window(
                _to_utc(anchor, WEEKLY_OPEN_TIME, zone),
                _to_utc(anchor + timedelta(days=1), UPDATE_TIME, zone),
            )
        else:
            continue
        if window.closes_at > window.opens_at:
            yield window


def _to_utc(day: date, at: time, zone: ZoneInfo) -> datetime:
    # Converting via UTC normalises non-existent local times (see module docstring).
    return datetime.combine(day, at, tzinfo=zone).astimezone(UTC)
