"""Score history for the graph (GRA-01…07, MEM-03).

One point per closed period and member. A member without a result in a period (not yet
joined, or left) gets None there, so the line breaks instead of bridging the gap.
Only results of closed periods appear, never anything about who voted (NFA-06).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.domain.formatting import round_half_up
from app.extensions import db
from app.i18n import local_date, t
from app.models import (
    Group,
    Membership,
    MembershipEvent,
    MembershipEventKind,
    Period,
    PeriodResult,
    PeriodStatus,
    SettingField,
)
from app.services import settings
from app.services.leaderboard import Leaderboard
from app.services.text import member_name


class Range(StrEnum):
    """GRA-03"""

    WEEK = "1w"
    FOUR_WEEKS = "4w"
    QUARTER = "3m"
    YEAR = "1y"
    ALL = "all"


DEFAULT_RANGE = Range.FOUR_WEEKS
RANGE_DAYS: dict[Range, int | None] = {
    Range.WEEK: 7,
    Range.FOUR_WEEKS: 28,
    Range.QUARTER: 91,
    Range.YEAR: 365,
    Range.ALL: None,
}
RANGE_LABELS = {
    Range.WEEK: "graph.range_1w",
    Range.FOUR_WEEKS: "graph.range_4w",
    Range.QUARTER: "graph.range_3m",
    Range.YEAR: "graph.range_1y",
    Range.ALL: "graph.range_all",
}

MEMBER_MARKERS = {
    MembershipEventKind.JOINED: "graph.marker_joined",
    MembershipEventKind.REJOINED: "graph.marker_rejoined",
    MembershipEventKind.LEFT: "graph.marker_left",
    MembershipEventKind.REMOVED: "graph.marker_removed",
}


def parse_range(value: str | None) -> Range | None:
    """None for unknown values; a missing value means the default."""
    if value is None:
        return DEFAULT_RANGE
    try:
        return Range(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class _Point:
    period_id: int
    closes_at: datetime
    user_id: int
    score: float
    ups: int
    downs: int


class Role(StrEnum):
    """GRA-02: lines are colored by role, not per person (docs/design.md, section 4)."""

    LEADER = "leader"
    GAIN = "gain"
    DROP = "drop"


def graph_data(
    group: Group,
    viewer_id: int,
    range_: Range,
    now: datetime,
    roles: dict[int, Role] | None = None,
) -> dict[str, Any]:
    """The JSON for graph.js. Timestamps are milliseconds since the epoch.

    A point is [score, ups, downs] with the score already rounded for display (A13),
    so the client only swaps the decimal point. `roles` come from the current leaderboard.
    """
    roles = roles or {}
    since = range_start(range_, now, group.timezone)
    points = _points(group.id, since)
    period_ids = list(dict.fromkeys(p.period_id for p in points))
    column = {period_id: i for i, period_id in enumerate(period_ids)}
    closes = {p.period_id: p.closes_at for p in points}
    members = _memberships(group.id)
    values: dict[int, list[list[Any] | None]] = {}
    for p in points:
        row = values.setdefault(p.user_id, [None] * len(period_ids))
        row[column[p.period_id]] = [float(round_half_up(p.score)), p.ups, p.downs]
    return {
        "range": range_.value,
        "cadence": group.cadence.value,
        "periods": [
            {"t": _ms(closes[i]), "date": local_date(closes[i], group.timezone)} for i in period_ids
        ],
        "series": [
            {
                "id": m.user_id,
                "name": member_name(m.user),
                "role": roles.get(m.user_id),
                "me": m.user_id == viewer_id,
                "former": not m.is_active,
                "points": values[m.user_id],
            }
            for m in members
            if m.user_id in values
        ],
        "markers": sorted(
            _member_markers(group, members, since)
            + _mode_markers(group, since)
            + _settings_markers(group, since),
            key=lambda marker: marker["t"],
        ),
    }


def range_start(range_: Range, now: datetime, timezone: str) -> datetime | None:
    """Counts the days back in the group's local time, so a week has 7 daily windows
    even across a daylight saving switch."""
    days = RANGE_DAYS[range_]
    if days is None:
        return None
    local = now.astimezone(ZoneInfo(timezone)).replace(tzinfo=None) - timedelta(days=days)
    return local.replace(tzinfo=ZoneInfo(timezone)).astimezone(UTC)


def _points(group_id: int, since: datetime | None) -> list[_Point]:
    query = (
        select(
            Period.id,
            Period.closes_at,
            PeriodResult.user_id,
            PeriodResult.score,
            PeriodResult.ups,
            PeriodResult.downs,
        )
        .join(Period, Period.id == PeriodResult.period_id)
        .where(Period.group_id == group_id, Period.status == PeriodStatus.CLOSED)
        .order_by(Period.closes_at, PeriodResult.user_id)
    )
    if since is not None:
        query = query.where(Period.closes_at > since)
    return [_Point(*row) for row in db.session.execute(query)]


def _memberships(group_id: int) -> list[Membership]:
    """Current and former members, longest-standing first (MEM-03)."""
    return list(
        db.session.scalars(
            select(Membership)
            .options(joinedload(Membership.user))
            .where(Membership.group_id == group_id)
            .order_by(Membership.first_joined_at, Membership.id)
        )
    )


def _member_markers(
    group: Group, members: list[Membership], since: datetime | None
) -> list[dict[str, Any]]:
    """GRA-07: joins and departures."""
    names = {m.user_id: m for m in members}
    query = (
        select(MembershipEvent)
        .where(
            MembershipEvent.group_id == group.id,
            MembershipEvent.kind.in_(list(MEMBER_MARKERS)),
        )
        .order_by(MembershipEvent.occurred_at, MembershipEvent.id)
    )
    if since is not None:
        query = query.where(MembershipEvent.occurred_at > since)
    markers = []
    for event in db.session.scalars(query):
        member = names[event.user_id]
        markers.append(
            _marker(
                event.occurred_at,
                group,
                "member",
                t(MEMBER_MARKERS[event.kind], name=member_name(member.user)),
            )
        )
    return markers


def _mode_markers(group: Group, since: datetime | None) -> list[dict[str, Any]]:
    """GRA-07: where a period is anonymous and the one before was open, or the other way."""
    previous = func.lag(Period.is_anonymous).over(order_by=Period.seq).label("previous")
    periods = (
        select(Period.opens_at, Period.is_anonymous, previous)
        .where(Period.group_id == group.id)
        .subquery()
    )
    query = select(periods.c.opens_at, periods.c.is_anonymous).where(
        periods.c.previous.is_not(None), periods.c.previous != periods.c.is_anonymous
    )
    if since is not None:
        query = query.where(periods.c.opens_at > since)
    return [
        _marker(
            opens_at,
            group,
            "mode",
            t("graph.marker_anonymous" if anonymous else "graph.marker_open"),
        )
        for opens_at, anonymous in db.session.execute(query.order_by(periods.c.opens_at))
    ]


# The switch between anonymous and not anonymous has its own marker (_mode_markers).
SETTINGS_IN_MARKERS = {
    SettingField.NAME: "settings.field_name",
    SettingField.CADENCE: "settings.field_cadence",
    SettingField.TIMEZONE: "settings.field_timezone",
    SettingField.K: "settings.field_k",
    SettingField.D: "settings.field_d",
}


def _settings_markers(group: Group, since: datetime | None) -> list[dict[str, Any]]:
    """GRA-07, SET-03: where a window took over changed settings."""
    markers = []
    for at, changed in settings.applied_changes(group.id, since):
        names = [t(key) for field, key in SETTINGS_IN_MARKERS.items() if field in changed]
        if names:
            text = t("graph.marker_settings", fields=", ".join(names))
            markers.append(_marker(at, group, "settings", text))
    return markers


def _marker(at: datetime, group: Group, kind: str, text: str) -> dict[str, Any]:
    return {"t": _ms(at), "date": local_date(at, group.timezone), "kind": kind, "text": text}


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def roles(board: Leaderboard) -> dict[int, Role]:
    """Biggest gain and drop of the latest period win over place 1 (GRA-02)."""
    found: dict[int, Role] = {
        row.member.user_id: Role.LEADER for row in board.rows if row.place == 1
    }
    h = board.highlights
    for movement, role in ((h.biggest_gain, Role.GAIN), (h.biggest_drop, Role.DROP)):
        if movement is not None:
            found.update(dict.fromkeys(movement.user_ids, role))
    return found
