"""Injectable clock. The only place in the app that reads the system time."""

from datetime import UTC, datetime, timedelta
from typing import Protocol

from flask import current_app


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Clock for tests: stands still until it is set or advanced explicitly."""

    def __init__(self, at: datetime) -> None:
        self._now = _to_utc(at)

    def now(self) -> datetime:
        return self._now

    def set(self, at: datetime) -> None:
        self._now = _to_utc(at)

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def get_clock() -> Clock:
    return current_app.extensions["clock"]


def _to_utc(at: datetime) -> datetime:
    if at.tzinfo is None:
        raise ValueError("FrozenClock needs a timezone-aware datetime")
    return at.astimezone(UTC)
