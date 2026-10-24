"""Leaderboard logic (RNK-01…03) and overtakes for notifications (M8).

Scores are compared at full precision; equal scores share a place (A7).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations

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
    """RNK-02: score change per member; None for members without a previous score."""
    return {
        user_id: (value - prev[user_id]) if user_id in prev else None
        for user_id, value in curr.items()
    }


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
