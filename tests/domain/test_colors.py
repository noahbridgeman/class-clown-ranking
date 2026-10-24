import itertools
import math
import re

import pytest

from app.domain.colors import PALETTE, color_for

HEX = re.compile(r"^#[0-9A-F]{6}$")
# CIE76 ΔE above ~20 reads as clearly different colours.
MIN_DELTA_E = 20
# Lightness L* above this keeps lines bright on the dark theme.
MIN_LIGHTNESS = 45


def _lab(color: str) -> tuple[float, float, float]:
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))

    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = linear(r), linear(g), linear(b)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def test_palette_has_twenty_distinct_colours():
    assert len(PALETTE) == 20
    assert len(set(PALETTE)) == 20


def test_palette_colours_are_clearly_distinguishable():
    labs = [_lab(c) for c in PALETTE]
    closest = min(math.dist(a, b) for a, b in itertools.combinations(labs, 2))

    assert closest > MIN_DELTA_E


def test_palette_colours_are_bright():
    assert all(_lab(c)[0] > MIN_LIGHTNESS for c in PALETTE)


@pytest.mark.parametrize("index", [0, 5, 19, 20, 21, 29, 100])
def test_color_for_returns_hex(index):
    assert HEX.match(color_for(index))


def test_color_for_uses_palette_first():
    assert [color_for(i) for i in range(20)] == list(PALETTE)


def test_extra_colours_are_stable_and_distinct():
    extra = [color_for(i) for i in range(20, 50)]

    assert extra == [color_for(i) for i in range(20, 50)]
    assert len(set(extra)) == len(extra)
    assert not set(extra) & set(PALETTE)


def test_negative_index_is_rejected():
    with pytest.raises(ValueError):
        color_for(-1)
