"""The only module that reads votes together with their voter (NFA-06, VOT-07, VOT-09).

It hands out only what may be shown: a voter's own votes, and while the window is open
nothing about other people's votes except how many members have voted. The matrix and
reasons of open periods follow in M7.
"""

from sqlalchemy import distinct, func, select

from app.extensions import db
from app.models import Period, Vote


def own_votes(period: Period, voter_id: int) -> dict[int, int]:
    """Target user id → +1 or −1. Voters always see their own votes (OVW-07)."""
    rows = db.session.execute(
        select(Vote.target_user_id, Vote.value).where(
            Vote.period_id == period.id, Vote.voter_user_id == voter_id
        )
    )
    return {target: value for target, value in rows}


def voter_count(period: Period) -> int:
    """How many members have cast at least one vote; all VOT-07 allows while open."""
    return db.session.scalar(
        select(func.count(distinct(Vote.voter_user_id))).where(Vote.period_id == period.id)
    )
