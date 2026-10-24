"""Validation of free text such as display and group names (A15)."""

import unicodedata

from app.services.errors import InvalidInput

# Invisible or layout-changing characters: controls, format characters such as bidi
# overrides and zero-width spaces, surrogates, private use, unassigned, line separators.
_FORBIDDEN_NAME_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}
# The zero-width joiner is a format character, but emoji sequences such as 👨‍👩‍👧 need it.
_ALLOWED_FORMAT_CHARS = {"\u200d"}
# Letters that render as blank space.
_BLANK_LETTERS = {"\u115f", "\u1160", "\u3164", "\uffa0", "\u2800"}


def clean_name(raw: str, max_length: int) -> str:
    """Trims and collapses whitespace and rejects invisible or layout-changing characters."""
    name = " ".join(raw.split())
    if not name:
        raise InvalidInput("validation.name_required")
    if len(name) > max_length:
        raise InvalidInput("validation.name_too_long", max=max_length)
    if any(_forbidden_in_name(char) for char in name):
        raise InvalidInput("validation.name_invalid")
    if not any(_visible(char) for char in name):
        raise InvalidInput("validation.name_required")
    return name


def _forbidden_in_name(char: str) -> bool:
    category = unicodedata.category(char)
    return category in _FORBIDDEN_NAME_CATEGORIES and char not in _ALLOWED_FORMAT_CHARS


def _visible(char: str) -> bool:
    # Letters, numbers, punctuation, symbols; marks and spaces alone show nothing.
    return unicodedata.category(char)[0] in "LNPS" and char not in _BLANK_LETTERS
