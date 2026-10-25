import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from string import Formatter

import pytest

from app.i18n import (
    Translator,
    _flatten,
    countdown,
    countdown_short,
    load_texts,
    short_date,
    short_datetime,
    t,
    weekday_time,
    window_dates,
)

APP_DIR = Path(__file__).parent.parent / "app"
KEY_USAGE = re.compile(r"""\bt\(\s*["']([\w.]+)["']""")


def test_t_resolves_nested_keys(app):
    assert t("app.name") == "Spaßvogel-Ranking"


def test_t_formats_parameters():
    translate = Translator({"greet": "Hallo {name}"})
    assert translate("greet", name="Noah") == "Hallo Noah"


def test_escaped_braces_render_the_same_with_and_without_params():
    translate = Translator({"text": "{{x}} {name}", "plain": "{{x}}"})
    assert translate("plain") == "{x}"
    assert translate("text", name="A") == "{x} A"


def test_missing_key_raises_in_strict_mode():
    with pytest.raises(KeyError):
        Translator({}, strict=True)("nope")


def test_missing_key_falls_back_to_key_otherwise():
    assert Translator({})("nope") == "nope"


def test_missing_param_raises_in_strict_mode():
    with pytest.raises(KeyError):
        Translator({"greet": "Hallo {name}"}, strict=True)("greet")


def test_missing_param_stays_visible_otherwise():
    assert Translator({"greet": "Hallo {name}"})("greet") == "Hallo {name}"


def test_non_string_values_are_rejected():
    with pytest.raises(TypeError, match="limit"):
        _flatten({"limit": 140})


def test_every_used_key_exists_in_german_texts():
    known = set(load_texts("de"))
    sources = [*APP_DIR.rglob("*.html"), *APP_DIR.rglob("*.py")]
    used = {key for path in sources for key in KEY_USAGE.findall(path.read_text())}
    assert used, "expected at least one t() usage"
    assert used <= known, f"missing keys: {sorted(used - known)}"


def test_german_texts_use_only_simple_named_placeholders():
    # {user.name} or {0} would crash pages even in non-strict mode.
    bad = {
        key: field
        for key, text in load_texts("de").items()
        for _, field, _, _ in Formatter().parse(text)
        if field is not None and not field.isidentifier()
    }
    assert not bad


def test_local_date_uses_the_group_timezone():
    from datetime import UTC, datetime

    from app.i18n import local_date

    # 23:30 UTC on 30 Oct is already 31 Oct in Berlin (UTC+1 after the switch on 25 Oct).
    assert local_date(datetime(2026, 10, 30, 23, 30, tzinfo=UTC), "Europe/Berlin") == "31.10.2026"
    assert (
        local_date(datetime(2026, 10, 30, 23, 30, tzinfo=UTC), "America/New_York") == "30.10.2026"
    )


def test_local_datetime_names_weekday_and_local_time(app):
    from datetime import UTC, datetime

    from app.i18n import local_datetime

    closes = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
    assert local_datetime(closes, "Europe/Berlin") == "Mo. 26.10.2026 um 13:00 Uhr"


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "0 Min."),
        (1, "1 Min."),  # rounded up, so "0 Min." only shows at the very end
        (59 * 60, "59 Min."),
        (2 * 3600 + 5 * 60, "2 Std. 5 Min."),
        (37 * 3600 + 1, "1 T. 13 Std."),
        (-30, "0 Min."),
    ],
)
def test_duration(app, seconds, text):
    from datetime import timedelta

    from app.i18n import duration

    assert duration(timedelta(seconds=seconds)) == text


@pytest.mark.parametrize(
    ("remaining", "full", "short"),
    [
        (timedelta(hours=20, minutes=46, seconds=1), "20:47 h", "20:47 h"),
        (timedelta(days=3, hours=14, minutes=22), "3 T 14:22 h", "3 T"),
        (timedelta(minutes=5), "0:05 h", "0:05 h"),
        (timedelta(seconds=-3), "0:00 h", "0:00 h"),
    ],
)
def test_countdown(app, remaining, full, short):
    assert countdown(remaining) == full
    assert countdown_short(remaining) == short


def test_short_formats(app):
    at = datetime(2026, 10, 19, 11, 0, tzinfo=UTC)  # Monday 13:00 in Berlin
    assert short_datetime(at, "Europe/Berlin") == "Mo 19.10., 13:00"
    assert short_date(at, "Europe/Berlin") == "Mo 19.10."
    assert weekday_time(at, "Europe/Berlin") == "Mo 13:00"


@pytest.mark.parametrize(
    ("opens", "closes", "text"),
    [
        (
            datetime(2026, 10, 24, 22, tzinfo=UTC),
            datetime(2026, 10, 26, 12, tzinfo=UTC),
            "25./26.10.",
        ),
        (
            datetime(2026, 10, 31, 23, tzinfo=UTC),
            datetime(2026, 11, 2, 12, tzinfo=UTC),
            "01./02.11.",
        ),
        (
            datetime(2026, 10, 30, 12, tzinfo=UTC),
            datetime(2026, 11, 1, 12, tzinfo=UTC),
            "30.10./01.11.",
        ),
    ],
)
def test_window_dates(opens, closes, text):
    assert window_dates(opens, closes, "Europe/Berlin") == text
