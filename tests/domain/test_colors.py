import itertools
import math
import re

import pytest

from app.domain import colors as colors_module
from app.domain.colors import MIN_LIGHTNESS, PALETTE, color_for, lab

HEX = re.compile(r"^#[0-9A-F]{6}$")
MAX_GROUP_SIZE = 30  # A8
# CIE76 ΔE above ~20 reads as clearly different colours.
MIN_DELTA_E = 20
# ΔE between colour indexes beyond the palette and every earlier one.
MIN_EXTRA_DELTA_E = 10


def _closest(colors: list[str]) -> float:
    return min(math.dist(lab(a), lab(b)) for a, b in itertools.combinations(colors, 2))


def test_lab_reference_values():
    assert lab("#FFFFFF") == pytest.approx((100.0, 0.0, 0.0), abs=0.05)
    assert lab("#000000") == pytest.approx((0.0, 0.0, 0.0), abs=0.05)
    assert lab("#FF0000") == pytest.approx((53.24, 80.09, 67.20), abs=0.05)


def test_palette_covers_a_full_group():
    assert len(PALETTE) == MAX_GROUP_SIZE
    assert len(set(PALETTE)) == MAX_GROUP_SIZE


def test_full_group_colours_are_clearly_distinguishable():
    assert _closest([color_for(i) for i in range(MAX_GROUP_SIZE)]) > MIN_DELTA_E


def test_first_fifteen_colours_are_clearly_distinguishable():
    """GRA-02 names 15 people explicitly."""
    assert _closest([color_for(i) for i in range(15)]) > MIN_DELTA_E


def test_palette_colours_are_bright():
    assert all(lab(c)[0] > MIN_LIGHTNESS for c in PALETTE)


@pytest.mark.parametrize("index", [0, 5, 29, 30, 31, 60])
def test_color_for_returns_hex(index):
    assert HEX.match(color_for(index))


def test_color_for_uses_palette_first():
    assert [color_for(i) for i in range(MAX_GROUP_SIZE)] == list(PALETTE)


def test_extra_colours_stay_distinguishable_from_all_earlier_ones():
    colors = [color_for(i) for i in range(60)]

    for index in range(MAX_GROUP_SIZE, len(colors)):
        nearest = min(math.dist(lab(colors[index]), lab(c)) for c in colors[:index])
        assert nearest > MIN_EXTRA_DELTA_E, index
        assert lab(colors[index])[0] > MIN_LIGHTNESS


def test_extra_colours_are_stable():
    assert color_for(45) == color_for(45)
    assert [color_for(i) for i in range(30, 40)] == [color_for(i) for i in range(30, 40)]


def test_negative_index_is_rejected():
    with pytest.raises(ValueError):
        color_for(-1)


def test_large_indexes_work_without_warm_cache():
    colors_module._extras.cache_clear()
    assert HEX.match(color_for(1100))


def test_extra_colours_repeat_once_all_candidates_are_used():
    pool = len(colors_module._candidates())

    assert color_for(len(PALETTE) + pool) == color_for(len(PALETTE))
    assert color_for(len(PALETTE) + pool + 5) == color_for(len(PALETTE) + 5)
