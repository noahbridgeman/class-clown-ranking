"""The voting overview and the member detail view (OVW-01…07, A23)."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Period, PeriodStatus
from app.services import membership, overview, voting
from app.services.errors import NotFound
from tests.factories import (
    IN_WEEK_WINDOW,
    WEEK_CLOSES,
    add_member,
    make_group,
    make_user,
    tick,
    vote,
)

WEEK = timedelta(days=7)


@pytest.fixture
def trio(app, clock):
    a, b, c = (make_user(display_name=name) for name in ("Ada", "Bo", "Cleo"))
    group = make_group(a, "Runde")
    add_member(group, b)
    add_member(group, c)
    return group, a, b, c


def open_week(clock, week: int = 0) -> None:
    clock.set(IN_WEEK_WINDOW + week * WEEK)
    tick()


def close_week(clock, week: int = 0) -> None:
    clock.set(WEEK_CLOSES + week * WEEK)
    tick()


def set_anonymous(group, anonymous: bool) -> None:
    """Directly, as the effective setting the next window copies."""
    group.is_anonymous = anonymous
    db.session.commit()


class TestPeriodPage:
    def test_nothing_before_the_first_window(self, trio):
        group, a, _b, _c = trio
        assert overview.period_page(group, a) is None
        with pytest.raises(NotFound):
            overview.period_page(group, a, 1)

    def test_running_period_shows_only_own_votes(self, trio, clock):
        """OVW-06, OVW-07."""
        group, a, b, c = trio
        open_week(clock)
        vote(group, a, b, "up")
        vote(group, b, c, "down")
        page = overview.period_page(group, a)
        assert page.running
        assert page.entries == [] and page.matrix == {} and page.reasons == []
        assert page.own == {b.id: 1}
        assert [u.id for u in page.others] == [b.id, c.id]

    def test_anonymous_period_shows_counts_but_no_voters(self, trio, clock):
        """OVW-02, NFA-06."""
        group, a, b, c = trio
        open_week(clock)
        vote(group, a, c, "up")
        vote(group, b, c, "down")
        vote(group, c, a, "up")
        close_week(clock)
        page = overview.period_page(group, b)
        assert not page.running and page.period.is_anonymous
        assert page.matrix == {} and page.reasons == []
        by_user = {e.user.id: e for e in page.entries}
        assert (by_user[c.id].ups, by_user[c.id].downs, by_user[c.id].net) == (1, 1, 0.0)
        assert (by_user[a.id].ups, by_user[a.id].downs, by_user[a.id].net) == (1, 0, 1.0)
        assert page.own == {c.id: -1}  # the viewer's own vote only (OVW-07)

    def test_open_period_shows_matrix_and_reasons(self, trio, clock):
        """OVW-03, OVW-04."""
        group, a, b, c = trio
        set_anonymous(group, False)
        open_week(clock)
        vote(group, a, b, "up")
        vote(group, c, b, "down")
        voting.set_reason(group, a, b.id, "Die Ente")
        close_week(clock)
        page = overview.period_page(group, c)
        assert page.matrix == {(a.id, b.id): 1, (c.id, b.id): -1}
        assert [(v.voter_id, v.target_id, v.reason) for v in page.reasons] == [
            (a.id, b.id, "Die Ente")
        ]
        assert page.reasoned == {(a.id, b.id)}

    def test_entries_are_sorted_by_score_with_the_displayed_change(self, trio, clock):
        """A23: the change of the first result is measured against 5.0."""
        group, a, b, c = trio
        open_week(clock)
        vote(group, a, b, "up")
        vote(group, c, b, "up")
        vote(group, b, a, "down")
        close_week(clock)
        entries = overview.period_page(group, a).entries
        assert [e.user.id for e in entries] == [b.id, c.id, a.id]
        assert entries[0].delta > 0 and entries[1].delta == 0 and entries[2].delta < 0

    def test_navigation_skips_skipped_periods(self, trio, clock):
        """OVW-01, PER-06, A23."""
        group, a, b, c = trio
        open_week(clock)
        close_week(clock)
        membership.leave(group, b)
        membership.leave(group, c)
        open_week(clock, 1)
        close_week(clock, 1)  # one member left: skipped
        add_member(group, b)
        open_week(clock, 2)
        statuses = {p.seq: p.status for p in group_periods(group)}
        assert statuses == {1: PeriodStatus.CLOSED, 2: PeriodStatus.SKIPPED, 3: PeriodStatus.OPEN}
        newest = overview.period_page(group, a)
        assert (newest.period.seq, newest.older, newest.newer) == (3, 1, None)
        first = overview.period_page(group, a, 1)
        assert (first.older, first.newer) == (None, 3)
        with pytest.raises(NotFound):
            overview.period_page(group, a, 2)
        with pytest.raises(NotFound):
            overview.period_page(group, a, 9)

    def test_who_was_not_part_of_a_period_has_no_own_votes_there(self, trio, clock):
        group, a, b, _c = trio
        open_week(clock)
        vote(group, a, b, "up")
        close_week(clock)
        late = add_member(group, make_user(display_name="Dora"))
        page = overview.period_page(group, late, 1)
        assert not page.is_member and page.own == {}
        assert late.id not in {e.user.id for e in page.entries}


def group_periods(group) -> list[Period]:
    return list(db.session.scalars(select(Period).where(Period.group_id == group.id)))


class TestMemberHistory:
    @pytest.fixture
    def two_weeks(self, trio, clock):
        """Week 1 anonymous, week 2 open, with votes on and by Bo."""
        group, a, b, c = trio
        open_week(clock)
        vote(group, a, b, "up")
        vote(group, b, c, "down")
        close_week(clock)
        set_anonymous(group, False)
        open_week(clock, 1)
        vote(group, a, b, "down")
        voting.set_reason(group, a, b.id, "Zu laut")
        vote(group, c, b, "up")
        vote(group, b, a, "up")
        close_week(clock, 1)
        return trio

    def test_results_newest_first(self, two_weeks):
        """OVW-05."""
        group, a, b, _c = two_weeks
        history = overview.member_history(group, a, b.id)
        assert [i.period.seq for i in history.items] == [2, 1]
        assert [(i.entry.ups, i.entry.downs) for i in history.items] == [(1, 1), (1, 0)]
        assert history.scores == [i.entry.score for i in reversed(history.items)]

    def test_votes_only_from_open_periods_for_others(self, two_weeks):
        """OVW-05, NFA-06: Bo's anonymous vote on Cleo stays hidden from Ada."""
        group, a, b, _c = two_weeks
        week2, week1 = overview.member_history(group, a, b.id).items
        assert week2.cast == {a.id: 1}
        assert [(v.voter_id, v.reason) for v in week2.received] == [(a.id, "Zu laut")]
        assert week1.cast == {} and week1.received == []

    def test_own_detail_shows_own_anonymous_votes(self, two_weeks):
        """OVW-07."""
        group, a, b, c = two_weeks
        week2, week1 = overview.member_history(group, b, b.id).items
        assert week1.cast == {c.id: -1}
        assert week2.cast == {a.id: 1}

    def test_former_members_have_a_history(self, two_weeks):
        group, a, b, _c = two_weeks
        membership.leave(group, b)
        history = overview.member_history(group, a, b.id)
        assert not history.member.is_active and len(history.items) == 2

    def test_strangers_are_not_found(self, two_weeks):
        group, a, _b, _c = two_weeks
        with pytest.raises(NotFound):
            overview.member_history(group, a, make_user().id)

    def test_a_switch_to_open_does_not_reveal_anonymous_periods(self, two_weeks):
        """VOT-09, SET-06: the period's snapshot decides, not the current setting."""
        group, a, b, _c = two_weeks
        assert not group.is_anonymous
        week1 = overview.member_history(group, a, b.id).items[1]
        assert week1.period.is_anonymous and week1.cast == {}
