"""Member colours (GRA-02): bright on a dark background, stable per colour index."""

import colorsys

# Ordered so that the first members get the most distinct colours.
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
)

GOLDEN_ANGLE = 137.508  # degrees
EXTRA_HUE_START = 15.0
EXTRA_LIGHTNESS = 0.65
EXTRA_SATURATION = 0.8


def color_for(index: int) -> str:
    """Hex colour for a membership's colour index; golden-angle hues beyond the palette."""
    if index < 0:
        raise ValueError("colour index must not be negative")
    if index < len(PALETTE):
        return PALETTE[index]
    hue = (EXTRA_HUE_START + (index - len(PALETTE)) * GOLDEN_ANGLE) % 360
    r, g, b = colorsys.hls_to_rgb(hue / 360, EXTRA_LIGHTNESS, EXTRA_SATURATION)
    return f"#{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}"
