from datetime import UTC, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from app.domain.schedule import Window, next_window, window_at
from app.domain.types import Cadence

BERLIN = "Europe/Berlin"
# DST starts at midnight here, so Sunday 00:00 does not exist on 2026-09-06.
SANTIAGO = "America/Santiago"
MONDAY_WEEKDAY, SUNDAY_WEEKDAY = 0, 6


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "opens", "closes"),
    [
        pytest.param(
            utc(2026, 10, 23, 12), utc(2026, 10, 23, 11), utc(2026, 10, 24, 11), id="summer"
        ),
        pytest.param(utc(2026, 12, 1, 6), utc(2026, 11, 30, 12), utc(2026, 12, 1, 12), id="winter"),
        pytest.param(
            utc(2026, 10, 25, 0), utc(2026, 10, 24, 11), utc(2026, 10, 25, 12), id="dst end"
        ),
        pytest.param(
            utc(2026, 3, 29, 0), utc(2026, 3, 28, 12), utc(2026, 3, 29, 11), id="dst start"
        ),
        pytest.param(
            utc(2026, 12, 31, 23), utc(2026, 12, 31, 12), utc(2027, 1, 1, 12), id="new year"
        ),
    ],
)
def test_daily_window(now, opens, closes):
    assert window_at(now, Cadence.DAILY, BERLIN) == Window(opens, closes)


def test_daily_window_lengths_follow_dst():
    autumn = window_at(utc(2026, 10, 25, 0), Cadence.DAILY, BERLIN)
    spring = window_at(utc(2026, 3, 29, 0), Cadence.DAILY, BERLIN)

    assert autumn.closes_at - autumn.opens_at == timedelta(hours=25)
    assert spring.closes_at - spring.opens_at == timedelta(hours=23)


def test_daily_windows_have_no_gaps():
    now = utc(2026, 1, 1, 12)
    for _ in range(400):
        window = window_at(now, Cadence.DAILY, BERLIN)
        assert window is not None
        following = window_at(window.closes_at, Cadence.DAILY, BERLIN)
        assert following.opens_at == window.closes_at
        now = window.closes_at


def test_daily_window_boundaries_are_half_open():
    opens, closes = utc(2026, 10, 23, 11), utc(2026, 10, 24, 11)
    tick = timedelta(microseconds=1)

    assert window_at(opens, Cadence.DAILY, BERLIN).opens_at == opens
    assert window_at(closes - tick, Cadence.DAILY, BERLIN).closes_at == closes
    assert window_at(closes, Cadence.DAILY, BERLIN).opens_at == closes


@pytest.mark.parametrize(
    ("now", "opens", "closes"),
    [
        pytest.param(
            utc(2026, 10, 18, 12), utc(2026, 10, 17, 22), utc(2026, 10, 19, 11), id="summer"
        ),
        pytest.param(utc(2026, 12, 7, 11), utc(2026, 12, 5, 23), utc(2026, 12, 7, 12), id="winter"),
        pytest.param(
            utc(2026, 10, 25, 5), utc(2026, 10, 24, 22), utc(2026, 10, 26, 12), id="dst end"
        ),
        pytest.param(
            utc(2026, 3, 29, 5), utc(2026, 3, 28, 23), utc(2026, 3, 30, 11), id="dst start"
        ),
    ],
)
def test_weekly_window(now, opens, closes):
    assert window_at(now, Cadence.WEEKLY, BERLIN) == Window(opens, closes)


@pytest.mark.parametrize(
    "now",
    [
        pytest.param(utc(2026, 10, 19, 11), id="monday 13:00 exactly"),
        pytest.param(utc(2026, 10, 21, 12), id="wednesday"),
        pytest.param(utc(2026, 10, 24, 21, 59, 59), id="saturday 23:59:59"),
    ],
)
def test_no_weekly_window_between_monday_and_sunday(now):
    assert window_at(now, Cadence.WEEKLY, BERLIN) is None


def test_weekly_window_opens_at_sunday_midnight_exactly():
    assert window_at(utc(2026, 10, 17, 22), Cadence.WEEKLY, BERLIN).opens_at == utc(
        2026, 10, 17, 22
    )


def test_weekly_window_when_midnight_does_not_exist():
    window = window_at(utc(2026, 9, 6, 12), Cadence.WEEKLY, SANTIAGO)

    # 00:00 −04 is skipped; the window opens at the first instant after the gap, 01:00 −03.
    assert window == Window(utc(2026, 9, 6, 4), utc(2026, 9, 7, 16))


def test_weekly_window_when_saturday_evening_repeats():
    window = window_at(utc(2026, 4, 5, 12), Cadence.WEEKLY, SANTIAGO)

    assert window == Window(utc(2026, 4, 5, 4), utc(2026, 4, 6, 17))
    assert window.closes_at - window.opens_at == timedelta(hours=37)


@pytest.mark.parametrize(
    ("now", "expected_open"),
    [
        pytest.param(utc(2026, 10, 23, 10, 59), utc(2026, 10, 23, 11), id="before 13:00"),
        pytest.param(utc(2026, 10, 23, 11), utc(2026, 10, 24, 11), id="at 13:00"),
        pytest.param(utc(2026, 10, 24, 12), utc(2026, 10, 25, 12), id="across dst end"),
    ],
)
def test_next_daily_window(now, expected_open):
    assert next_window(now, Cadence.DAILY, BERLIN).opens_at == expected_open


@pytest.mark.parametrize(
    ("now", "expected_open"),
    [
        pytest.param(utc(2026, 10, 21, 12), utc(2026, 10, 24, 22), id="wednesday"),
        pytest.param(utc(2026, 10, 25, 5), utc(2026, 10, 31, 23), id="inside a window"),
        pytest.param(utc(2026, 10, 24, 22), utc(2026, 10, 31, 23), id="at opening"),
        pytest.param(utc(2026, 9, 1, 12), utc(2026, 9, 6, 4), id="into dst gap"),
    ],
)
def test_next_weekly_window(now, expected_open):
    tz = SANTIAGO if now.month == 9 else BERLIN
    window = next_window(now, Cadence.WEEKLY, tz)

    assert window.opens_at == expected_open
    assert window.opens_at > now


def test_other_timezone_input_is_handled():
    now = datetime(2026, 10, 23, 14, tzinfo=timezone(timedelta(hours=2)))

    assert window_at(now, Cadence.DAILY, BERLIN).opens_at == utc(2026, 10, 23, 11)


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        window_at(datetime(2026, 10, 23, 12), Cadence.DAILY, BERLIN)


def test_unknown_timezone_is_rejected():
    with pytest.raises(ZoneInfoNotFoundError):
        window_at(utc(2026, 10, 23, 12), Cadence.DAILY, "Mars/Olympus_Mons")


@pytest.mark.parametrize("tz", [BERLIN, SANTIAGO])
def test_weekly_windows_chain_over_a_year(tz):
    zone = ZoneInfo(tz)
    window = next_window(utc(2026, 1, 1), Cadence.WEEKLY, tz)
    for _ in range(52):
        opens_local = window.opens_at.astimezone(zone)
        closes_local = window.closes_at.astimezone(zone)
        assert opens_local.weekday() == SUNDAY_WEEKDAY
        # 00:00, or 01:00 when midnight falls into a DST gap.
        assert opens_local.time() in (time(0), time(1))
        assert (closes_local.weekday(), closes_local.time()) == (MONDAY_WEEKDAY, time(13))
        assert window_at(window.opens_at, Cadence.WEEKLY, tz) == window

        following = next_window(window.opens_at, Cadence.WEEKLY, tz)
        assert following.opens_at.astimezone(zone).date() - opens_local.date() == timedelta(7)
        window = following


def test_daily_window_unaffected_by_midnight_dst_change():
    window = window_at(utc(2026, 9, 6, 12), Cadence.DAILY, SANTIAGO)

    # 13:00 −04 on Saturday to 13:00 −03 on Sunday: the gap shortens it to 23 hours.
    assert window == Window(utc(2026, 9, 5, 17), utc(2026, 9, 6, 16))


def test_skipped_calendar_day_gives_no_empty_window():
    """Samoa skipped 2011-12-30 entirely."""
    tz = "Pacific/Apia"
    window = window_at(utc(2011, 12, 29, 22), Cadence.DAILY, tz)
    following = next_window(window.opens_at, Cadence.DAILY, tz)

    assert window == Window(utc(2011, 12, 28, 23), utc(2011, 12, 29, 23))
    assert following == Window(utc(2011, 12, 29, 23), utc(2011, 12, 30, 23))
    after = next_window(following.opens_at, Cadence.DAILY, tz)
    assert after.opens_at == following.closes_at
    assert after.closes_at > after.opens_at
