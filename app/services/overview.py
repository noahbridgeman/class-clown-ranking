"""The voting overview (OVW-01…07, A23): one period per page, and each member's history.

Counts come from the stored results of closed periods. Who voted whom comes only from
vote_queries, which hands it out for closed periods that were not anonymous; the
viewer's own votes are always shown, to the viewer only (NFA-06).
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.domain import ranking, scoring
from app.domain.types import UserId
from app.extensions import db
from app.models import Group, Membership, Period, PeriodResult, PeriodStatus, User
from app.services import membership, vote_queries
from app.services.errors import NotFound
from app.services.vote_queries import OpenVote


@dataclass(frozen=True)
class Entry:
    """A member's result in one closed period."""

    user: User
    ups: int
    downs: int
    net: float
    score: float
    delta: float  # change of the displayed score, against 5.0 for the first result (A23)


@dataclass(frozen=True)
class PeriodPage:
    period: Period
    running: bool  # no results yet; only the viewer's own votes (OVW-06)
    entries: list[Entry]  # members with a result, highest score first
    # Not anonymous only: (voter id, target id) → +1/−1, and the votes with a reason.
    matrix: dict[tuple[int, int], int]
    reasons: list[OpenVote]
    others: list[User]  # whom the viewer could rate in this period
    own: dict[int, int]  # the viewer's votes, target id → +1/−1 (OVW-07)
    older: int | None  # seq of the neighbouring pages
    newer: int | None

    @property
    def shows_own_votes(self) -> bool:
        """Whether the viewer took part with someone to rate (the matrix shows it otherwise)."""
        return bool(self.others)

    @property
    def reasoned(self) -> set[tuple[int, int]]:
        """(voter id, target id) of the votes with a reason, to mark their matrix cells."""
        return {(v.voter_id, v.target_id) for v in self.reasons}

    @property
    def users(self) -> dict[int, User]:
        return {e.user.id: e.user for e in self.entries}


def period_page(group: Group, viewer: User, seq: int | None = None) -> PeriodPage | None:
    """The page of one period, the newest without seq; None while there is none.

    Raises NotFound for unknown and skipped periods.
    """
    shown = _shown_periods(group.id)
    if not shown:
        if seq is not None:
            raise NotFound()
        return None
    by_seq = {p.seq: p for p in shown}
    period = shown[-1] if seq is None else by_seq.get(seq)
    if period is None:
        raise NotFound()
    index = shown.index(period)
    older = shown[index - 1].seq if index > 0 else None
    newer = shown[index + 1].seq if index + 1 < len(shown) else None
    if period.status == PeriodStatus.OPEN:
        return _running_page(group, viewer, period, older, newer)
    entries = _entries(period, {u: m.user for u, m in _users(group.id).items()})
    votes = [] if period.is_anonymous else vote_queries.open_votes(period)
    taking_part = any(e.user.id == viewer.id for e in entries)
    return PeriodPage(
        period=period,
        running=False,
        entries=entries,
        matrix={(v.voter_id, v.target_id): v.value for v in votes},
        reasons=_in_matrix_order([v for v in votes if v.reason], entries),
        others=[e.user for e in entries if e.user.id != viewer.id] if taking_part else [],
        # Not anonymous, the matrix shows the own votes already.
        own=vote_queries.own_votes(period, viewer.id)
        if taking_part and period.is_anonymous
        else {},
        older=older,
        newer=newer,
    )


def _in_matrix_order(votes: list[OpenVote], entries: list[Entry]) -> list[OpenVote]:
    """By row (voter), then column (target), so the list reads like the matrix."""
    position = {e.user.id: i for i, e in enumerate(entries)}
    return sorted(votes, key=lambda v: (position[v.voter_id], position[v.target_id]))


def _running_page(
    group: Group, viewer: User, period: Period, older: int | None, newer: int | None
) -> PeriodPage:
    others = [m.user for m in membership.active_members(group.id) if m.user_id != viewer.id]
    return PeriodPage(
        period=period,
        running=True,
        entries=[],
        matrix={},
        reasons=[],
        others=others,
        own=vote_queries.own_votes(period, viewer.id),
        older=older,
        newer=newer,
    )


def _shown_periods(group_id: int) -> list[Period]:
    """Closed periods and the running one, oldest first; skipped ones are left out (A23)."""
    return list(
        db.session.scalars(
            select(Period)
            .where(Period.group_id == group_id, Period.status != PeriodStatus.SKIPPED)
            .order_by(Period.seq)
        )
    )


def _entries(period: Period, users: dict[int, User]) -> list[Entry]:
    results = db.session.scalars(
        select(PeriodResult).where(PeriodResult.period_id == period.id)
    ).all()
    by_user = {UserId(r.user_id): r for r in results}
    order = ranking.rank({u: r.score for u, r in by_user.items()})
    return [_entry(by_user[e.user_id], users[e.user_id]) for e in order]


def _entry(result: PeriodResult, user: User) -> Entry:
    before = scoring.score(result.rating_before)
    return Entry(
        user=user,
        ups=result.ups,
        downs=result.downs,
        net=result.net,
        score=result.score,
        delta=ranking.displayed_change(before, result.score),
    )


def _users(group_id: int) -> dict[int, Membership]:
    """Everyone who has ever been a member, by user id; results only exist for them."""
    members = db.session.scalars(
        select(Membership)
        .options(joinedload(Membership.user))
        .where(Membership.group_id == group_id)
    )
    return {m.user_id: m for m in members}


@dataclass(frozen=True)
class HistoryItem:
    """One closed period in a member's detail view."""

    period: Period
    entry: Entry
    received: list[OpenVote]  # with a reason, not anonymous only
    cast: dict[int, int]  # target id → +1/−1: not anonymous, or the viewer's own (OVW-07)


@dataclass(frozen=True)
class MemberHistory:
    member: Membership
    items: list[HistoryItem]  # newest first
    names: dict[int, User] = field(default_factory=dict)  # user id → user, for the votes

    @property
    def scores(self) -> list[float]:
        """Oldest first, for the chart."""
        return [item.entry.score for item in reversed(self.items)]


def member_history(group: Group, viewer: User, user_id: int) -> MemberHistory:
    """OVW-05 for a current or former member; NotFound for anyone else."""
    members = _users(group.id)
    member = members.get(user_id)
    if member is None:
        raise NotFound()
    rows = db.session.execute(
        select(Period, PeriodResult)
        .join(PeriodResult, PeriodResult.period_id == Period.id)
        .where(Period.group_id == group.id, PeriodResult.user_id == user_id)
        .order_by(Period.seq.desc())
    ).all()
    votes: dict[int, list[OpenVote]] = {}
    for v in vote_queries.open_votes_of(group.id, user_id):
        votes.setdefault(v.period_id, []).append(v)
    own = vote_queries.own_votes_by_period(group.id, viewer.id) if viewer.id == user_id else {}
    items = []
    for period, result in rows:
        in_period = votes.get(period.id, [])
        cast = {v.target_id: v.value for v in in_period if v.voter_id == user_id}
        items.append(
            HistoryItem(
                period=period,
                entry=_entry(result, member.user),
                received=[v for v in in_period if v.target_id == user_id and v.reason],
                cast=own.get(period.id, {}) if period.is_anonymous else cast,
            )
        )
    return MemberHistory(member=member, items=items, names={u: m.user for u, m in members.items()})
