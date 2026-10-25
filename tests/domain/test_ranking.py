import pytest

from app.domain.ranking import (
    LabelFacts,
    Movement,
    RankEntry,
    deltas,
    highlights,
    label,
    overtakes,
    rank,
    sparkline,
)
from app.domain.types import UserId

A, B, C, D = UserId(1), UserId(2), UserId(3), UserId(4)


def test_rank_sorts_by_score_descending():
    assert rank({A: 4.0, B: 6.5, C: 5.0}) == [
        RankEntry(B, 1, 6.5),
        RankEntry(C, 2, 5.0),
        RankEntry(A, 3, 4.0),
    ]


def test_rank_ties_share_a_place_and_skip_the_next():
    entries = rank({D: 5.0, A: 7.0, C: 5.0, B: 7.0})

    assert [(e.user_id, e.place) for e in entries] == [(A, 1), (B, 1), (C, 3), (D, 3)]


def test_rank_compares_full_precision():
    """A7: 5.04 and 5.01 both show as 5,0 but are not tied."""
    entries = rank({A: 5.01, B: 5.04})

    assert [(e.user_id, e.place) for e in entries] == [(B, 1), (A, 2)]


def test_rank_empty():
    assert rank({}) == []


def test_deltas():
    result = deltas({A: 5.0, B: 6.0, C: 4.0}, {A: 5.4, B: 5.5, D: 5.0})

    assert result == {A: 0.4, B: -0.5, D: None}


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        pytest.param(5.249, 5.251, 0.1, id="displayed 5,2 → 5,3"),
        pytest.param(5.151, 5.249, 0.0, id="displayed 5,2 → 5,2"),
        pytest.param(5.25, 5.149, -0.2, id="displayed 5,3 → 5,1"),
    ],
)
def test_deltas_match_displayed_scores(before, after, expected):
    assert deltas({A: before}, {A: after}) == {A: expected}


def test_biggest_gain_uses_displayed_change():
    """A rises 0,302 but shows 5,2 → 5,6; B rises 0,33 but shows 5,2 → 5,5."""
    result = highlights({A: 5.249, B: 5.15}, {A: 5.551, B: 5.48})

    assert result.biggest_gain == Movement((A,), pytest.approx(0.4))


def test_highlights():
    prev = {A: 6.0, B: 5.0, C: 4.0}
    curr = {A: 5.5, B: 6.2, C: 4.1, D: 5.0}

    result = highlights(prev, curr)

    assert result.biggest_gain == Movement((B,), 1.2)
    assert result.biggest_drop == Movement((A,), -0.5)
    assert result.new_leaders == (B,)
    # Places before: A 1, B 2, C 3. After: B 1, A 2, D 3, C 4.
    assert result.place_changes == {A: -1, B: 1, C: -1}


def test_highlights_ties_list_all_users():
    result = highlights({A: 5.0, B: 5.0, C: 5.0}, {A: 5.5, B: 5.5, C: 4.0})

    assert result.biggest_gain == Movement((A, B), 0.5)
    assert result.new_leaders == ()  # all three were already tied at place 1


def test_highlights_without_change():
    result = highlights({A: 5.0, B: 6.0}, {A: 5.0, B: 6.0})

    assert result.biggest_gain is None
    assert result.biggest_drop is None
    assert result.new_leaders == ()
    assert result.place_changes == {}


def test_highlights_for_first_period():
    result = highlights({}, {A: 5.5, B: 4.5})

    assert result.biggest_gain is None
    assert result.biggest_drop is None
    assert result.new_leaders == ()
    assert result.place_changes == {}


def test_overtakes():
    prev = {A: 6.0, B: 5.0, C: 4.0, D: 3.0}
    curr = {A: 5.0, B: 5.5, C: 6.0, D: 3.0}

    assert overtakes(prev, curr) == [(B, A), (C, A), (C, B)]


def test_overtakes_need_strict_order_before_and_after():
    assert overtakes({A: 5.0, B: 5.0}, {A: 6.0, B: 5.0}) == []
    assert overtakes({A: 4.0, B: 5.0}, {A: 5.0, B: 5.0}) == []


def test_overtakes_ignore_new_and_departed_members():
    assert overtakes({A: 4.0, C: 9.0}, {A: 5.0, B: 4.5}) == []


def test_highlights_ignore_departed_members():
    """The leader left: the others did not move up by themselves."""
    result = highlights({A: 9.0, B: 6.0, C: 5.0}, {B: 6.1, C: 5.0})

    assert result.place_changes == {}
    assert result.new_leaders == ()
    assert result.biggest_gain == Movement((B,), 0.1)


def test_newcomer_on_place_one_is_a_new_leader_without_change():
    result = highlights({A: 6.0, B: 5.0}, {A: 6.0, B: 5.0, D: 7.0})

    assert result.new_leaders == (D,)
    assert result.biggest_gain is None
    assert D not in result.place_changes
    assert result.place_changes == {A: -1, B: -1}


def facts(**overrides):
    values = {
        "score": 6.0,
        "best": 7.0,
        "results": 3,
        "delta": 0.5,
        "previous_delta": 0.2,
        "is_gain": False,
        "is_drop": False,
        "is_new": False,
    }
    return LabelFacts(**{**values, **overrides})


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"score": 7.0, "best": 7.04}, "best"),  # equal when displayed
        ({"score": 5.04, "best": 5.04}, None),  # shows as 5,0: not above the start
        ({"delta": -0.1}, "steady"),
        ({"delta": -0.2}, None),
        ({"score": 7.0, "best": 7.0, "results": 1}, None),  # one result is no record yet
        ({"score": 4.9, "best": 4.9, "delta": -0.5}, "below_start"),  # a record only above 5
        ({"score": 7.0, "best": 7.0, "is_gain": True}, "best"),  # best goes first
        ({"is_gain": True}, "gain"),
        ({"is_drop": True, "delta": -0.5}, "drop"),
        ({"delta": 0.1}, "steady"),
        ({"delta": 0.0}, "steady"),
        ({"delta": 0.3, "previous_delta": -0.2}, "recovering"),
        ({"score": 4.2, "delta": -0.3}, "below_start"),
        (
            {"score": 5.0, "delta": None, "previous_delta": None, "is_new": True, "results": 0},
            "new",
        ),
        ({}, None),
    ],
)
def test_label(overrides, expected):
    """A22: at most one label, in the order of docs/design.md section 6."""
    assert label(facts(**overrides)) == expected


def test_sparkline_scales_to_its_own_range():
    assert sparkline([4.0, 6.0, 5.0]) == [0.0, 1.0, 0.5]
    assert sparkline([5.0, 5.0]) == [0.5, 0.5]
    assert sparkline([]) == []
