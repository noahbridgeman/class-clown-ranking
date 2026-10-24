"""The period update (PER-01…06), run every minute by `flask --app app tick`.

Per group and in one locked transaction: close the open period once its window has
ended and store the results, then open the period of the current window. Running it
again changes nothing (PER-02). After downtime the close is caught up, windows missed
entirely are not (PER-03, A1).
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime

from flask import current_app
from sqlalchemy import func, select

from app.clock import get_clock
from app.domain import schedule, scoring
from app.domain.types import UserId
from app.extensions import db
from app.models import Group, Period, PeriodResult, PeriodStatus, Vote
from app.services import auth, membership
from app.services.errors import NotFound
from app.services.locks import lock_group

MIN_MEMBERS = 2  # PER-06


@dataclass
class TickReport:
    opened: int = 0
    closed: int = 0
    skipped: int = 0
    tokens_removed: int = 0
    failed: list[int] = field(default_factory=list)


def tick() -> TickReport:
    """Updates every group. A failing group is rolled back and reported, the others go on."""
    now = get_clock().now()
    report = TickReport()
    for group_id in db.session.scalars(select(Group.id).order_by(Group.id)).all():
        try:
            closed, opened = _tick_group(group_id, now)
        except Exception:
            db.session.rollback()
            current_app.logger.exception("tick failed for group %s", group_id)
            report.failed.append(group_id)
            continue
        report.closed += closed is PeriodStatus.CLOSED
        report.skipped += closed is PeriodStatus.SKIPPED
        report.opened += opened
    report.tokens_removed = auth.delete_stale_tokens(now)
    db.session.commit()
    return report


def _tick_group(group_id: int, now: datetime) -> tuple[PeriodStatus | None, bool]:
    group = db.session.get(Group, group_id)
    if group is None:
        return None, False
    try:
        lock_group(group)
    except NotFound:
        return None, False  # deleted since the list was read
    # Read again under the lock: a parallel run may have done the work already (PER-02).
    closed = close_if_due(group_id, now)
    opened = open_period(group_id) is None and _open_current(group, now)
    db.session.commit()
    return closed, opened


def open_period(group_id: int) -> Period | None:
    return db.session.scalar(
        select(Period).where(Period.group_id == group_id, Period.status == PeriodStatus.OPEN)
    )


def latest_period(group_id: int) -> Period | None:
    return db.session.scalar(
        select(Period).where(Period.group_id == group_id).order_by(Period.seq.desc()).limit(1)
    )


def close_if_due(group_id: int, now: datetime) -> PeriodStatus | None:
    """Closes the open period if its window has ended. The caller holds lock_group.

    Joining, leaving and removing call this first, so the members at closing are always
    those at the window's end, however late tick runs (PER-03, VOT-05, MEM-05).
    Does not commit.
    """
    period = open_period(group_id)
    if period is None or now < period.closes_at:
        return None
    return _close(period, now)


def _close(period: Period, now: datetime) -> PeriodStatus:
    """PER-01 steps 1–2 for the active members."""
    member_ids = [UserId(m.user_id) for m in membership.active_members(period.group_id)]
    if len(member_ids) < MIN_MEMBERS:
        period.status = PeriodStatus.SKIPPED  # no results and no decay (A2)
    else:
        results = scoring.compute_period(
            current_ratings(period.group_id, member_ids), _votes(period), period.params
        )
        db.session.add_all(
            PeriodResult(period_id=period.id, user_id=user_id, **asdict(result))
            for user_id, result in results.items()
        )
        period.status = PeriodStatus.CLOSED
    period.closed_at = now
    return period.status


def _votes(period: Period) -> list[tuple[UserId, UserId, int]]:
    rows = db.session.execute(
        select(Vote.voter_user_id, Vote.target_user_id, Vote.value).where(
            Vote.period_id == period.id
        )
    )
    return [(UserId(voter), UserId(target), value) for voter, target, value in rows]


def _open_current(group: Group, now: datetime) -> bool:
    """PER-01 step 4: a period for the window containing now, with the group's settings.

    Pending settings are applied here first from M6 on (E1, SET-01).
    """
    window = schedule.window_at(now, group.cadence, group.timezone)
    if window is None:
        return False
    if had_period(group.id, window):
        return False
    previous = latest_period(group.id)
    db.session.add(
        Period(
            group_id=group.id,
            seq=previous.seq + 1 if previous else 1,
            opens_at=window.opens_at,
            closes_at=window.closes_at,
            cadence=group.cadence,
            is_anonymous=group.is_anonymous,
            k=group.k,
            d=group.d,
            status=PeriodStatus.OPEN,
        )
    )
    return True


def had_period(group_id: int, window: schedule.Window) -> bool:
    """Whether the window overlaps the latest period, so it must not get one of its own."""
    previous = latest_period(group_id)
    return previous is not None and window.opens_at < previous.closes_at


def current_ratings(group_id: int, user_ids: list[UserId]) -> dict[UserId, float]:
    """The rating after each member's latest result in the group.

    Newcomers start at 0 (INV-06). Former members keep the rating they left with, and
    take it back when they rejoin (SCO-08, MEM-04).
    """
    latest = (
        select(PeriodResult.user_id, func.max(Period.seq).label("seq"))
        .join(Period, Period.id == PeriodResult.period_id)
        .where(Period.group_id == group_id, PeriodResult.user_id.in_(user_ids))
        .group_by(PeriodResult.user_id)
        .subquery()
    )
    rows = db.session.execute(
        select(PeriodResult.user_id, PeriodResult.rating_after)
        .join(Period, Period.id == PeriodResult.period_id)
        .join(
            latest,
            (latest.c.user_id == PeriodResult.user_id) & (latest.c.seq == Period.seq),
        )
        .where(Period.group_id == group_id)
    )
    ratings = dict.fromkeys(user_ids, 0.0)
    ratings.update({UserId(user_id): rating for user_id, rating in rows})
    return ratings
