"""RNK-01…03 with stored results (A7, A12, A13)."""

import pytest

from app.domain import ranking, scoring
from app.domain.formatting import round_half_up
from app.domain.types import Cadence
from app.services import membership
from app.services.leaderboard import _previous_delta, leaderboard
from tests.factories import add_member, make_daily, make_group, make_user, next_day, tick, vote


@pytest.fixture
def daily(app):
    """A daily group of Ada, Bo and Cleo with its first window open."""
    ada, bo, cleo = (make_user(display_name=name) for name in ("Ada", "Bo", "Cleo"))
    group = make_daily(make_group(ada))
    add_member(group, bo)
    add_member(group, cleo)
    tick()
    return group, ada, bo, cleo


def order(board) -> list[int]:
    return [row.member.user_id for row in board.rows]


def row_of(board, user):
    return next(row for row in board.rows if row.member.user_id == user.id)


def test_without_results_everyone_is_new_at_five(daily):
    """INV-06: r = 0 means score 5,0; all share place 1 (A7)."""
    group, *_ = daily
    board = leaderboard(group.id)
    assert board.as_of is None
    assert [(row.place, row.score, row.delta, row.is_new) for row in board.rows] == [
        (1, 5.0, None, True)
    ] * 3


def test_sorted_by_score(daily, clock):
    group, ada, bo, cleo = daily
    vote(group, ada, bo, "up")
    vote(group, cleo, bo, "up")
    vote(group, bo, cleo, "up")
    vote(group, ada, cleo, "down")
    vote(group, bo, ada, "down")
    next_day(clock)
    board = leaderboard(group.id)
    assert order(board) == [bo.id, cleo.id, ada.id]
    assert [row.place for row in board.rows] == [1, 2, 3]
    assert board.as_of is not None


def test_first_result_has_no_change(daily, clock):
    """A12: newcomers have no change, even after their first result."""
    group, ada, bo, _cleo = daily
    vote(group, ada, bo, "up")
    next_day(clock)
    board = leaderboard(group.id)
    assert all(row.delta is None and row.is_new for row in board.rows)
    assert board.highlights.biggest_gain is None


def test_change_is_the_difference_of_the_displayed_scores(daily, clock):
    """RNK-02 / A13: the change of the latest period, from the rounded numbers."""
    group, ada, bo, cleo = daily
    vote(group, ada, bo, "up")
    next_day(clock)
    before = {row.member.user_id: row.score for row in leaderboard(group.id).rows}
    vote(group, ada, cleo, "up")
    vote(group, bo, cleo, "up")
    vote(group, cleo, bo, "down")
    next_day(clock)
    board = leaderboard(group.id)
    for row in board.rows:
        displayed = round_half_up(row.score) - round_half_up(before[row.member.user_id])
        assert row.delta == float(displayed)
        assert not row.is_new
    assert row_of(board, cleo).delta > 0
    assert row_of(board, bo).delta < 0


def test_highlights_and_place_changes(daily, clock):
    """RNK-03: biggest gain, biggest drop, new leader and places moved."""
    group, ada, bo, cleo = daily
    vote(group, ada, bo, "up")
    vote(group, cleo, bo, "up")
    vote(group, bo, ada, "up")
    next_day(clock)  # Bo, Ada, Cleo
    vote(group, ada, cleo, "up")
    vote(group, bo, cleo, "up")
    vote(group, ada, bo, "down")
    vote(group, cleo, bo, "down")
    next_day(clock)
    board = leaderboard(group.id)
    assert order(board)[0] == cleo.id
    assert board.highlights.biggest_gain.user_ids == (cleo.id,)
    assert board.highlights.biggest_drop.user_ids == (bo.id,)
    assert board.highlights.new_leaders == (cleo.id,)
    assert row_of(board, cleo).place_change == 2
    assert row_of(board, bo).place_change < 0


def test_shows_only_active_members(daily, clock):
    """RNK-01, and nobody moves up just because someone left (A12)."""
    group, ada, bo, _cleo = daily
    vote(group, ada, bo, "up")
    vote(group, bo, ada, "up")
    next_day(clock)
    membership.leave(group, bo)
    next_day(clock)
    board = leaderboard(group.id)
    assert bo.id not in order(board)
    assert all(row.place_change == 0 for row in board.rows)


def test_newcomer_after_the_latest_result(daily, clock):
    group, ada, bo, _cleo = daily
    vote(group, ada, bo, "up")
    next_day(clock)
    newcomer = add_member(group)
    row = row_of(leaderboard(group.id), newcomer)
    assert (row.score, row.delta, row.is_new) == (5.0, None, True)


def test_rejoined_member_takes_back_the_old_score(daily, clock):
    """MEM-04: the score shown is the one from leaving, without a change."""
    group, ada, bo, _cleo = daily
    vote(group, ada, bo, "up")
    next_day(clock)
    score = row_of(leaderboard(group.id), bo).score
    membership.leave(group, bo)
    next_day(clock)
    add_member(group, bo)
    row = row_of(leaderboard(group.id), bo)
    assert (row.score, row.delta, row.is_new) == (score, None, False)
    assert score > scoring.score(0.0)


def test_skipped_periods_are_ignored(app, clock):
    """A2: a period with too few members has no results and does not reset the board."""
    ada, bo = make_user(), make_user()
    group = make_daily(make_group(ada))
    add_member(group, bo)
    tick()
    vote(group, ada, bo, "up")
    next_day(clock)
    as_of = leaderboard(group.id).as_of
    membership.leave(group, bo)
    next_day(clock)  # skipped
    board = leaderboard(group.id)
    assert board.as_of == as_of
    assert order(board) == [ada.id]


def test_returning_after_the_latest_result_moves_nobody(daily, clock):
    """A20: a returner with a high score is sorted in, but changes no movement and
    is no new leader until the next period has run."""
    group, ada, bo, cleo = daily
    vote(group, ada, bo, "up")
    vote(group, cleo, bo, "up")
    next_day(clock)
    membership.leave(group, bo)
    vote(group, ada, cleo, "up")
    next_day(clock)
    add_member(group, bo)
    board = leaderboard(group.id)
    assert order(board) == [bo.id, cleo.id, ada.id]
    # Cleo passed Ada in the latest period; Bo's return moves nobody further down.
    changes = {row.member.user_id: row.place_change for row in board.rows}
    assert changes == {bo.id: 0, cleo.id: 0, ada.id: -1}
    assert board.highlights.new_leaders == ()
    assert board.highlights.biggest_gain.user_ids == (cleo.id,)


def test_open_votes_change_nothing(daily, clock):
    """NFA-06 / VOT-07: the board only reads closed results."""
    group, ada, bo, cleo = daily
    vote(group, ada, bo, "up")
    next_day(clock)
    before = leaderboard(group.id)
    vote(group, ada, cleo, "up")
    vote(group, bo, ada, "down")
    assert leaderboard(group.id) == before


class TestLabelsFromStoredResults:
    """A22 with real periods: best score, recovering, below the start, sparklines."""

    def test_best_so_far_and_sparkline(self, daily, clock):
        group, ada, bo, cleo = daily
        for _ in range(3):
            vote(group, ada, bo, "up")
            vote(group, cleo, bo, "up")
            next_day(clock)
        row = row_of(leaderboard(group.id), bo)
        assert row.label == ranking.Label.BEST
        assert row.sparkline[0] == 0.0 and row.sparkline[-1] == 1.0
        assert len(row.sparkline) == 3

    def test_change_of_the_period_before(self):
        """Feeds "recovering" (A22): the shown change one period before the latest."""
        assert _previous_delta([5.0, 4.54, 4.8]) == pytest.approx(-0.5)  # 4,5 − 5,0 as shown
        assert _previous_delta([5.0, 4.8]) is None

    def test_sparkline_shows_at_most_six_periods(self, daily, clock):
        group, *_ = daily
        for _ in range(8):
            next_day(clock)
        assert {len(row.sparkline) for row in leaderboard(group.id).rows} == {6}

    def test_cadence_comes_from_the_period_not_the_setting(self, daily, clock):
        """SET-01: a later cadence change does not rename the period shown."""
        group, *_ = daily
        next_day(clock)
        group.cadence = Cadence.WEEKLY
        assert leaderboard(group.id).cadence == Cadence.DAILY
