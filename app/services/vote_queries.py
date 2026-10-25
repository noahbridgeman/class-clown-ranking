"""The only module that reads votes together with their voter (NFA-06, VOT-07, VOT-09).

It hands out only what may be shown: a voter's own votes, while the window is open
nothing about other people's votes except how many members have voted, and who voted
whom only once a period that was not anonymous has closed (OVW-03…07). How many ups and
downs someone received comes from the stored results, not from here.
"""

from dataclasses import dataclass

from sqlalchemy import distinct, func, or_, select

from app.extensions import db
from app.models import Period, PeriodStatus, Vote


class AnonymityViolation(RuntimeError):
    """Votes of an anonymous or still running period were asked for with their voter."""


@dataclass(frozen=True)
class OpenVote:
    """A vote of a closed period that was not anonymous; everyone in the group may see it."""

    period_id: int
    voter_id: int
    target_id: int
    value: int  # +1 or −1
    reason: str | None


def own_votes(period: Period, voter_id: int) -> dict[int, int]:
    """Target user id → +1 or −1. Voters always see their own votes (OVW-07)."""
    rows = db.session.execute(
        select(Vote.target_user_id, Vote.value).where(
            Vote.period_id == period.id, Vote.voter_user_id == voter_id
        )
    )
    return {target: value for target, value in rows}


def own_reasons(period: Period, voter_id: int) -> dict[int, str]:
    """Target user id → the voter's own reason (VOT-08)."""
    rows = db.session.execute(
        select(Vote.target_user_id, Vote.reason).where(
            Vote.period_id == period.id, Vote.voter_user_id == voter_id, Vote.reason.is_not(None)
        )
    )
    return {target: reason for target, reason in rows}


def voter_count(period: Period) -> int:
    """How many members have cast at least one vote; all VOT-07 allows while open."""
    return db.session.scalar(
        select(func.count(distinct(Vote.voter_user_id))).where(Vote.period_id == period.id)
    )


def own_votes_by_period(group_id: int, voter_id: int) -> dict[int, dict[int, int]]:
    """Period id → the voter's own votes in every closed period of the group (OVW-07)."""
    rows = db.session.execute(
        select(Vote.period_id, Vote.target_user_id, Vote.value)
        .join(Period, Period.id == Vote.period_id)
        .where(
            Period.group_id == group_id,
            Period.status == PeriodStatus.CLOSED,
            Vote.voter_user_id == voter_id,
        )
    )
    votes: dict[int, dict[int, int]] = {}
    for period_id, target, value in rows:
        votes.setdefault(period_id, {})[target] = value
    return votes


def open_votes(period: Period) -> list[OpenVote]:
    """Every vote of a closed period that was not anonymous: matrix and reasons (OVW-03, OVW-04)."""
    if period.is_anonymous or period.status != PeriodStatus.CLOSED:
        raise AnonymityViolation(f"period {period.id} is anonymous or not closed")
    return _open_votes(Vote.period_id == period.id)


def open_votes_of(group_id: int, user_id: int) -> list[OpenVote]:
    """The votes a member cast or received in closed periods that were not anonymous (OVW-05)."""
    return _open_votes(
        Period.group_id == group_id,
        or_(Vote.voter_user_id == user_id, Vote.target_user_id == user_id),
    )


def _open_votes(*criteria: object) -> list[OpenVote]:
    # The period's snapshot decides, never the group's current setting (VOT-09).
    rows = db.session.execute(
        select(Vote.period_id, Vote.voter_user_id, Vote.target_user_id, Vote.value, Vote.reason)
        .join(Period, Period.id == Vote.period_id)
        .where(Period.is_anonymous.is_(False), Period.status == PeriodStatus.CLOSED, *criteria)
        .order_by(Vote.period_id, Vote.id)
    )
    return [OpenVote(*row) for row in rows]
