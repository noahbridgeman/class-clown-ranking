"""Score calculation (SCO-01…05, SCO-07, SCO-09, SET-05). Pure functions, no I/O."""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.domain.types import Cadence, UserId

SCORE_MAX = 10.0
DAYS_PER_WEEK = 7
VOTE_VALUES = (-1, 1)


@dataclass(frozen=True)
class ScoreParams:
    k: float
    d: float


@dataclass(frozen=True)
class ParamBounds:
    k_min: float
    k_max: float
    d_min: float
    d_max: float


@dataclass(frozen=True)
class MemberResult:
    ups: int
    downs: int
    net: float
    rating_before: float
    rating_after: float
    score: float


# Starting values from the requirements; calibrated in M9.
DEFAULT_WEEKLY_PARAMS = ScoreParams(k=0.5, d=0.95)

# SET-05 (assumption A11). Daily bounds are the image of the weekly bounds under
# convert_params, so every valid weekly setting converts to a valid daily one.
WEEKLY_BOUNDS = ParamBounds(k_min=0.05, k_max=2.0, d_min=0.5, d_max=1.0)


def net(ups: int, downs: int) -> float:
    """SCO-01: (U − D) / (U + D), 0 without votes."""
    if ups < 0 or downs < 0:
        raise ValueError("vote counts must not be negative")
    total = ups + downs
    return (ups - downs) / total if total else 0.0


def next_rating(rating: float, net_value: float, params: ScoreParams) -> float:
    """SCO-02: r ← d · r + K · net."""
    return params.d * rating + params.k * net_value


def score(rating: float) -> float:
    """SCO-03: 10 / (1 + e^(−r)), written so that large |r| cannot overflow."""
    if rating >= 0:
        return SCORE_MAX / (1.0 + math.exp(-rating))
    e = math.exp(rating)
    return SCORE_MAX * e / (1.0 + e)


def compute_period(
    prior: Mapping[UserId, float],
    votes: Iterable[tuple[UserId, UserId, int]],
    params: ScoreParams,
) -> dict[UserId, MemberResult]:
    """Results for every member in `prior` (SCO-05), sorted by user id (SCO-09).

    `prior` maps each active member to their rating before the period, `votes`
    are (voter, target, value) triples.
    """
    ups = dict.fromkeys(prior, 0)
    downs = dict.fromkeys(prior, 0)
    seen: set[tuple[UserId, UserId]] = set()
    for voter, target, value in votes:
        _check_vote(voter, target, value, prior, seen)
        if value > 0:
            ups[target] += 1
        else:
            downs[target] += 1

    results: dict[UserId, MemberResult] = {}
    for user_id in sorted(prior):
        before = prior[user_id]
        n = net(ups[user_id], downs[user_id])
        after = next_rating(before, n, params)
        results[user_id] = MemberResult(
            ups=ups[user_id],
            downs=downs[user_id],
            net=n,
            rating_before=before,
            rating_after=after,
            score=score(after),
        )
    return results


def _check_vote(
    voter: UserId,
    target: UserId,
    value: int,
    members: Mapping[UserId, float],
    seen: set[tuple[UserId, UserId]],
) -> None:
    if value not in VOTE_VALUES:
        raise ValueError(f"vote value must be -1 or 1, got {value!r}")
    if voter == target:
        raise ValueError(f"user {voter} voted for themselves")  # VOT-03
    if voter not in members or target not in members:
        raise ValueError(f"vote {voter} → {target} involves a non-member")
    if (voter, target) in seen:
        raise ValueError(f"duplicate vote {voter} → {target}")  # VOT-02
    seen.add((voter, target))


def convert_params(params: ScoreParams, src: Cadence, dst: Cadence) -> ScoreParams:
    """SCO-07: keeps the equilibrium K / (1 − d) when the cadence changes.

    The result is clamped to the bounds of `dst`; that only changes values that
    sit at the edge of the daily range (SET-04 lets the admin adjust afterwards).
    """
    if src == dst:
        return params
    exponent = 1 / DAYS_PER_WEEK if src == Cadence.WEEKLY else DAYS_PER_WEEK
    d_new = params.d**exponent
    k_new = params.k * _equilibrium_ratio(d_new, params.d, src)
    return _clamp(ScoreParams(k=k_new, d=d_new), bounds(dst))


def _equilibrium_ratio(d_new: float, d_old: float, src: Cadence) -> float:
    """(1 − d_new) / (1 − d_old), with the limit for d = 1."""
    if d_old == 1.0 or d_new == 1.0:
        return 1 / DAYS_PER_WEEK if src == Cadence.WEEKLY else DAYS_PER_WEEK
    return (1 - d_new) / (1 - d_old)


def bounds(cadence: Cadence) -> ParamBounds:
    """SET-05: allowed range for K and d."""
    if cadence == Cadence.WEEKLY:
        return WEEKLY_BOUNDS
    w = WEEKLY_BOUNDS
    d_min = w.d_min ** (1 / DAYS_PER_WEEK)
    return ParamBounds(
        k_min=w.k_min / DAYS_PER_WEEK,
        k_max=w.k_max * (1 - d_min) / (1 - w.d_min),
        d_min=d_min,
        d_max=w.d_max,
    )


def validate(params: ScoreParams, cadence: Cadence) -> set[str]:
    """Names of the fields ("k", "d") outside the bounds; empty if valid."""
    b = bounds(cadence)
    invalid = set()
    if not (math.isfinite(params.k) and b.k_min <= params.k <= b.k_max):
        invalid.add("k")
    if not (math.isfinite(params.d) and b.d_min <= params.d <= b.d_max):
        invalid.add("d")
    return invalid


def _clamp(params: ScoreParams, b: ParamBounds) -> ScoreParams:
    return ScoreParams(
        k=min(max(params.k, b.k_min), b.k_max),
        d=min(max(params.d, b.d_min), b.d_max),
    )


def default_params(cadence: Cadence) -> ScoreParams:
    return convert_params(DEFAULT_WEEKLY_PARAMS, Cadence.WEEKLY, cadence)


def simulate(params: ScoreParams, nets: Sequence[float], r0: float = 0.0) -> list[float]:
    """Scores after each period for a sequence of net values (SET-05 preview, calibration)."""
    rating = r0
    scores = []
    for n in nets:
        rating = next_rating(rating, n, params)
        scores.append(score(rating))
    return scores
