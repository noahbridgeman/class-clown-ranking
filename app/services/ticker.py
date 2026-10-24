"""The running ticker on every group page (docs/design.md, section 3).

The group average and every active member's score with its change. Before the first
result everyone stands at 5,0 and is marked new.
"""

from dataclasses import dataclass
from enum import StrEnum
from statistics import fmean

from app.domain.formatting import format_delta, format_score
from app.services.leaderboard import Leaderboard
from app.services.text import member_name


class Trend(StrEnum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"
    NEW = "new"


@dataclass(frozen=True)
class Item:
    label: str  # a name; empty for the group average, whose label the template adds
    score: str
    change: str  # "▲ +0,4"-style text without the sign, or "" for new members
    trend: Trend


@dataclass(frozen=True)
class Ticker:
    average: Item | None  # None before the first result
    members: list[Item]


def ticker(board: Leaderboard) -> Ticker:
    members = [
        _item(member_name(row.member.user), row.score, row.delta, row.is_new) for row in board.rows
    ]
    if board.as_of is None or not board.rows:
        return Ticker(average=None, members=members)
    deltas = [row.delta for row in board.rows if row.delta is not None]
    mean_delta = fmean(deltas) if deltas else None
    average = _item("", fmean(row.score for row in board.rows), mean_delta, is_new=False)
    return Ticker(average=average, members=members)


def _item(label: str, score: float, delta: float | None, is_new: bool) -> Item:
    if is_new:
        return Item(label, format_score(score), "", Trend.NEW)
    if delta is None:
        return Item(label, format_score(score), "", Trend.FLAT)
    text = format_delta(delta)  # "▲ +0,4", "▼ −0,4" or "–"
    trend = Trend.UP if text.startswith("▲") else Trend.DOWN if text.startswith("▼") else Trend.FLAT
    return Item(label, format_score(score), _compact(text), trend)


def _compact(text: str) -> str:
    """The ticker shows "▲0,4" (docs/design.md): arrow and number without sign or space."""
    return text.replace(" +", "").replace(" −", "")
