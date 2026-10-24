import itertools
import math
import random

import pytest

from app.domain import scoring
from app.domain.scoring import MemberResult, ScoreParams
from app.domain.types import Cadence, UserId

WEEKLY = ScoreParams(k=0.5, d=0.95)

A, B, C = UserId(1), UserId(2), UserId(3)


@pytest.mark.parametrize(
    ("ups", "downs", "expected"),
    [(0, 0, 0.0), (1, 0, 1.0), (0, 1, -1.0), (3, 1, 0.5), (1, 3, -0.5), (2, 2, 0.0)],
)
def test_net(ups, downs, expected):
    assert scoring.net(ups, downs) == expected


def test_net_rejects_negative_counts():
    with pytest.raises(ValueError):
        scoring.net(-1, 0)


@pytest.mark.parametrize(
    ("rating", "net", "expected"),
    [(0.0, 0.0, 0.0), (0.0, 1.0, 0.5), (1.0, 0.5, 1.2), (2.0, 0.0, 1.9), (-1.0, -1.0, -1.45)],
)
def test_next_rating(rating, net, expected):
    assert scoring.next_rating(rating, net, WEEKLY) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("rating", "expected"),
    [(0.0, 5.0), (1.0, 7.310585786300049), (-1.0, 2.689414213699951), (5.0, 9.933071490757153)],
)
def test_score_reference_values(rating, expected):
    assert scoring.score(rating) == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("rating", [-1e6, -800.0, -50.0, 50.0, 800.0, 1e6])
def test_score_stays_in_range_without_overflow(rating):
    assert 0.0 <= scoring.score(rating) <= 10.0


def test_score_is_symmetric():
    assert scoring.score(0.7) + scoring.score(-0.7) == pytest.approx(10.0)


def test_decay_pulls_score_back_to_five_without_votes():
    scores = scoring.simulate(WEEKLY, [0.0] * 200, r0=3.0)

    assert all(a > b for a, b in itertools.pairwise(scores))
    assert scores[-1] == pytest.approx(5.0, abs=1e-3)


@pytest.mark.parametrize("net", [1.0, 0.5, -0.25])
def test_constant_voting_converges_to_equilibrium(net):
    params = ScoreParams(k=0.3, d=0.8)
    rating = 0.0
    for _ in range(500):
        rating = scoring.next_rating(rating, net, params)

    assert rating == pytest.approx(net * params.k / (1 - params.d))


def test_compute_period_reference_example():
    prior = {A: 0.0, B: 0.5, C: -1.0}
    votes = [(A, C, 1), (B, C, -1), (A, B, 1)]

    results = scoring.compute_period(prior, votes, WEEKLY)

    assert results == {
        A: MemberResult(0, 0, 0.0, 0.0, 0.0, 5.0),
        B: MemberResult(1, 0, 1.0, 0.5, pytest.approx(0.975), pytest.approx(scoring.score(0.975))),
        C: MemberResult(1, 1, 0.0, -1.0, pytest.approx(-0.95), pytest.approx(scoring.score(-0.95))),
    }


def test_compute_period_decays_members_without_votes():
    results = scoring.compute_period({A: 2.0, B: -2.0}, [], WEEKLY)

    assert results[A].rating_after == pytest.approx(1.9)
    assert results[B].rating_after == pytest.approx(-1.9)
    assert results[A].ups == results[A].downs == 0


def test_compute_period_with_no_members():
    assert scoring.compute_period({}, [], WEEKLY) == {}


def test_compute_period_is_deterministic():
    prior = {UserId(i): i / 10 for i in range(10, 0, -1)}
    votes = [(v, t, 1 if (v + t) % 3 else -1) for v, t in itertools.permutations(prior, 2) if v % 2]
    first = scoring.compute_period(prior, votes, WEEKLY)
    shuffled = votes[:]
    random.Random(42).shuffle(shuffled)
    second = scoring.compute_period(dict(reversed(prior.items())), shuffled, WEEKLY)

    assert first == second
    assert list(first) == sorted(prior)
    assert list(second) == sorted(prior)


@pytest.mark.parametrize(
    "votes",
    [
        pytest.param([(A, A, 1)], id="self-vote"),
        pytest.param([(A, UserId(99), 1)], id="non-member target"),
        pytest.param([(UserId(99), A, 1)], id="non-member voter"),
        pytest.param([(A, B, 0)], id="zero value"),
        pytest.param([(A, B, 2)], id="value out of range"),
        pytest.param([(A, B, 1), (A, B, -1)], id="duplicate"),
    ],
)
def test_compute_period_rejects_invalid_votes(votes):
    with pytest.raises(ValueError):
        scoring.compute_period({A: 0.0, B: 0.0}, votes, WEEKLY)


def test_convert_weekly_to_daily_reference():
    daily = scoring.convert_params(WEEKLY, Cadence.WEEKLY, Cadence.DAILY)

    assert daily.d == pytest.approx(0.95 ** (1 / 7))
    assert daily.k == pytest.approx(0.5 * (1 - 0.95 ** (1 / 7)) / 0.05)


@pytest.mark.parametrize(
    ("k", "d"),
    [(0.5, 0.95), (0.05, 0.5), (2.0, 0.5), (1.0, 0.99), (0.2, 0.75), (0.7, 1.0)],
)
def test_convert_roundtrip_keeps_params_and_equilibrium(k, d):
    weekly = ScoreParams(k=k, d=d)
    daily = scoring.convert_params(weekly, Cadence.WEEKLY, Cadence.DAILY)
    back = scoring.convert_params(daily, Cadence.DAILY, Cadence.WEEKLY)

    assert back.k == pytest.approx(k, rel=1e-9)
    assert back.d == pytest.approx(d, rel=1e-9)
    if d < 1:
        assert daily.k / (1 - daily.d) == pytest.approx(k / (1 - d), rel=1e-9)


def test_convert_with_d_one_uses_limit():
    daily = scoring.convert_params(ScoreParams(k=0.7, d=1.0), Cadence.WEEKLY, Cadence.DAILY)

    assert daily == ScoreParams(k=pytest.approx(0.1), d=1.0)


def test_convert_with_d_close_to_one_approaches_limit():
    daily = scoring.convert_params(ScoreParams(k=0.7, d=1 - 1e-12), Cadence.WEEKLY, Cadence.DAILY)

    assert daily.k == pytest.approx(0.1, rel=1e-3)


def test_convert_same_cadence_is_identity():
    assert scoring.convert_params(WEEKLY, Cadence.WEEKLY, Cadence.WEEKLY) == WEEKLY


def test_convert_has_same_effect_over_a_week():
    """SET-04: a week of daily periods ≈ one weekly period at the equilibrium."""
    daily = scoring.convert_params(WEEKLY, Cadence.WEEKLY, Cadence.DAILY)
    eq = WEEKLY.k / (1 - WEEKLY.d)
    start = 0.3 * eq

    weekly_rating = scoring.next_rating(start, 1.0, WEEKLY)
    daily_rating = start
    for _ in range(7):
        daily_rating = scoring.next_rating(daily_rating, 1.0, daily)

    assert daily_rating == pytest.approx(weekly_rating)


def test_every_valid_weekly_setting_converts_to_a_valid_daily_one():
    b = scoring.bounds(Cadence.WEEKLY)
    for k, d in itertools.product(
        [b.k_min, 0.1, 0.5, 1.0, b.k_max], [b.d_min, 0.6, 0.9, 0.99, b.d_max]
    ):
        daily = scoring.convert_params(ScoreParams(k, d), Cadence.WEEKLY, Cadence.DAILY)
        assert scoring.validate(daily, Cadence.DAILY) == set(), (k, d)


def test_convert_clamps_daily_values_outside_weekly_range():
    b = scoring.bounds(Cadence.DAILY)
    weekly = scoring.convert_params(ScoreParams(b.k_max, 1.0), Cadence.DAILY, Cadence.WEEKLY)

    assert weekly == ScoreParams(k=scoring.WEEKLY_BOUNDS.k_max, d=1.0)


def test_daily_bounds_are_image_of_weekly_bounds():
    daily = scoring.bounds(Cadence.DAILY)

    assert daily.d_min == pytest.approx(0.5 ** (1 / 7))
    assert daily.d_max == 1.0
    assert daily.k_min == pytest.approx(0.05 / 7)
    assert daily.k_max == pytest.approx(2.0 * (1 - 0.5 ** (1 / 7)) / 0.5)


@pytest.mark.parametrize("cadence", list(Cadence))
def test_default_params_are_valid(cadence):
    assert scoring.validate(scoring.default_params(cadence), cadence) == set()


@pytest.mark.parametrize(
    ("k", "d", "invalid"),
    [
        (0.5, 0.95, set()),
        (0.05, 0.5, set()),
        (2.0, 1.0, set()),
        (0.0, 0.95, {"k"}),
        (-0.1, 0.95, {"k"}),
        (2.01, 0.95, {"k"}),
        (0.5, 0.0, {"d"}),
        (0.5, 0.49, {"d"}),
        (0.5, 1.01, {"d"}),
        (math.nan, math.inf, {"k", "d"}),
    ],
)
def test_validate_weekly(k, d, invalid):
    assert scoring.validate(ScoreParams(k, d), Cadence.WEEKLY) == invalid


def test_validate_daily_uses_daily_bounds():
    assert scoring.validate(ScoreParams(0.5, 0.95), Cadence.DAILY) == {"k"}
    assert scoring.validate(ScoreParams(0.1, 0.8), Cadence.DAILY) == {"d"}


def test_simulate_matches_step_by_step():
    nets = [1.0, 0.5, 0.0, -1.0]
    rating, expected = 0.2, []
    for n in nets:
        rating = scoring.next_rating(rating, n, WEEKLY)
        expected.append(scoring.score(rating))

    assert scoring.simulate(WEEKLY, nets, r0=0.2) == expected
    assert scoring.simulate(WEEKLY, []) == []
