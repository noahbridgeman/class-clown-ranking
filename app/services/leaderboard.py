"""The leaderboard of a group (RNK-01…04, A20).

Current scores come from each active member's latest result. The change shown is the
one the latest closed period caused, measured against the score before it (A12, A13).
Highlights and place changes only compare members with a result in that period, so
someone joining or returning afterwards changes nobody's movement until the next one.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.domain import ranking, scoring
from app.domain.types import UserId
from app.extensions import db
from app.models import Membership, Period, PeriodResult, PeriodStatus
from app.services import membership, periods


@dataclass(frozen=True)
class Row:
    member: Membership
    place: int
    score: float
    delta: float | None  # None without an earlier score
    place_change: int  # positive = moved up, 0 = unchanged or new
    is_new: bool  # no result before the latest closed period (INV-06)


@dataclass(frozen=True)
class Leaderboard:
    rows: list[Row]
    highlights: ranking.Highlights
    as_of: datetime | None  # end of the latest closed period
    names: dict[int, Membership]  # user id → membership, for the highlights


def leaderboard(group_id: int, members: list[Membership] | None = None) -> Leaderboard:
    """members: the active members, if the caller has loaded them already."""
    if members is None:
        members = membership.active_members(group_id)
    by_id = {UserId(m.user_id): m for m in members}
    latest = latest_closed_period(group_id)
    results = _results(latest) if latest else {}
    curr: dict[UserId, float] = {u: r.score for u, r in results.items() if u in by_id}
    missing = [u for u in by_id if u not in curr]
    with_history = _with_earlier_results(group_id, latest, list(by_id))
    if missing:
        ratings = periods.current_ratings(group_id, missing)
        curr.update({u: scoring.score(ratings[u]) for u in missing})
    # Only the latest period's change counts; members who rejoined since have none.
    prev = {
        u: scoring.score(r.rating_before)
        for u, r in results.items()
        if u in by_id and u in with_history
    }
    in_latest = {u: score for u, score in curr.items() if u in results}
    highlights = ranking.highlights(prev, in_latest)
    changes = ranking.deltas(prev, curr)
    rows = [
        Row(
            member=by_id[entry.user_id],
            place=entry.place,
            score=entry.score,
            delta=changes[entry.user_id],
            place_change=highlights.place_changes.get(entry.user_id, 0),
            is_new=entry.user_id not in with_history,
        )
        for entry in ranking.rank(curr)
    ]
    return Leaderboard(
        rows=rows,
        highlights=highlights,
        as_of=latest.closes_at if latest else None,
        names={m.user_id: m for m in members},
    )


def latest_closed_period(group_id: int) -> Period | None:
    return db.session.scalar(
        select(Period)
        .where(Period.group_id == group_id, Period.status == PeriodStatus.CLOSED)
        .order_by(Period.seq.desc())
        .limit(1)
    )


def _results(period: Period) -> dict[UserId, PeriodResult]:
    rows = db.session.scalars(select(PeriodResult).where(PeriodResult.period_id == period.id))
    return {UserId(r.user_id): r for r in rows}


def _with_earlier_results(
    group_id: int, latest: Period | None, user_ids: list[UserId]
) -> set[UserId]:
    """Members with a result before the latest closed period (all periods if there is none)."""
    if not user_ids:
        return set()
    query = (
        select(PeriodResult.user_id)
        .distinct()
        .join(Period, Period.id == PeriodResult.period_id)
        .where(Period.group_id == group_id, PeriodResult.user_id.in_(user_ids))
    )
    if latest is not None:
        query = query.where(Period.seq < latest.seq)
    return {UserId(u) for u in db.session.scalars(query)}
