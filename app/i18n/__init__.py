"""UI texts. Every user-facing string lives in a TOML file per locale (NFA-03)."""

import tomllib
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from flask import Flask, current_app

LOCALE_DIR = Path(__file__).parent


class Translator:
    def __init__(self, texts: Mapping[str, str], strict: bool = False) -> None:
        self._texts = texts
        self._strict = strict

    def __call__(self, key: str, **params: Any) -> str:
        text = self._texts.get(key)
        if text is None:
            if self._strict:
                raise KeyError(f"Missing translation: {key}")
            return key
        # Always format, so "{{" means a literal brace whether or not params are given.
        return text.format_map(params if self._strict else _KeepMissing(params))

    def keys(self) -> set[str]:
        return set(self._texts)


class _KeepMissing(dict[str, Any]):
    """Leaves unknown placeholders visible instead of failing the whole page."""

    def __missing__(self, name: str) -> str:
        return f"{{{name}}}"


def load_texts(locale: str) -> dict[str, str]:
    with (LOCALE_DIR / f"{locale}.toml").open("rb") as f:
        return _flatten(tomllib.load(f))


def _flatten(tree: Mapping[str, Any], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for name, value in tree.items():
        key = f"{prefix}{name}"
        if isinstance(value, Mapping):
            flat.update(_flatten(value, f"{key}."))
        elif isinstance(value, str):
            flat[key] = value
        else:
            raise TypeError(f"Translation {key} must be a string, got {type(value).__name__}")
    return flat


def init_app(app: Flask) -> None:
    translator = Translator(
        load_texts(app.config["DEFAULT_LOCALE"]), strict=app.config["I18N_STRICT"]
    )
    app.extensions["translator"] = translator
    app.jinja_env.globals["t"] = translator
    app.jinja_env.filters["local_date"] = local_date
    app.jinja_env.filters["local_datetime"] = local_datetime
    app.jinja_env.filters["duration"] = duration


def t(key: str, **params: Any) -> str:
    return current_app.extensions["translator"](key, **params)


def local_date(value: datetime, timezone: str) -> str:
    """A UTC timestamp as a German date in the group's timezone, e.g. 31.10.2026."""
    return value.astimezone(ZoneInfo(timezone)).strftime("%d.%m.%Y")


def local_datetime(value: datetime, timezone: str) -> str:
    """A UTC timestamp in the group's timezone, e.g. "So. 25.10.2026 um 13:00 Uhr"."""
    local = value.astimezone(ZoneInfo(timezone))
    weekday = t("time.weekdays").split(",")[local.weekday()]
    return t(
        "time.datetime",
        weekday=weekday,
        date=local.strftime("%d.%m.%Y"),
        time=local.strftime("%H:%M"),
    )


def duration(value: timedelta) -> str:
    """Remaining time, rounded up to whole minutes: "1 T. 3 Std.", "2 Std. 5 Min.", "4 Min."."""
    minutes = max(0, -(-int(value.total_seconds()) // 60))
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return t("time.days_hours", days=days, hours=hours)
    if hours:
        return t("time.hours_minutes", hours=hours, minutes=minutes)
    return t("time.minutes", minutes=minutes)
