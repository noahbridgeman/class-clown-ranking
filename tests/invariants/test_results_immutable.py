"""SCO-06: stored results are never recomputed. VOT-09: a period's snapshot never changes."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import ImmutableError, Period, PeriodResult
from tests.factories import IN_WEEK_WINDOW, WEEK_CLOSES, add_member, make_group, tick, vote


@pytest.fixture
def closed(app, clock):
    group = make_group()
    other = add_member(group)
    clock.set(IN_WEEK_WINDOW)
    tick()
    vote(group, group.admin, other, "up")
    clock.set(WEEK_CLOSES)
    tick()
    return group


def stored() -> list[tuple]:
    rows = db.session.scalars(select(PeriodResult).order_by(PeriodResult.id))
    return [
        (r.user_id, r.ups, r.downs, r.net, r.rating_before, r.rating_after, r.score) for r in rows
    ]


def test_results_cannot_be_changed(closed):
    result = db.session.scalar(select(PeriodResult))
    result.score = 9.9
    with pytest.raises(ImmutableError):
        db.session.commit()


def test_later_runs_and_new_settings_leave_results_alone(closed, clock):
    before = stored()
    closed.k, closed.d = 2.0, 0.5
    db.session.commit()
    tick()
    clock.set(WEEK_CLOSES + timedelta(minutes=5))
    tick()
    assert stored() == before


@pytest.mark.parametrize(
    ("field", "value"),
    [("is_anonymous", False), ("k", 2.0), ("d", 0.5), ("seq", 7)],
)
def test_snapshot_cannot_be_changed(closed, field, value):
    period = db.session.scalar(select(Period))
    setattr(period, field, value)
    with pytest.raises(ImmutableError, match=field):
        db.session.commit()


def test_status_may_change_while_open(app, clock):
    """Closing sets status and closed_at; that is no snapshot change."""
    make_group()
    clock.set(IN_WEEK_WINDOW)
    tick()
    clock.set(WEEK_CLOSES)
    assert tick().failed == []
