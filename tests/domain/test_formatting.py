import math

import pytest

from app.domain.formatting import format_change, format_delta, format_net, format_score


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5.0, "5,0"),
        (5.04, "5,0"),
        (5.05, "5,1"),
        (5.15, "5,2"),
        (5.25, "5,3"),
        (9.96, "10,0"),
        (10.0, "10,0"),
        (0.0, "0,0"),
        (-0.0, "0,0"),
        (0.04, "0,0"),
        (7.310585786300049, "7,3"),
    ],
)
def test_format_score(value, expected):
    assert format_score(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.4, "▲ +0,4"),
        (0.05, "▲ +0,1"),
        (1.25, "▲ +1,3"),
        (-0.4, "▼ −0,4"),
        (-0.35, "▼ −0,4"),
        (-0.05, "▼ −0,1"),
        (0.0, "–"),
        (-0.0, "–"),
        (0.049, "–"),
        (-0.049, "–"),
    ],
)
def test_format_delta(value, expected):
    assert format_delta(value) == expected


def test_decimal_separator_can_be_changed():
    assert format_score(5.25, decimal_separator=".") == "5.3"
    assert format_delta(-0.4, decimal_separator=".") == "▼ −0.4"


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_values_are_rejected(value):
    with pytest.raises(ValueError):
        format_score(value)
    with pytest.raises(ValueError):
        format_delta(value)


@pytest.mark.parametrize(
    ("value", "compact", "text"),
    [
        (0.44, False, "▲ 0,4"),
        (-0.25, False, "▼ 0,3"),
        (0.6, True, "▲0,6"),
        (0.04, False, "–"),
        (None, False, "–"),
    ],
)
def test_format_change(value, compact, text):
    """Kursblatt style (docs/design.md): arrow and amount, no sign."""
    assert format_change(value, compact) == text


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (0.6, "+0,60"),
        (-1.0, "−1,00"),
        (1 / 3, "+0,33"),
        (-1 / 3, "−0,33"),
        (0.0, "0,00"),
        (-0.001, "0,00"),
        (0.125, "+0,13"),
    ],
)
def test_format_net(value, text):
    """A23: the net of a period with sign and two decimals."""
    assert format_net(value) == text
