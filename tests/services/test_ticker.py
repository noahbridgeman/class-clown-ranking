"""The ticker on every group page (docs/design.md section 3, A22)."""

import pytest

from app.services import membership
from app.services.leaderboard import leaderboard
from app.services.ticker import Trend, ticker
from tests.factories import add_member, make_daily, make_group, make_user, next_day, tick, vote


@pytest.fixture
def daily(app):
    ada, bo, cleo = (make_user(display_name=name) for name in ("Ada", "Bo", "Cleo"))
    group = make_daily(make_group(ada))
    add_member(group, bo)
    add_member(group, cleo)
    tick()
    return group, ada, bo, cleo


def test_before_the_first_result_everyone_is_new(daily):
    group, *_ = daily
    data = ticker(leaderboard(group.id))
    assert data.average is None
    assert [(i.score, i.trend) for i in data.members] == [("5,0", Trend.NEW)] * 3


def test_average_and_its_change(daily, clock):
    """The mean of the scores; its change the mean of the shown changes, new ones left out."""
    group, ada, bo, cleo = daily
    next_day(clock)  # everyone has a result now, nobody a change yet
    vote(group, ada, bo, "up")
    vote(group, cleo, bo, "up")
    vote(group, bo, cleo, "down")
    next_day(clock)
    board = leaderboard(group.id)
    data = ticker(board)
    scores = [row.score for row in board.rows]
    assert data.average.score == f"{sum(scores) / 3:.1f}".replace(".", ",")
    by_name = {item.label: item for item in data.members}
    assert by_name["Bo"].trend == Trend.UP and by_name["Bo"].change.startswith("▲")
    assert by_name["Cleo"].trend == Trend.DOWN and by_name["Cleo"].change.startswith("▼")
    assert " " not in by_name["Bo"].change  # compact: "▲1,2"


def test_no_change_is_flat(daily, clock):
    group, *_ = daily
    next_day(clock)
    next_day(clock)
    data = ticker(leaderboard(group.id))
    assert {item.trend for item in data.members} == {Trend.FLAT}
    assert {item.change for item in data.members} == {"–"}


def test_returner_without_new_result(daily, clock):
    group, ada, bo, _cleo = daily
    vote(group, ada, bo, "up")
    next_day(clock)
    membership.leave(group, bo)
    next_day(clock)
    add_member(group, bo)
    bo_item = next(i for i in ticker(leaderboard(group.id)).members if i.label == "Bo")
    assert (bo_item.trend, bo_item.change) == (Trend.FLAT, "")
