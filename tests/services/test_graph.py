"""GRA-01…07 and MEM-03: the data behind the graph."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.i18n import load_texts
from app.services import graph, membership, settings
from app.services.graph import Range, graph_data, parse_range
from app.services.leaderboard import leaderboard
from tests.factories import add_member, make_daily, make_group, make_user, next_day, tick, vote


@pytest.fixture
def daily(app):
    ada, bo = make_user(display_name="Ada"), make_user(display_name="Bo")
    group = make_daily(make_group(ada))
    add_member(group, bo)
    tick()
    return group, ada, bo


def data(group, viewer, clock, range_=Range.FOUR_WEEKS):
    return graph_data(group, viewer.id, range_, clock.now())


def series_of(result, user):
    return next(s for s in result["series"] if s["id"] == user.id)


def test_one_point_per_closed_period_and_member(daily, clock):
    """GRA-01, GRA-04: score (rounded and as text), ups and downs per period."""
    group, ada, bo = daily
    vote(group, ada, bo, "up")
    next_day(clock)
    vote(group, ada, bo, "down")
    next_day(clock)
    result = data(group, ada, clock)
    assert len(result["periods"]) == 2
    assert result["periods"][0]["date"] == "24.10.2026"
    assert result["periods"][0]["t"] < result["periods"][1]["t"]
    first, second = series_of(result, bo)["points"]
    assert first[1:] == [1, 0]
    assert second[1:] == [0, 1]
    assert first[0] > 5 and first[0] == round(first[0], 1)
    assert series_of(result, ada)["points"][0][1:] == [0, 0]


def test_contains_only_results_never_voters(daily, clock):
    """NFA-06: per point the score and the counts received, nothing about who voted."""
    group, ada, bo = daily
    vote(group, ada, bo, "up")
    vote(group, bo, ada, "down")
    next_day(clock)
    result = data(group, ada, clock)
    assert set(result) == {"range", "cadence", "periods", "series", "markers"}
    for series in result["series"]:
        assert set(series) == {"id", "name", "role", "me", "former", "points"}
        assert all(len(point) == 3 for point in series["points"])
    assert {m["kind"] for m in result["markers"]} == {"member"}


def test_open_period_does_not_appear(daily, clock):
    """Only closed periods have points, so nothing about running votes leaks (NFA-06)."""
    group, ada, bo = daily
    vote(group, ada, bo, "up")
    assert data(group, ada, clock)["series"] == []


def test_roles_names_and_own_series(daily, clock):
    """GRA-02: lines carry their role from the leaderboard instead of a color per person."""
    group, ada, bo = daily
    next_day(clock)
    roles = {ada.id: graph.Role.LEADER}
    result = graph_data(group, bo.id, Range.FOUR_WEEKS, clock.now(), roles)
    ada_series = series_of(result, ada)
    assert ada_series["name"] == "Ada"
    assert (ada_series["role"], series_of(result, bo)["role"]) == ("leader", None)
    assert (ada_series["me"], series_of(result, bo)["me"]) == (False, True)
    assert result["cadence"] == "daily"


def test_roles_from_the_leaderboard(daily, clock):
    """Biggest gain and drop win over place 1; ties share the role."""
    group, ada, bo = daily
    cleo = add_member(group, make_user(display_name="Cleo"))
    next_day(clock)
    vote(group, bo, ada, "up")
    vote(group, cleo, ada, "up")
    vote(group, ada, bo, "up")
    vote(group, cleo, bo, "down")  # Bo: net 0, no change
    vote(group, ada, cleo, "down")
    next_day(clock)
    found = graph.roles(leaderboard(group.id))
    assert found[ada.id] == graph.Role.GAIN
    assert found[cleo.id] == graph.Role.DROP
    assert bo.id not in found


@pytest.mark.parametrize(
    ("range_", "periods"), [(Range.WEEK, 7), (Range.FOUR_WEEKS, 28), (Range.ALL, 40)]
)
def test_ranges(daily, clock, range_, periods):
    """GRA-03: the range counts back from now."""
    group, ada, _bo = daily
    for _ in range(40):
        next_day(clock)
    assert len(data(group, ada, clock, range_)["periods"]) == periods


@pytest.mark.parametrize(
    "now",
    [
        datetime(2027, 4, 2, 11, 0, 30, tzinfo=UTC),  # a week back crosses 28.3.
        datetime(2026, 10, 30, 12, 0, 30, tzinfo=UTC),  # a week back crosses 25.10.
    ],
)
def test_a_week_is_seven_local_days_across_daylight_saving(now):
    """GRA-03 counts in the group's time: 13:00 a week ago, whatever the UTC offset."""
    start = graph.range_start(Range.WEEK, now, "Europe/Berlin")
    berlin = ZoneInfo("Europe/Berlin")
    assert start.astimezone(berlin).time() == now.astimezone(berlin).time()
    assert start.astimezone(berlin).date() == (now.astimezone(berlin) - timedelta(days=7)).date()
    assert graph.range_start(Range.ALL, now, "Europe/Berlin") is None


def test_parse_range():
    assert parse_range(None) is graph.DEFAULT_RANGE is Range.FOUR_WEEKS
    assert parse_range("1y") is Range.YEAR
    assert parse_range("2w") is None


def test_every_range_has_a_label():
    texts = load_texts("de")
    assert set(graph.RANGE_LABELS) == set(Range)
    assert all(key in texts for key in graph.RANGE_LABELS.values())
    assert all(key in texts for key in graph.MEMBER_MARKERS.values())


def test_former_member_line_ends_and_breaks(daily, clock):
    """MEM-03: still in the graph, with a gap while away, and back after rejoining."""
    group, ada, bo = daily
    cleo = add_member(group, make_user(display_name="Cleo"))
    next_day(clock)
    membership.leave(group, bo)
    next_day(clock)
    next_day(clock)
    result = data(group, ada, clock)
    bo_series = series_of(result, bo)
    assert bo_series["former"] is True
    assert bo_series["points"][0] is not None
    assert bo_series["points"][1:] == [None, None]
    add_member(group, bo)
    next_day(clock)
    points = series_of(data(group, cleo, clock), bo)["points"]
    assert [p is not None for p in points] == [True, False, False, True]


def test_members_without_points_are_left_out(daily, clock):
    group, ada, _bo = daily
    next_day(clock)
    newcomer = add_member(group)
    assert newcomer.id not in [s["id"] for s in data(group, ada, clock)["series"]]


def test_markers_for_joins_and_departures(daily, clock):
    """GRA-07: only inside the range."""
    group, ada, bo = daily
    next_day(clock)
    add_member(group, make_user(display_name="Cleo"))
    membership.leave(group, bo)
    texts = [m["text"] for m in data(group, ada, clock)["markers"]]
    assert texts == [
        "Ada ist beigetreten",
        "Bo ist beigetreten",
        "Cleo ist beigetreten",
        "Bo ist ausgetreten",
    ]
    assert set(data(group, ada, clock)["markers"][2]) == {"t", "date", "kind", "text"}
    for _ in range(8):
        next_day(clock)
    assert data(group, ada, clock, Range.WEEK)["markers"] == []


def test_markers_for_removal_and_return(daily, clock):
    group, ada, bo = daily
    membership.remove(group, ada, bo.id)
    add_member(group, bo)
    texts = [m["text"] for m in data(group, ada, clock)["markers"]]
    assert texts[-2:] == ["Bo wurde entfernt", "Bo ist zurück"]


def test_markers_for_switching_between_anonymous_and_open(daily, clock):
    """GRA-07: at the start of the first period in the other mode."""
    group, ada, _bo = daily
    next_day(clock)
    group.is_anonymous = False  # the settings flow follows in M6
    next_day(clock)
    next_day(clock)
    group.is_anonymous = True
    next_day(clock)
    modes = [m for m in data(group, ada, clock)["markers"] if m["kind"] == "mode"]
    assert [m["text"] for m in modes] == ["Ab hier nicht anonym", "Ab hier anonym"]
    assert modes[1]["t"] - modes[0]["t"] == timedelta(days=2) / timedelta(milliseconds=1)


def test_markers_for_settings_changes(daily, clock):
    """GRA-07 / SET-03: where a window took over changes; anonymity has its own marker."""
    group, ada, _bo = daily
    wanted = replace(settings.upcoming(group), name="Neu", is_anonymous=False)
    settings.change(group, ada, wanted)
    next_day(clock)
    texts = [m["text"] for m in data(group, ada, clock)["markers"] if m["kind"] != "member"]
    assert texts == ["Ab hier nicht anonym", "Einstellungen geändert: Gruppenname"]
