from datetime import timedelta

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Vote
from app.services import membership, periods, vote_queries, voting
from app.services.errors import InvalidInput, NotFound
from tests.factories import (
    IN_WEEK_WINDOW,
    WEEK_CLOSES,
    WEEK_OPENS,
    add_member,
    make_group,
    make_user,
    tick,
    vote,
)


@pytest.fixture
def trio(app, clock):
    a, b, c = (make_user(display_name=name) for name in "ABC")
    group = make_group(a)
    add_member(group, b)
    add_member(group, c)
    clock.set(IN_WEEK_WINDOW)
    tick()
    return group, a, b, c


def own(group, user):
    return vote_queries.own_votes(periods.open_period(group.id), user.id)


class TestSetVote:
    def test_cast_change_and_retract(self, trio, clock):
        """VOT-02, VOT-05: one vote per pair, changeable until the window ends."""
        group, a, b, _ = trio
        vote(group, a, b, "up")
        assert own(group, a) == {b.id: 1}
        clock.advance(timedelta(hours=1))
        vote(group, a, b, "down")
        row = db.session.scalar(select(Vote))
        assert (row.value, row.created_at, row.updated_at) == (
            -1,
            IN_WEEK_WINDOW,
            IN_WEEK_WINDOW + timedelta(hours=1),
        )
        vote(group, a, b, "none")
        assert own(group, a) == {}

    def test_retracting_without_a_vote_is_harmless(self, trio):
        group, a, b, _ = trio
        vote(group, a, b, "none")
        assert own(group, a) == {}

    def test_same_vote_twice_keeps_one_row(self, trio):
        group, a, b, _ = trio
        vote(group, a, b, "up")
        vote(group, a, b, "up")
        assert len(db.session.scalars(select(Vote)).all()) == 1

    def test_self_vote_is_refused(self, trio):
        """VOT-03."""
        group, a, *_ = trio
        with pytest.raises(InvalidInput) as error:
            vote(group, a, a, "up")
        assert error.value.message_key == "voting.self_vote"

    def test_target_must_be_an_active_member(self, trio):
        group, a, b, _ = trio
        membership.leave(group, b)
        for target in (b, make_user()):
            with pytest.raises(InvalidInput) as error:
                vote(group, a, target, "up")
            assert error.value.message_key == "voting.not_a_member"

    def test_voter_must_be_an_active_member(self, trio):
        group, a, *_ = trio
        with pytest.raises(NotFound):
            vote(group, make_user(), a, "up")

    def test_admin_votes_like_everyone(self, trio):
        """ROL-04: same rules, no extra weight."""
        group, admin, b, _ = trio
        assert group.admin_user_id == admin.id
        vote(group, admin, b, "down")
        assert own(group, admin) == {b.id: -1}

    def test_refused_outside_the_window(self, app):
        group = make_group()
        other = add_member(group)
        with pytest.raises(InvalidInput) as error:
            vote(group, group.admin, other, "up")
        assert error.value.message_key == "voting.closed"

    def test_late_vote_is_refused_before_the_update_ran(self, trio, clock):
        """PER-03: checked against closes_at, not the status."""
        group, a, b, _ = trio
        vote(group, a, b, "up")
        clock.set(WEEK_CLOSES)
        for choice in ("down", "none"):
            with pytest.raises(InvalidInput):
                vote(group, a, b, choice)
        clock.set(WEEK_CLOSES - timedelta(days=2))
        assert own(group, a) == {b.id: 1}

    def test_new_member_votes_in_the_running_period(self, trio):
        """INV-06."""
        group, a, *_ = trio
        newcomer = add_member(group)
        vote(group, newcomer, a, "up")
        vote(group, a, newcomer, "down")
        assert own(group, newcomer) == {a.id: 1}


class TestQueries:
    def test_voter_count_counts_people_not_votes(self, trio):
        """VOT-07: the only thing others learn while the window is open."""
        group, a, b, c = trio
        period = periods.open_period(group.id)
        assert vote_queries.voter_count(period) == 0
        vote(group, a, b, "up")
        vote(group, a, c, "up")
        vote(group, b, a, "down")
        assert vote_queries.voter_count(period) == 2

    def test_own_votes_are_only_the_voters(self, trio):
        group, a, b, c = trio
        vote(group, a, b, "up")
        vote(group, c, b, "down")
        assert own(group, a) == {b.id: 1}
        assert own(group, b) == {}


class TestBallot:
    def test_open_window(self, trio):
        group, a, b, c = trio
        vote(group, a, b, "up")
        vote(group, c, a, "up")
        ballot = voting.ballot(group, a)
        assert ballot.period == periods.open_period(group.id)
        assert [m.user_id for m in ballot.others] == [b.id, c.id]
        assert ballot.own == {b.id: 1}
        assert (ballot.rated, ballot.voters, ballot.members) == (1, 2, 3)

    def test_outside_the_window_names_the_next_one(self, app):
        """VOT-10."""
        group = make_group()
        ballot = voting.ballot(group, group.admin)
        assert ballot.period is None
        assert ballot.next_opens_at == WEEK_OPENS

    def test_after_the_window_names_the_next_week(self, trio, clock):
        group, a, *_ = trio
        clock.set(WEEK_CLOSES)  # the update has not run yet
        ballot = voting.ballot(group, a)
        assert ballot.period is None
        # Sunday 00:00 is 23:00 UTC now that winter time has begun.
        assert ballot.next_opens_at == WEEK_OPENS + timedelta(days=7, hours=1)

    def test_window_started_but_not_opened_yet(self, app, clock):
        group = make_group()
        clock.set(WEEK_OPENS)
        ballot = voting.ballot(group, group.admin)
        assert (ballot.period, ballot.next_opens_at) == (None, None)
