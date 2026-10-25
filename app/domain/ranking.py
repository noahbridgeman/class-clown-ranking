"""Leaderboard logic (RNK-01…03) and overtakes for notifications (M8).

Places compare scores at full precision; equal scores share a place (A7).
Changes are the difference of the displayed, rounded scores (A12, A13), so a
change always matches the two numbers people see.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations

from app.domain.formatting import round_half_up
from app.domain.types import UserId


@dataclass(frozen=True)
class RankEntry:
    user_id: UserId
    place: int
    score: float


@dataclass(frozen=True)
class Movement:
    user_ids: tuple[UserId, ...]  # several on a tie
    delta: float


@dataclass(frozen=True)
class Highlights:
    biggest_gain: Movement | None
    biggest_drop: Movement | None
    new_leaders: tuple[UserId, ...]
    place_changes: Mapping[UserId, int]  # positive = moved up; unchanged places left out


def rank(scores: Mapping[UserId, float]) -> list[RankEntry]:
    """RNK-01: highest score first, ties share a place (1, 1, 3), then by user id."""
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    entries: list[RankEntry] = []
    for position, (user_id, value) in enumerate(ordered, start=1):
        tied = entries and entries[-1].score == value
        place = entries[-1].place if tied else position
        entries.append(RankEntry(user_id=user_id, place=place, score=value))
    return entries


def deltas(
    prev: Mapping[UserId, float], curr: Mapping[UserId, float]
) -> dict[UserId, float | None]:
    """RNK-02: change of the displayed score; None for members without a previous score."""
    return {
        user_id: _displayed_change(prev[user_id], value) if user_id in prev else None
        for user_id, value in curr.items()
    }


def _displayed_change(before: float, after: float) -> float:
    return float(round_half_up(after) - round_half_up(before))


def highlights(prev: Mapping[UserId, float], curr: Mapping[UserId, float]) -> Highlights:
    """RNK-03: biggest gain, biggest drop, new leaders and place changes (A12).

    `curr` holds the active members. Members of `prev` who have left are ignored,
    so nobody "moves up" just because someone left. Newcomers have no change,
    but count as new leader if they land on place 1.
    """
    prev = {u: s for u, s in prev.items() if u in curr}
    changes = {u: d for u, d in deltas(prev, curr).items() if d is not None}
    prev_places = _places(prev)
    curr_places = _places(curr)
    leaders_before = {u for u, p in prev_places.items() if p == 1}
    return Highlights(
        biggest_gain=_extreme(changes, sign=1),
        biggest_drop=_extreme(changes, sign=-1),
        new_leaders=tuple(
            sorted(u for u, p in curr_places.items() if p == 1 and u not in leaders_before)
        )
        if prev
        else (),
        place_changes={
            u: prev_places[u] - curr_places[u]
            for u in sorted(curr_places)
            if u in prev_places and prev_places[u] != curr_places[u]
        },
    )


def overtakes(
    prev: Mapping[UserId, float], curr: Mapping[UserId, float]
) -> list[tuple[UserId, UserId]]:
    """(overtaker, overtaken) pairs: strictly behind before, strictly ahead now."""
    common = sorted(prev.keys() & curr.keys())
    pairs = []
    for a, b in combinations(common, 2):
        if prev[a] < prev[b] and curr[a] > curr[b]:
            pairs.append((a, b))
        elif prev[b] < prev[a] and curr[b] > curr[a]:
            pairs.append((b, a))
    return sorted(pairs)


def _places(scores: Mapping[UserId, float]) -> dict[UserId, int]:
    return {entry.user_id: entry.place for entry in rank(scores)}


def _extreme(changes: Mapping[UserId, float], sign: int) -> Movement | None:
    candidates = {u: d for u, d in changes.items() if d * sign > 0}
    if not candidates:
        return None
    best = max(d * sign for d in candidates.values())
    users = tuple(sorted(u for u, d in candidates.items() if d * sign == best))
    return Movement(user_ids=users, delta=best * sign)


START_SCORE = 5.0  # score of rating 0 (INV-06)
STEADY_MAX = 0.1  # "hardly changed": a displayed change of at most this


class Label(StrEnum):
    """One label per leaderboard row (docs/design.md section 6, A22), in priority order."""

    BEST = "best"
    GAIN = "gain"
    DROP = "drop"
    STEADY = "steady"
    RECOVERING = "recovering"
    BELOW_START = "below_start"
    NEW = "new"


@dataclass(frozen=True)
class LabelFacts:
    score: float
    best: float  # highest own score so far
    results: int  # number of own results
    delta: float | None  # displayed change in the latest period
    previous_delta: float | None  # displayed change in the period before
    is_gain: bool
    is_drop: bool
    is_new: bool


def label(facts: LabelFacts) -> Label | None:
    """The first label in Label's order that applies, or None."""
    shown = round_half_up(facts.score)
    checks = (
        (
            Label.BEST,
            facts.results >= 2
            and shown == round_half_up(facts.best)
            and shown > round_half_up(START_SCORE),
        ),
        (Label.GAIN, facts.is_gain),
        (Label.DROP, facts.is_drop),
        (Label.STEADY, facts.delta is not None and abs(facts.delta) <= STEADY_MAX),
        (
            Label.RECOVERING,
            facts.delta is not None
            and facts.delta > 0
            and facts.previous_delta is not None
            and facts.previous_delta < 0,
        ),
        (Label.BELOW_START, shown < round_half_up(START_SCORE)),
        (Label.NEW, facts.is_new),
    )
    return next((name for name, applies in checks if applies), None)


def sparkline(scores: Sequence[float]) -> list[float]:
    """Scores scaled to 0 (lowest) … 1 (highest) of the given ones; flat lines sit at 0.5."""
    if not scores:
        return []
    low, high = min(scores), max(scores)
    if high - low < 1e-9:
        return [0.5] * len(scores)
    return [(s - low) / (high - low) for s in scores]
