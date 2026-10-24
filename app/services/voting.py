"""Casting, changing and retracting votes (VOT-02…05, VOT-09, MEM-05, ROL-04)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import delete, or_, select

from app.clock import get_clock
from app.domain import schedule
from app.extensions import db
from app.models import Group, Membership, Period, User, Vote
from app.models.period import REASON_MAX_LENGTH
from app.services import membership, periods, settings, vote_queries
from app.services.errors import InvalidInput
from app.services.locks import lock_group
from app.services.text import clean_text


class Choice(StrEnum):
    UP = "up"
    DOWN = "down"
    NONE = "none"  # abstain, or take a vote back (VOT-04, VOT-05)


VALUES: dict[Choice, int | None] = {Choice.UP: 1, Choice.DOWN: -1, Choice.NONE: None}


@dataclass(frozen=True)
class Ballot:
    """What the voting page shows one member (VOT-06, VOT-07, VOT-10)."""

    now: datetime
    period: Period | None  # set while the window accepts votes
    others: list[Membership]  # everyone the member can rate
    own: dict[int, int]  # target user id → +1 or −1
    reasons: dict[int, str]  # target user id → own reason, open periods only (VOT-08)
    voters: int  # members who have voted so far
    members: int
    next_opens_at: datetime | None  # outside a window; None if one opens any moment
    timezone: str  # of the next window; differs from the group's while a change is pending

    @property
    def rated(self) -> int:
        return sum(1 for m in self.others if m.user_id in self.own)


def ballot(group: Group, user: User) -> Ballot:
    now = get_clock().now()
    active = membership.active_members(group.id)
    others = [m for m in active if m.user_id != user.id]
    period = periods.open_period(group.id)
    if period is not None and period.accepts_votes(now):
        return Ballot(
            now=now,
            period=period,
            others=others,
            own=vote_queries.own_votes(period, user.id),
            reasons=vote_queries.own_reasons(period, user.id),
            voters=vote_queries.voter_count(period),
            members=len(active),
            next_opens_at=None,
            timezone=group.timezone,
        )
    # Between the window's start and the next tick no period exists yet.
    # The next window follows the upcoming settings (SET-01, PER-05).
    upcoming = settings.upcoming(group)
    pending = schedule.window_at(now, upcoming.cadence, upcoming.timezone)
    next_opens_at = None
    # An expired period not yet closed is the latest one too, so had_period sees it.
    if pending is None or periods.had_period(group.id, pending):
        next_opens_at = schedule.next_window(now, upcoming.cadence, upcoming.timezone).opens_at
    return Ballot(now, None, others, {}, {}, 0, len(active), next_opens_at, upcoming.timezone)


def set_vote(group: Group, voter: User, target_id: int, choice: Choice) -> None:
    """Sets, changes or retracts the voter's vote on one member in the running window.

    The admin votes like everyone else (ROL-04). The window's end is checked inside the
    locked transaction, so a vote racing the update is either counted or refused (PER-03).
    """
    lock_group(group)
    membership.require_active(group.id, voter.id)
    if target_id == voter.id:
        raise InvalidInput("voting.self_vote")  # VOT-03
    if membership.active_membership(group.id, target_id) is None:
        raise InvalidInput("voting.not_a_member")
    now = get_clock().now()
    period = periods.open_period(group.id)
    if period is None or not period.accepts_votes(now):
        raise InvalidInput("voting.closed")
    vote = db.session.scalar(
        select(Vote).where(
            Vote.period_id == period.id,
            Vote.voter_user_id == voter.id,
            Vote.target_user_id == target_id,
        )
    )
    value = VALUES[choice]
    if value is None:
        if vote is not None:
            db.session.delete(vote)
    elif vote is None:
        db.session.add(
            Vote(
                period_id=period.id,
                voter_user_id=voter.id,
                target_user_id=target_id,
                value=value,
                created_at=now,
                updated_at=now,
            )
        )
    elif vote.value != value:
        vote.value = value
        vote.updated_at = now
    db.session.commit()


def set_reason(group: Group, voter: User, target_id: int, raw: str | None) -> None:
    """VOT-08: an optional reason on the voter's own vote, only in open periods.

    Empty text removes it. Retracting the vote removes the reason with it.
    """
    lock_group(group)
    membership.require_active(group.id, voter.id)
    reason = clean_text(raw, REASON_MAX_LENGTH)
    period = periods.open_period(group.id)
    if period is None or not period.accepts_votes(get_clock().now()):
        raise InvalidInput("voting.closed")
    if period.is_anonymous:
        raise InvalidInput("voting.reason_anonymous")
    vote = db.session.scalar(
        select(Vote).where(
            Vote.period_id == period.id,
            Vote.voter_user_id == voter.id,
            Vote.target_user_id == target_id,
        )
    )
    if vote is None:
        raise InvalidInput("voting.reason_needs_vote")
    vote.reason = reason
    db.session.commit()


def discard_open_votes(group_id: int, user_id: int) -> None:
    """MEM-05 and A3: a leaving member's votes in the open period, cast and received.

    Votes of closed periods stay. Does not commit; the caller holds lock_group.
    """
    period = periods.open_period(group_id)
    if period is None:
        return
    db.session.execute(
        delete(Vote).where(
            Vote.period_id == period.id,
            or_(Vote.voter_user_id == user_id, Vote.target_user_id == user_id),
        )
    )
