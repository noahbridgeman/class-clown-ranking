from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.domain import scoring
from app.domain.types import Cadence
from app.extensions import db
from app.models import Group, LoginToken, Period, PeriodResult, PeriodStatus, Vote
from app.services import groups, membership, periods
from tests.factories import (
    IN_WEEK_WINDOW,
    WEEK_CLOSES,
    WEEK_OPENS,
    add_member,
    make_daily,
    make_group,
    make_user,
    tick,
    vote,
)


def all_periods(group: Group) -> list[Period]:
    return list(
        db.session.scalars(select(Period).where(Period.group_id == group.id).order_by(Period.seq))
    )


def results(period: Period) -> dict[int, PeriodResult]:
    rows = db.session.scalars(select(PeriodResult).where(PeriodResult.period_id == period.id))
    return {row.user_id: row for row in rows}


@pytest.fixture
def trio(app, clock):
    """A weekly group of three with its window open."""
    a, b, c = (make_user(display_name=name) for name in "ABC")
    group = make_group(a)
    add_member(group, b)
    add_member(group, c)
    clock.set(IN_WEEK_WINDOW)
    tick()
    return group, a, b, c


class TestOpening:
    def test_no_period_outside_the_window(self, app):
        group = make_group()  # the clock stands on a Friday
        assert tick().opened == 0
        assert all_periods(group) == []

    def test_window_opens_with_a_snapshot_of_the_settings(self, app, clock):
        group = make_group()
        clock.set(WEEK_OPENS)
        assert tick().opened == 1
        [period] = all_periods(group)
        assert (period.seq, period.status) == (1, PeriodStatus.OPEN)
        assert (period.opens_at, period.closes_at) == (WEEK_OPENS, WEEK_CLOSES)
        assert (period.cadence, period.is_anonymous) == (Cadence.WEEKLY, True)
        assert (period.k, period.d) == (group.k, group.d)

    def test_opens_for_a_single_member_so_newcomers_can_join_in(self, app, clock):
        """A2 / INV-06: the window opens anyway; only the result is skipped."""
        group = make_group()
        clock.set(IN_WEEK_WINDOW)
        tick()
        assert periods.open_period(group.id) is not None

    def test_daily_window(self, app, clock):
        group = make_daily(make_group())
        tick()  # Fri 14:00 Berlin
        [period] = all_periods(group)
        assert period.opens_at == datetime(2026, 10, 23, 11, 0, tzinfo=UTC)
        assert period.closes_at == datetime(2026, 10, 24, 11, 0, tzinfo=UTC)
        assert period.cadence == Cadence.DAILY

    def test_running_twice_opens_once(self, app, clock):
        group = make_group()
        clock.set(IN_WEEK_WINDOW)
        tick()
        assert tick().opened == 0
        assert len(all_periods(group)) == 1


class TestClosing:
    def test_results_follow_the_formulas(self, trio, clock):
        group, a, b, c = trio
        vote(group, a, b, "up")
        vote(group, c, b, "up")
        vote(group, a, c, "down")
        clock.set(WEEK_CLOSES)
        report = tick()
        assert (report.closed, report.skipped) == (1, 0)
        [period] = all_periods(group)
        assert (period.status, period.closed_at) == (PeriodStatus.CLOSED, WEEK_CLOSES)
        stored = results(period)
        assert {u: (r.ups, r.downs, r.net) for u, r in stored.items()} == {
            a.id: (0, 0, 0.0),
            b.id: (2, 0, 1.0),
            c.id: (0, 1, -1.0),
        }
        assert stored[b.id].rating_after == pytest.approx(0.5)
        assert stored[c.id].rating_after == pytest.approx(-0.5)
        assert stored[b.id].score == pytest.approx(scoring.score(0.5))
        assert stored[a.id].score == 5.0

    def test_window_end_is_exclusive(self, trio, clock):
        group, *_ = trio
        clock.set(WEEK_CLOSES - timedelta(microseconds=1))
        assert tick().closed == 0
        assert all_periods(group)[0].status == PeriodStatus.OPEN

    def test_ratings_carry_over_and_decay_without_votes(self, trio, clock):
        """SCO-05: everyone decays each period, with or without votes."""
        group, a, b, _c = trio
        vote(group, a, b, "up")
        clock.set(WEEK_CLOSES)
        tick()
        clock.set(IN_WEEK_WINDOW + timedelta(days=7))
        tick()
        clock.set(WEEK_CLOSES + timedelta(days=7))
        tick()
        first, second = all_periods(group)
        assert second.seq == 2
        assert results(second)[b.id].rating_before == results(first)[b.id].rating_after
        assert results(second)[b.id].rating_after == pytest.approx(0.95 * 0.5)

    def test_single_member_is_skipped(self, app, clock):
        """PER-06 / A2: no results and no decay."""
        group = make_group()
        clock.set(IN_WEEK_WINDOW)
        tick()
        clock.set(WEEK_CLOSES)
        assert tick().skipped == 1
        [period] = all_periods(group)
        assert period.status == PeriodStatus.SKIPPED
        assert period.closed_at == WEEK_CLOSES
        assert results(period) == {}

    def test_skipped_when_the_others_left(self, trio, clock):
        group, _a, b, c = trio
        membership.leave(group, b)
        membership.leave(group, c)
        clock.set(WEEK_CLOSES)
        assert tick().skipped == 1

    def test_uses_the_snapshot_not_the_changed_group(self, trio, clock):
        """VOT-09, SET-01: settings changed during the window apply from the next one."""
        group, a, b, _c = trio
        group.k, group.d, group.is_anonymous = 2.0, 0.5, False
        db.session.commit()
        vote(group, a, b, "up")
        clock.set(WEEK_CLOSES)
        tick()
        [period] = all_periods(group)
        assert (period.k, period.is_anonymous) == (0.5, True)
        assert results(period)[b.id].rating_after == pytest.approx(0.5)

    def test_next_period_takes_the_new_settings(self, trio, clock):
        group, *_ = trio
        group.is_anonymous = False
        db.session.commit()
        clock.set(WEEK_CLOSES)
        tick()
        clock.set(IN_WEEK_WINDOW + timedelta(days=7))
        tick()
        assert [p.is_anonymous for p in all_periods(group)] == [True, False]

    def test_catch_up_closes_late_and_skips_missed_windows(self, app, clock):
        """PER-03 / A1: a late run closes the period; windows missed entirely get none."""
        a = make_user()
        group = make_daily(make_group(a))
        b = add_member(group)
        tick()  # window Fri 13:00 – Sat 13:00
        vote(group, a, b, "up")
        clock.set(datetime(2026, 10, 27, 9, 0, tzinfo=UTC))  # Tue 10:00, three updates late
        report = tick()
        assert (report.closed, report.opened) == (1, 1)
        first, second = all_periods(group)
        assert first.closed_at == clock.now()
        assert results(first)[b.id].ups == 1
        assert second.seq == 2
        assert second.opens_at == datetime(2026, 10, 26, 12, 0, tzinfo=UTC)  # Mon 13:00 CET

    def test_daily_close_and_open_happen_in_one_run(self, app, clock):
        group = make_daily(make_group())
        add_member(group)
        tick()
        clock.set(datetime(2026, 10, 24, 11, 0, tzinfo=UTC))
        report = tick()
        assert (report.skipped, report.closed, report.opened) == (0, 1, 1)
        first, second = all_periods(group)
        assert second.opens_at == first.closes_at


class TestMembers:
    def test_newcomer_starts_at_zero_and_takes_part_at_once(self, trio, clock):
        """INV-06: votes and is voted on in the running period."""
        group, a, _b, _c = trio
        clock.set(WEEK_CLOSES)
        tick()
        clock.set(IN_WEEK_WINDOW + timedelta(days=7))
        tick()
        newcomer = add_member(group)
        vote(group, newcomer, a, "up")
        vote(group, a, newcomer, "up")
        clock.set(WEEK_CLOSES + timedelta(days=7))
        tick()
        result = results(all_periods(group)[1])[newcomer.id]
        assert (result.rating_before, result.ups) == (0.0, 1)

    def test_rejoining_takes_back_the_old_rating(self, trio, clock):
        """MEM-04 and SCO-08: the rating stands still while away and returns with the member."""
        group, a, b, _c = trio
        vote(group, a, b, "up")
        clock.set(WEEK_CLOSES)
        tick()
        rating = results(all_periods(group)[0])[b.id].rating_after
        membership.leave(group, b)
        clock.set(IN_WEEK_WINDOW + timedelta(days=7))
        tick()
        clock.set(WEEK_CLOSES + timedelta(days=7))
        tick()
        assert b.id not in results(all_periods(group)[1])
        clock.set(IN_WEEK_WINDOW + timedelta(days=14))
        tick()
        add_member(group, b)
        clock.set(WEEK_CLOSES + timedelta(days=14))
        tick()
        assert results(all_periods(group)[2])[b.id].rating_before == rating

    def test_votes_of_a_member_who_left_are_discarded(self, trio, clock):
        """MEM-05 / A3: cast and received votes of the open period go."""
        group, a, b, c = trio
        vote(group, b, a, "up")
        vote(group, c, b, "down")
        vote(group, c, a, "up")
        membership.leave(group, b)
        clock.set(WEEK_CLOSES)
        tick()
        stored = results(all_periods(group)[0])
        assert set(stored) == {a.id, c.id}
        assert (stored[a.id].ups, stored[a.id].downs) == (1, 0)

    def test_votes_of_closed_periods_stay_when_someone_leaves(self, trio, clock):
        group, a, b, _c = trio
        vote(group, b, a, "up")
        clock.set(WEEK_CLOSES)
        tick()
        membership.leave(group, b)
        assert db.session.scalar(select(Vote).where(Vote.voter_user_id == b.id)) is not None

    def test_removed_member_loses_open_votes(self, trio, clock):
        group, a, b, c = trio
        vote(group, b, c, "up")
        membership.remove(group, a, b.id)
        assert db.session.scalars(select(Vote)).all() == []

    def test_joining_after_the_window_ended_takes_no_part(self, trio, clock):
        group, *_ = trio
        clock.set(WEEK_CLOSES + timedelta(minutes=5))  # the update is late
        late = add_member(group)
        tick()
        assert late.id not in results(all_periods(group)[0])


class TestRobustness:
    def test_a_failing_group_does_not_stop_the_others(self, app, clock, monkeypatch):
        broken, fine = make_group(), make_group()
        add_member(broken)
        add_member(fine)
        clock.set(IN_WEEK_WINDOW)
        tick()
        original = periods._close

        def close(period, now):
            if period.group_id == broken.id:
                raise RuntimeError("boom")
            return original(period, now)

        monkeypatch.setattr(periods, "_close", close)
        clock.set(WEEK_CLOSES)
        report = tick()
        assert report.failed == [broken.id]
        assert report.closed == 1
        assert periods.open_period(broken.id) is not None  # rolled back, retried next run

    def test_deleting_a_group_removes_its_periods(self, trio, clock):
        group, a, b, _c = trio
        vote(group, a, b, "up")
        clock.set(WEEK_CLOSES)
        tick()
        groups.delete_group(group, a, group.name)
        assert db.session.scalars(select(Period)).all() == []
        assert db.session.scalars(select(Vote)).all() == []
        assert db.session.scalars(select(PeriodResult)).all() == []

    def test_removes_login_tokens_the_rate_limit_no_longer_counts(self, app, clock):
        now = clock.now()
        for age, hash_ in ((timedelta(minutes=20), "recent"), (timedelta(hours=2), "old")):
            db.session.add(
                LoginToken(
                    email="a@example.org",
                    nonce_hash=hash_,
                    created_at=now - age,
                    expires_at=now - age + timedelta(minutes=15),
                )
            )
        db.session.commit()
        assert tick().tokens_removed == 1
        assert db.session.scalars(select(LoginToken.nonce_hash)).all() == ["recent"]


class TestCurrentRatings:
    def test_defaults_to_zero(self, app):
        group = make_group()
        assert periods.current_ratings(group.id, [1, 2]) == {1: 0.0, 2: 0.0}

    def test_is_per_group(self, trio, clock):
        """GRP-03: a rating in one group does not leak into another."""
        group, a, b, _c = trio
        other = make_group(a)
        add_member(other, b)
        vote(group, a, b, "up")
        clock.set(WEEK_CLOSES)
        tick()
        assert periods.current_ratings(other.id, [b.id]) == {b.id: 0.0}
