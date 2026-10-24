"""Group settings (SET-01…06, A6, E1).

A change never touches the running period: it is logged as pending and the next window
takes it over when it opens, together with all other pending changes (E1). The groups
columns hold the effective values, `upcoming()` the values the next window will use.
Values are stored as text: floats with repr() so they read back exactly.
"""

import math
from dataclasses import dataclass, fields, replace
from datetime import datetime
from functools import cache
from zoneinfo import available_timezones

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.clock import get_clock
from app.domain import schedule, scoring
from app.domain.types import Cadence
from app.extensions import db
from app.models import Group, Period, SettingField, SettingsChange, User
from app.models.group import GROUP_NAME_MAX_LENGTH
from app.services import periods
from app.services.errors import InvalidInput
from app.services.locks import lock_group
from app.services.text import clean_name

SettingValue = str | bool | float | Cadence


@dataclass(frozen=True)
class GroupSettings:
    name: str
    cadence: Cadence
    is_anonymous: bool
    timezone: str
    k: float
    d: float

    @property
    def params(self) -> scoring.ScoreParams:
        return scoring.ScoreParams(k=self.k, d=self.d)

    def value(self, field: SettingField) -> SettingValue:
        return getattr(self, field.value)


FIELDS = [SettingField(f.name) for f in fields(GroupSettings)]


class InvalidSettings(InvalidInput):
    """One message per invalid field, so the form can show each next to its input."""

    def __init__(self, errors: dict[SettingField, InvalidInput]) -> None:
        first = next(iter(errors.values()))
        super().__init__(first.message_key, **first.params)
        self.errors = errors


def effective(group: Group) -> GroupSettings:
    return GroupSettings(**{field.value: getattr(group, field.value) for field in FIELDS})


def pending_changes(group_id: int) -> list[SettingsChange]:
    return list(
        db.session.scalars(
            select(SettingsChange)
            .where(SettingsChange.group_id == group_id, SettingsChange.applied_at.is_(None))
            .order_by(SettingsChange.id)
        )
    )


def upcoming(group: Group, pending: list[SettingsChange] | None = None) -> GroupSettings:
    """The settings the next window will use: effective values, then pending changes in
    order, so the latest change of a field wins."""
    values = effective(group)
    for change in pending_changes(group.id) if pending is None else pending:
        values = replace(values, **{change.field.value: parse(change.field, change.new_value)})
    return values


def pending_fields(group: Group) -> dict[SettingField, SettingValue]:
    """Fields whose upcoming value differs from the effective one, with that value."""
    now, then = effective(group), upcoming(group)
    return {field: then.value(field) for field in FIELDS if then.value(field) != now.value(field)}


def takes_effect_at(group: Group, now: datetime) -> datetime:
    """SET-01: when the window that takes over the pending settings opens.

    Mirrors periods.open_current: the running period ends first, and a window that
    overlaps the latest period gets no period of its own.
    """
    settings = upcoming(group)
    running = periods.open_period(group.id)
    after = max(now, running.closes_at) if running else now
    window = schedule.window_at(after, settings.cadence, settings.timezone)
    if window is None or periods.had_period(group.id, window):
        window = schedule.next_window(after, settings.cadence, settings.timezone)
    return window.opens_at


def change(group: Group, actor: User, wanted: GroupSettings) -> list[SettingsChange]:
    """Logs every field that differs from its upcoming value (SET-03). Only the admin may
    call this; the route checks the role. Commits."""
    lock_group(group)
    checked = validate(wanted)
    before = upcoming(group)
    now = get_clock().now()
    changes = [
        SettingsChange(
            group_id=group.id,
            changed_by_user_id=actor.id,
            changed_at=now,
            field=field,
            old_value=serialize(before.value(field)),
            new_value=serialize(checked.value(field)),
        )
        for field in FIELDS
        if checked.value(field) != before.value(field)
    ]
    db.session.add_all(changes)
    db.session.commit()
    return changes


def validate(wanted: GroupSettings) -> GroupSettings:
    """Cleans the name and checks every field (SET-05); raises InvalidSettings."""
    errors: dict[SettingField, InvalidInput] = {}
    name = wanted.name
    try:
        name = clean_name(wanted.name, GROUP_NAME_MAX_LENGTH)
    except InvalidInput as invalid:
        errors[SettingField.NAME] = invalid
    if wanted.timezone not in timezones():
        errors[SettingField.TIMEZONE] = InvalidInput("settings.invalid_timezone")
    bounds = scoring.bounds(wanted.cadence, wanted.d)
    invalid_params = scoring.validate(wanted.params, wanted.cadence)
    if "k" in invalid_params:
        errors[SettingField.K] = InvalidInput(
            "settings.k_out_of_range",
            min=format_param(bounds.k_min),
            max=format_param(bounds.k_max),
        )
    if "d" in invalid_params:
        errors[SettingField.D] = InvalidInput(
            "settings.d_out_of_range",
            min=format_param(bounds.d_min),
            max=format_param(bounds.d_max),
        )
    if errors:
        raise InvalidSettings(errors)
    return replace(wanted, name=name)


def apply_pending(group: Group, period: Period, now: datetime) -> None:
    """E1: called when a window opens, before its snapshot is taken. Does not commit."""
    pending = pending_changes(group.id)
    if not pending:
        return
    settings = upcoming(group, pending)
    for field in FIELDS:
        setattr(group, field.value, settings.value(field))
    for change in pending:
        change.applied_at = now
        change.applied_in_period_id = period.id


def log(group_id: int) -> list[SettingsChange]:
    """SET-03: every change, newest first, for all members."""
    return list(
        db.session.scalars(
            select(SettingsChange)
            .options(joinedload(SettingsChange.changed_by))
            .where(SettingsChange.group_id == group_id)
            .order_by(SettingsChange.changed_at.desc(), SettingsChange.id.desc())
        )
    )


def applied_changes(
    group_id: int, since: datetime | None
) -> list[tuple[datetime, set[SettingField]]]:
    """Per window that took over changes: when, and which fields really changed (GRA-07).

    A field changed back and forth before the window opened did not change.
    """
    query = (
        select(SettingsChange)
        .where(SettingsChange.group_id == group_id, SettingsChange.applied_at.is_not(None))
        .order_by(SettingsChange.applied_at, SettingsChange.id)
    )
    if since is not None:
        query = query.where(SettingsChange.applied_at > since)
    batches: dict[datetime, dict[SettingField, tuple[str, str]]] = {}
    for change in db.session.scalars(query):
        if change.applied_at is None:
            continue
        batch = batches.setdefault(change.applied_at, {})
        first_old = batch[change.field][0] if change.field in batch else change.old_value
        batch[change.field] = (first_old, change.new_value)
    return [
        (at, {field for field, (old, new) in batch.items() if old != new})
        for at, batch in batches.items()
        if any(old != new for old, new in batch.values())
    ]


@cache
def timezones() -> frozenset[str]:
    return frozenset(available_timezones())


def serialize(value: SettingValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def parse(field: SettingField, text: str) -> SettingValue:
    if field is SettingField.CADENCE:
        return Cadence(text)
    if field is SettingField.IS_ANONYMOUS:
        return text == "true"
    if field in (SettingField.K, SettingField.D):
        return float(text)
    return text


def parse_number(text: str | None) -> float:
    """Accepts a decimal comma or point; NaN for anything else, which validate() rejects."""
    try:
        value = float((text or "").strip().replace(",", "."))
    except ValueError:
        return math.nan
    return value if math.isfinite(value) else math.nan


def format_param(value: float, decimals: int = 6, decimal_separator: str = ",") -> str:
    """Six decimals for reading. Form inputs use INPUT_DECIMALS, so that a converted value
    at a bound reads back within the tolerance of scoring.validate (A11)."""
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return text.replace(".", decimal_separator)


INPUT_DECIMALS = 10
