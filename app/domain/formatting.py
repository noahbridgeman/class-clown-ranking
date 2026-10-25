"""Display of scores and score changes (SCO-04, RNK-02).

One decimal, rounded half up. Calculations always keep full precision; only the
text shown to people is rounded.
"""

import math
from decimal import ROUND_HALF_UP, Decimal

ONE_DECIMAL = Decimal("0.1")
DECIMAL_SEPARATOR = ","
MINUS = "−"
UP, DOWN, NO_CHANGE = "▲", "▼", "–"


def round_half_up(value: float) -> Decimal:
    """Rounds to one decimal; 5.25 → 5.3, −0.35 → −0.4 (half away from zero)."""
    if not math.isfinite(value):
        raise ValueError(f"cannot display {value!r}")
    # str() gives the shortest representation, so 5.15 rounds the way it reads.
    return Decimal(str(value)).quantize(ONE_DECIMAL, rounding=ROUND_HALF_UP)


def format_score(value: float, decimal_separator: str = DECIMAL_SEPARATOR) -> str:
    """SCO-04: "5,3". Scores are never negative, so −0.0 shows as "0,0"."""
    return _digits(abs(round_half_up(value)), decimal_separator)


def format_delta(value: float, decimal_separator: str = DECIMAL_SEPARATOR) -> str:
    """RNK-02: "▲ +0,4", "▼ −0,4", or "–" when the change rounds to zero."""
    rounded = round_half_up(value)
    if rounded == 0:
        return NO_CHANGE
    digits = _digits(abs(rounded), decimal_separator)
    return f"{UP} +{digits}" if rounded > 0 else f"{DOWN} {MINUS}{digits}"


def _digits(value: Decimal, decimal_separator: str) -> str:
    return f"{value:f}".replace(".", decimal_separator)


def format_change(
    value: float | None, compact: bool = False, decimal_separator: str = DECIMAL_SEPARATOR
) -> str:
    """Kursblatt style (docs/design.md): "▲ 0,4" in lists, "▲0,4" compact; "–" for no change."""
    if value is None:
        return NO_CHANGE
    rounded = round_half_up(value)
    if rounded == 0:
        return NO_CHANGE
    arrow = UP if rounded > 0 else DOWN
    return f"{arrow}{'' if compact else ' '}{_digits(abs(rounded), decimal_separator)}"


def format_net(value: float, decimal_separator: str = DECIMAL_SEPARATOR) -> str:
    """SCO-01's net (U−D)/(U+D) with sign and two decimals: "+0,60", "−1,00", "0,00" (A23)."""
    rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded == 0:
        return _digits(abs(rounded), decimal_separator)
    sign = "+" if rounded > 0 else MINUS
    return f"{sign}{_digits(abs(rounded), decimal_separator)}"
