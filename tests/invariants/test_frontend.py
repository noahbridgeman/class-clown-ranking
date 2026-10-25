"""Frontend rules from CLAUDE.md that keep a redesign cheap.

No inline styles, fixed colors, fonts and sizes only in tokens.css, recurring elements
only as macros in macros/ui.html.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
TEMPLATES = ROOT / "app" / "templates"
CSS_DIR = ROOT / "app" / "static" / "css"
TOKENS = CSS_DIR / "tokens.css"
MACROS = TEMPLATES / "macros" / "ui.html"

COMMENT = re.compile(r"/\*.*?\*/", re.S)
DECLARATION = re.compile(r"([\w-]+)\s*:\s*([^;{}]+)")
UNITS = "px|rem|em|vh|vw|vmin|vmax|svh|lvh|dvh|ch|ex|lh|rlh|pt|pc|cm|mm|in|q"
LENGTH = re.compile(rf"(?<![\w.-])(-?(?:\d+\.?\d*|\.\d+))({UNITS})\b", re.I)
HEX_COLOR = re.compile(r"#[0-9a-f]{3,8}\b", re.I)
COLOR_FUNCTION = re.compile(r"\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(", re.I)
NAMED_COLORS = {
    "aliceblue",
    "antiquewhite",
    "aqua",
    "aquamarine",
    "azure",
    "beige",
    "bisque",
    "black",
    "blanchedalmond",
    "blue",
    "blueviolet",
    "brown",
    "burlywood",
    "cadetblue",
    "chartreuse",
    "chocolate",
    "coral",
    "cornflowerblue",
    "cornsilk",
    "crimson",
    "cyan",
    "darkblue",
    "darkcyan",
    "darkgoldenrod",
    "darkgray",
    "darkgreen",
    "darkgrey",
    "darkkhaki",
    "darkmagenta",
    "darkolivegreen",
    "darkorange",
    "darkorchid",
    "darkred",
    "darksalmon",
    "darkseagreen",
    "darkslateblue",
    "darkslategray",
    "darkslategrey",
    "darkturquoise",
    "darkviolet",
    "deeppink",
    "deepskyblue",
    "dimgray",
    "dimgrey",
    "dodgerblue",
    "firebrick",
    "floralwhite",
    "forestgreen",
    "fuchsia",
    "gainsboro",
    "ghostwhite",
    "gold",
    "goldenrod",
    "gray",
    "green",
    "greenyellow",
    "grey",
    "honeydew",
    "hotpink",
    "indianred",
    "indigo",
    "ivory",
    "khaki",
    "lavender",
    "lavenderblush",
    "lawngreen",
    "lemonchiffon",
    "lightblue",
    "lightcoral",
    "lightcyan",
    "lightgoldenrodyellow",
    "lightgray",
    "lightgreen",
    "lightgrey",
    "lightpink",
    "lightsalmon",
    "lightseagreen",
    "lightskyblue",
    "lightslategray",
    "lightslategrey",
    "lightsteelblue",
    "lightyellow",
    "lime",
    "limegreen",
    "linen",
    "magenta",
    "maroon",
    "mediumaquamarine",
    "mediumblue",
    "mediumorchid",
    "mediumpurple",
    "mediumseagreen",
    "mediumslateblue",
    "mediumspringgreen",
    "mediumturquoise",
    "mediumvioletred",
    "midnightblue",
    "mintcream",
    "mistyrose",
    "moccasin",
    "navajowhite",
    "navy",
    "oldlace",
    "olive",
    "olivedrab",
    "orange",
    "orangered",
    "orchid",
    "palegoldenrod",
    "palegreen",
    "paleturquoise",
    "palevioletred",
    "papayawhip",
    "peachpuff",
    "peru",
    "pink",
    "plum",
    "powderblue",
    "purple",
    "rebeccapurple",
    "red",
    "rosybrown",
    "royalblue",
    "saddlebrown",
    "salmon",
    "sandybrown",
    "seagreen",
    "seashell",
    "sienna",
    "silver",
    "skyblue",
    "slateblue",
    "slategray",
    "slategrey",
    "snow",
    "springgreen",
    "steelblue",
    "tan",
    "teal",
    "thistle",
    "tomato",
    "turquoise",
    "violet",
    "wheat",
    "white",
    "whitesmoke",
    "yellow",
    "yellowgreen",
}
FONT_PROPERTIES = {"font-family", "font"}
INLINE_STYLE = re.compile(r"<style\b|\sstyle\s*=", re.I)
VAR_CALL = re.compile(r"var\([^)]*\)")
VAR_USE = re.compile(r"var\(\s*(--[\w-]+)")
VAR_DEFINITION = re.compile(r"(--[\w-]+)\s*:")
# Recurring elements whose markup lives only in macros/ui.html.
MACRO_CLASSES = (
    "card",
    "section",
    "page-head",
    "button",
    "link-button",
    "text-link",
    "badge",
    "profile",
    "ticker",
    "status-block",
    "cell",
    "segment",
    "vote",
    "progress",
    "sparkline",
)


def stylesheets() -> list[Path]:
    sheets = sorted(path for path in CSS_DIR.glob("*.css") if path != TOKENS)
    assert sheets, "no stylesheets found"
    return sheets


def templates() -> list[Path]:
    found = sorted(TEMPLATES.rglob("*.html"))
    assert found
    return found


def declarations(css: str) -> list[tuple[str, str]]:
    return DECLARATION.findall(COMMENT.sub("", css))


def violations(css: str) -> list[str]:
    """Fixed values in a stylesheet. Allowed: 0, percentages, unitless numbers and 1px."""
    found = []
    for prop, value in declarations(css):
        prop = prop.lower()
        if prop.startswith("--"):
            found.append(f"{prop}: custom properties belong in tokens.css")
            continue
        for number, unit in LENGTH.findall(value):
            if float(number) != 0 and f"{number}{unit.lower()}" != "1px":
                found.append(f"{prop}: {number}{unit}")
        if HEX_COLOR.search(value) or COLOR_FUNCTION.search(value):
            found.append(f"{prop}: color {value.strip()}")
        words = {word.lower() for word in re.findall(r"[a-z]+", VAR_CALL.sub("", value), re.I)}
        if words & NAMED_COLORS:
            found.append(f"{prop}: named color {value.strip()}")
        if prop in FONT_PROPERTIES and not re.fullmatch(r"\s*(var\(--[\w-]+\)|inherit)\s*", value):
            found.append(f"{prop}: font {value.strip()}")
    return found


def test_tokens_exist_and_load_first():
    base = (TEMPLATES / "base.html").read_text()
    assert TOKENS.exists()
    assert 0 <= base.index("css/tokens.css") < base.index("css/app.css")


def test_stylesheets_use_only_tokens():
    found = [f"{path.name}: {v}" for path in stylesheets() for v in violations(path.read_text())]
    assert not found


def test_every_variable_used_is_defined_in_tokens():
    defined = set(VAR_DEFINITION.findall(COMMENT.sub("", TOKENS.read_text())))
    used = {
        name
        for path in [*stylesheets(), TOKENS]
        for name in VAR_USE.findall(COMMENT.sub("", path.read_text()))
    }
    assert used <= defined, sorted(used - defined)


def test_no_inline_styles_in_templates():
    found = [
        f"{path.relative_to(TEMPLATES)}:{number}"
        for path in templates()
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if INLINE_STYLE.search(line)
    ]
    assert not found


def test_no_fixed_colors_in_templates():
    """The browser's theme color cannot read CSS variables, so it must match the token."""
    bg = re.search(r"--color-bg:\s*(#[0-9a-f]+)", TOKENS.read_text(), re.I).group(1)
    found = []
    for path in templates():
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if 'name="theme-color"' in line:
                assert f'content="{bg}"' in line, "theme-color must equal --color-bg"
            elif HEX_COLOR.search(line):
                found.append(f"{path.relative_to(TEMPLATES)}:{number}")
    assert not found


def test_manifest_theme_color_matches_the_token():
    """Like theme-color: the web app manifest cannot read CSS variables (NFA-02)."""
    from app.web.pwa import THEME_COLOR

    bg = re.search(r"--color-bg:\s*(#[0-9a-f]+)", TOKENS.read_text(), re.I).group(1)
    assert bg.lower() == THEME_COLOR


@pytest.mark.parametrize("css_class", MACRO_CLASSES)
def test_recurring_elements_come_from_macros(css_class):
    pattern = re.compile(rf'class="(?:[^"]*\s)?{re.escape(css_class)}(?:\s[^"]*)?"')
    found = [
        str(path.relative_to(TEMPLATES))
        for path in templates()
        if path != MACROS and pattern.search(path.read_text())
    ]
    assert not found


@pytest.mark.parametrize(
    "css",
    [
        "a { padding: 12px; }",
        "a { margin: 0 1.5rem; }",
        "a { width: .5em; }",
        "a { outline: 2px solid var(--x); }",
        "a { color: #fff; }",
        "a { color: rgb(0 0 0); }",
        "a { background: white; }",
        "a { font-family: system-ui, sans-serif; }",
        "a { font: 16px var(--font-sans); }",
        "a { --space: 4px; }",
        "@media (min-width: 640px) { a { color: var(--x); } }",
        "a { max-width: calc(100% - 10px); }",
        "a { border: 1px solid red; color: var(--color-red); }",
    ],
)
def test_detector_catches_fixed_values(css):
    assert violations(css)


@pytest.mark.parametrize(
    "css",
    [
        "a { padding: 0; margin: 0 auto; }",
        "a { width: 100%; line-height: 1.5; font-weight: 600; }",
        "a { border: 1px solid var(--color-border); }",
        "a { outline-offset: 1px; }",
        "a { color: var(--color-text); background: none; }",
        "a { font: inherit; font-family: var(--font-sans); }",
        "a { padding-top: max(var(--space-md), env(safe-area-inset-top)); }",
        "a { -webkit-text-size-adjust: 100%; }",
        "a { border-color: transparent; color: currentColor; }",
        "/* 12px #fff */ a { color: var(--x); }",
        ".button-red-ish { color: var(--x); }",
    ],
)
def test_detector_allows_tokens_and_neutral_values(css):
    assert not violations(css)


@pytest.mark.parametrize(
    ("line", "found"),
    [
        ('<p style="color: red">', True),
        ("<style>p { color: red }</style>", True),
        ('<p class="muted">', False),
        ('<svg viewBox="0 0 10 10">', False),
    ],
)
def test_inline_style_detector(line, found):
    assert bool(INLINE_STYLE.search(line)) is found
