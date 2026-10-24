"""SET-01 and VOT-09 as invariants: a change never reaches the running or a past period.

Changes every setting at every moment of a period's life and checks that the snapshots of
all existing periods stay as they were.
"""

from dataclasses import replace
from datetime import timedelta

from sqlalchemy import select

from app.domain import scoring
from app.domain.types import Cadence
from app.extensions import db
from app.models import Period
from app.services import settings
from tests.factories import IN_WEEK_WINDOW, WEEK_CLOSES, WEEK_OPENS, add_member, make_group, tick


def snapshots(group):
    rows = db.session.scalars(
        select(Period).where(Period.group_id == group.id).order_by(Period.seq)
    )
    return [(p.seq, p.opens_at, p.closes_at, p.cadence, p.is_anonymous, p.k, p.d) for p in rows]


def test_changes_never_touch_existing_periods(app, clock):
    group = make_group()
    add_member(group)
    daily = scoring.convert_params(settings.effective(group).params, Cadence.WEEKLY, Cadence.DAILY)
    variants = [
        {"is_anonymous": False},
        {"k": 0.9, "d": 0.9},
        {"timezone": "Asia/Tokyo"},
        {"cadence": Cadence.DAILY, "k": daily.k, "d": daily.d},
        {"name": "Anders"},
    ]
    original = settings.upcoming(group)
    for moment in [WEEK_OPENS, IN_WEEK_WINDOW, WEEK_CLOSES - timedelta(seconds=1)]:
        clock.set(moment)
        tick()
        before = snapshots(group)
        for values in variants:
            for wanted in (replace(original, **values), original):
                settings.change(group, group.admin, wanted)
                tick()
                assert snapshots(group) == before


def test_switching_to_open_leaves_past_periods_anonymous(app, clock):
    """SET-06 / VOT-09"""
    group = make_group()
    add_member(group)
    clock.set(IN_WEEK_WINDOW)
    tick()
    settings.change(group, group.admin, replace(settings.upcoming(group), is_anonymous=False))
    clock.set(WEEK_CLOSES)
    tick()
    clock.set(IN_WEEK_WINDOW + timedelta(days=7))
    tick()
    anonymity = [s[4] for s in snapshots(group)]
    assert anonymity == [True, False]
