"""Member colours (GRA-02): bright on a dark background, stable per colour index."""

import colorsys
import math
from functools import cache

# One colour per possible member of a full group (A8). Ordered so that the first
# members get the most distinct colours.
PALETTE = (
    "#FF5C5C",
    "#4DABF7",
    "#FFD43B",
    "#51CF66",
    "#CC5DE8",
    "#FF922B",
    "#22D3EE",
    "#F06595",
    "#A9E34B",
    "#845EF7",
    "#12B886",
    "#FFA8A8",
    "#F1F3F5",
    "#E599F7",
    "#96F2D7",
    "#FFEC99",
    "#C2410C",
    "#3B82F6",
    "#D9A066",
    "#D0BFFF",
    "#06F906",
    "#B806F9",
    "#F906A8",
    "#F90606",
    "#E8F906",
    "#F906E8",
    "#C9FC9C",
    "#F90667",
    "#98F906",
    "#06F967",
)

# Colour indexes are never reused (MEM-04), so indexes beyond the palette can occur.
# Those pick the candidate farthest (CIE76 ΔE) from every colour handed out before.
EXTRA_HUE_STEP = 4  # degrees
EXTRA_LIGHTNESS = (0.5, 0.6, 0.7, 0.8, 0.88)
EXTRA_SATURATION = (0.55, 0.75, 0.95)
MIN_LIGHTNESS = 48  # L*, keeps lines bright on the dark theme


def color_for(index: int) -> str:
    """Hex colour for a membership's colour index."""
    if index < 0:
        raise ValueError("colour index must not be negative")
    return _colors(index + 1)[index]


@cache
def _colors(count: int) -> tuple[str, ...]:
    if count <= len(PALETTE):
        return PALETTE[:count]
    previous = _colors(count - 1)
    used = [lab(c) for c in previous]
    remaining = [c for c in _candidates() if c not in previous]
    best = max(remaining, key=lambda c: min(math.dist(lab(c), u) for u in used))
    return (*previous, best)


@cache
def _candidates() -> tuple[str, ...]:
    colors = []
    for hue in range(0, 360, EXTRA_HUE_STEP):
        for lightness in EXTRA_LIGHTNESS:
            for saturation in EXTRA_SATURATION:
                r, g, b = colorsys.hls_to_rgb(hue / 360, lightness, saturation)
                color = f"#{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}"
                if lab(color)[0] > MIN_LIGHTNESS:
                    colors.append(color)
    return tuple(colors)


@cache
def lab(color: str) -> tuple[float, float, float]:
    """CIE L*a*b* (D65) of a "#RRGGBB" colour."""
    r, g, b = (_linear(int(color[i : i + 2], 16) / 255) for i in (1, 3, 5))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    fx, fy, fz = _f(x), _f(y), _f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _f(t: float) -> float:
    return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
