from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.clock import FrozenClock, SystemClock, get_clock


def test_app_uses_injected_clock(app, clock):
    assert get_clock() is clock


def test_frozen_clock_normalizes_to_utc():
    cet = timezone(timedelta(hours=1))
    clock = FrozenClock(datetime(2026, 1, 1, 13, 0, tzinfo=cet))
    assert clock.now() == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert clock.now().tzinfo is UTC


def test_frozen_clock_set_and_advance():
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    clock.advance(timedelta(hours=2))
    assert clock.now() == datetime(2026, 1, 1, 2, 0, tzinfo=UTC)
    clock.set(datetime(2026, 5, 1, tzinfo=UTC))
    assert clock.now() == datetime(2026, 5, 1, tzinfo=UTC)


def test_frozen_clock_rejects_naive_datetimes():
    with pytest.raises(ValueError):
        FrozenClock(datetime(2026, 1, 1))


def test_system_clock_is_timezone_aware():
    assert SystemClock().now().tzinfo is UTC
