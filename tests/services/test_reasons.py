"""VOT-08: optional reasons on single votes, only in open periods."""

import pytest
import sqlalchemy.exc
from sqlalchemy import select, update

from app.extensions import db
from app.models import Vote
from app.services import periods, vote_queries, voting
from app.services.errors import InvalidInput
from tests.factories import (
    IN_WEEK_WINDOW,
    WEEK_CLOSES,
    add_member,
    make_group,
    make_user,
    tick,
    vote,
)


def window(clock, anonymous: bool):
    a, b, c = make_user(), make_user(), make_user()
    group = make_group(a)
    group.is_anonymous = anonymous  # the settings flow is tested elsewhere
    add_member(group, b)
    add_member(group, c)
    clock.set(IN_WEEK_WINDOW)
    tick()
    return group, a, b, c


@pytest.fixture
def open_mode(app, clock):
    return window(clock, anonymous=False)


def stored_reason(voter, target):
    return db.session.scalar(
        select(Vote.reason).where(Vote.voter_user_id == voter.id, Vote.target_user_id == target.id)
    )


def test_reason_on_own_vote(open_mode):
    group, a, b, _c = open_mode
    vote(group, a, b, "up")
    voting.set_reason(group, a, b.id, "  Der   Witz mit der Ente ")
    assert stored_reason(a, b) == "Der Witz mit der Ente"
    period = periods.open_period(group.id)
    assert vote_queries.own_reasons(period, a.id) == {b.id: "Der Witz mit der Ente"}
    assert vote_queries.own_reasons(period, b.id) == {}


def test_empty_text_removes_it(open_mode):
    group, a, b, _c = open_mode
    vote(group, a, b, "up")
    voting.set_reason(group, a, b.id, "gut")
    voting.set_reason(group, a, b.id, "   ")
    assert stored_reason(a, b) is None


def test_stays_when_the_vote_changes_and_goes_with_it(open_mode):
    group, a, b, _c = open_mode
    vote(group, a, b, "up")
    voting.set_reason(group, a, b.id, "gut")
    vote(group, a, b, "down")
    assert stored_reason(a, b) == "gut"
    vote(group, a, b, "none")
    assert stored_reason(a, b) is None


def test_only_with_a_vote(open_mode):
    group, a, b, _c = open_mode
    with pytest.raises(InvalidInput, match="reason_needs_vote"):
        voting.set_reason(group, a, b.id, "gut")


def test_not_in_anonymous_periods(app, clock):
    group, a, b, _c = window(clock, anonymous=True)
    vote(group, a, b, "up")
    with pytest.raises(InvalidInput, match="reason_anonymous"):
        voting.set_reason(group, a, b.id, "gut")


def test_period_mode_counts_not_the_group_setting(open_mode):
    """VOT-09: a group switched to anonymous keeps reasons in the running open period."""
    group, a, b, _c = open_mode
    group.is_anonymous = True
    vote(group, a, b, "up")
    voting.set_reason(group, a, b.id, "gut")
    assert stored_reason(a, b) == "gut"


def test_not_after_the_window(open_mode, clock):
    group, a, b, _c = open_mode
    vote(group, a, b, "up")
    clock.set(WEEK_CLOSES)
    with pytest.raises(InvalidInput, match="closed"):
        voting.set_reason(group, a, b.id, "gut")


@pytest.mark.parametrize(("length", "ok"), [(140, True), (141, False)])
def test_length_limit(open_mode, length, ok):
    group, a, b, _c = open_mode
    vote(group, a, b, "up")
    if ok:
        voting.set_reason(group, a, b.id, "x" * length)
        assert len(stored_reason(a, b)) == length
    else:
        with pytest.raises(InvalidInput, match="text_too_long"):
            voting.set_reason(group, a, b.id, "x" * length)


def test_invisible_characters_are_rejected(open_mode):
    group, a, b, _c = open_mode
    vote(group, a, b, "up")
    with pytest.raises(InvalidInput, match="text_invalid"):
        voting.set_reason(group, a, b.id, "gut‮evil")


def test_database_enforces_the_length(open_mode):
    group, a, b, _c = open_mode
    vote(group, a, b, "up")
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db.session.execute(update(Vote).values(reason="x" * 141))
    db.session.rollback()
