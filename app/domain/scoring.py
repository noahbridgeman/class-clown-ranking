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

# SET-05 (assumption A11). d stays below 1 so that the decay always applies (SCO-05)
# and the equilibrium K / (1 − d) stays finite. Daily bounds follow from these.
WEEKLY_BOUNDS = ParamBounds(k_min=0.05, k_max=2.0, d_min=0.5, d_max=0.99)
# A value converted to the other cadence may miss a bound by a rounding error.
BOUNDS_REL_TOL = 1e-9


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
    if type(value) is not int or value not in VOTE_VALUES:
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

    d_day = d_week^(1/7) and K_day = K_week · (1 − d_day) / (1 − d_week), written as
    K_week / (1 + d_day + … + d_day⁶) so that it stays exact near and at d = 1.
    """
    if not (_is_number(params.k) and _is_number(params.d) and 0 < params.d <= 1):
        raise ValueError(f"cannot convert {params!r}")
    if src == dst:
        return params
    if src == Cadence.WEEKLY:
        d_day = params.d ** (1 / DAYS_PER_WEEK)
        return ScoreParams(k=params.k / _week_sum(d_day), d=d_day)
    return ScoreParams(k=params.k * _week_sum(params.d), d=params.d**DAYS_PER_WEEK)


def _week_sum(d_day: float) -> float:
    """1 + x + … + x⁶ = (1 − x⁷) / (1 − x) for x = d_day."""
    return math.fsum(d_day**i for i in range(DAYS_PER_WEEK))


def bounds(cadence: Cadence, d: float) -> ParamBounds:
    """SET-05: allowed range for d, and for K given d.

    Daily K and d are each valid exactly when their weekly equivalent is, so
    converting a valid setting in either direction always gives a valid one (A11).
    The daily K range therefore depends on d.
    """
    w = WEEKLY_BOUNDS
    if cadence == Cadence.WEEKLY:
        return w
    d_min, d_max = w.d_min ** (1 / DAYS_PER_WEEK), w.d_max ** (1 / DAYS_PER_WEEK)
    # The weekly equivalent of K uses d as given, even when d itself is out of range.
    d_for_k = d if _is_number(d) and d > 0 else d_max
    week_sum = _week_sum(d_for_k)
    return ParamBounds(k_min=w.k_min / week_sum, k_max=w.k_max / week_sum, d_min=d_min, d_max=d_max)


def validate(params: ScoreParams, cadence: Cadence) -> set[str]:
    """Names of the fields ("k", "d") outside the bounds; empty if valid."""
    b = bounds(cadence, params.d)
    invalid = set()
    if not _within(params.d, b.d_min, b.d_max):
        invalid.add("d")
    if not _within(params.k, b.k_min, b.k_max):
        invalid.add("k")
    return invalid


def _within(value: float, low: float, high: float) -> bool:
    """low ≤ value ≤ high, tolerating rounding from a conversion."""
    tol = BOUNDS_REL_TOL * max(abs(low), abs(high))
    return _is_number(value) and low - tol <= value <= high + tol


def _is_number(value: float) -> bool:
    """A finite int or float; bool is rejected although it is an int."""
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


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
