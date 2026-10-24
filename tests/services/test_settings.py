"""SET-01…06, PER-05, SCO-07 (integration): pending settings and their takeover."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.domain import scoring
from app.domain.types import Cadence
from app.extensions import db
from app.models import Period, SettingField, SettingsChange
from app.services import periods, settings, voting
from app.services.settings import InvalidSettings
from tests.factories import (
    IN_WEEK_WINDOW,
    WEEK_CLOSES,
    WEEK_OPENS,
    add_member,
    make_group,
    make_user,
    tick,
)


@pytest.fixture
def group(app):
    admin = make_user(display_name="Ada")
    group = make_group(admin, "Runde")
    add_member(group)
    return group


def change(group, **values):
    wanted = replace(settings.upcoming(group), **values)
    return settings.change(group, group.admin, wanted)


def all_periods(group):
    return list(
        db.session.scalars(select(Period).where(Period.group_id == group.id).order_by(Period.seq))
    )


class TestChange:
    def test_logs_only_changed_fields_with_old_and_new_value(self, group):
        """SET-03"""
        [entry] = change(group, name="  Neue   Runde ")
        assert (entry.field, entry.old_value, entry.new_value) == (
            SettingField.NAME,
            "Runde",
            "Neue Runde",
        )
        assert entry.applied_at is None
        assert entry.changed_by_user_id == group.admin_user_id

    def test_nothing_changes_until_the_next_window(self, group):
        """SET-01: the groups columns hold the effective values."""
        change(group, name="Neu", is_anonymous=False)
        assert (group.name, group.is_anonymous) == ("Runde", True)
        assert settings.pending_fields(group) == {
            SettingField.NAME: "Neu",
            SettingField.IS_ANONYMOUS: False,
        }

    def test_latest_change_wins_and_each_is_logged(self, group):
        change(group, name="Eins")
        change(group, name="Zwei")
        assert settings.upcoming(group).name == "Zwei"
        old_new = [(c.old_value, c.new_value) for c in settings.log(group.id)]
        assert old_new == [("Eins", "Zwei"), ("Runde", "Eins")]

    def test_changing_back_leaves_nothing_pending(self, group):
        change(group, name="Eins")
        change(group, name="Runde")
        assert settings.pending_fields(group) == {}

    def test_floats_round_trip_exactly(self, group):
        params = scoring.convert_params(
            settings.effective(group).params, Cadence.WEEKLY, Cadence.DAILY
        )
        change(group, cadence=Cadence.DAILY, k=params.k, d=params.d)
        assert settings.upcoming(group).params == params

    @pytest.mark.parametrize(
        ("values", "fields"),
        [
            ({"name": "  "}, {SettingField.NAME}),
            ({"timezone": "Mars/Olympus"}, {SettingField.TIMEZONE}),
            ({"k": 5.0}, {SettingField.K}),
            ({"d": 1.0}, {SettingField.D}),
            ({"k": float("nan"), "d": 0.1}, {SettingField.K, SettingField.D}),
        ],
    )
    def test_rejects_invalid_values(self, group, values, fields):
        """SET-05 (A11) and the timezone check against zoneinfo."""
        with pytest.raises(InvalidSettings) as raised:
            change(group, **values)
        assert set(raised.value.errors) == fields
        assert db.session.scalar(select(SettingsChange)) is None

    def test_daily_bounds_follow_from_the_weekly_ones(self, group):
        """A daily K that is valid only with a weekly d is rejected."""
        with pytest.raises(InvalidSettings):
            change(group, cadence=Cadence.DAILY)  # K and d still weekly


class TestTakeover:
    def test_change_during_the_window_applies_to_the_next_one(self, group, clock):
        """SET-01, SET-06, VOT-09: the running period keeps its snapshot."""
        clock.set(IN_WEEK_WINDOW)
        tick()
        change(group, is_anonymous=False, k=0.8)
        clock.set(WEEK_CLOSES)
        tick()
        clock.set(IN_WEEK_WINDOW + timedelta(days=7))
        tick()
        first, second = all_periods(group)
        assert (first.is_anonymous, first.k) == (True, 0.5)
        assert (second.is_anonymous, second.k) == (False, 0.8)
        assert (group.is_anonymous, group.k) == (False, 0.8)
        assert all(c.applied_in_period_id == second.id for c in settings.log(group.id))
        assert settings.pending_fields(group) == {}

    def test_name_is_a_setting_too(self, group, clock):
        """A6"""
        change(group, name="Neu")
        clock.set(WEEK_OPENS)
        tick()
        assert group.name == "Neu"

    def test_weekly_to_daily_starts_after_the_running_period(self, group, clock):
        """PER-05: the running period ends by the old cadence, the next runs daily."""
        clock.set(IN_WEEK_WINDOW)
        tick()
        daily = scoring.convert_params(
            settings.effective(group).params, Cadence.WEEKLY, Cadence.DAILY
        )
        change(group, cadence=Cadence.DAILY, k=daily.k, d=daily.d)
        assert settings.takes_effect_at(group, clock.now()) == WEEK_CLOSES
        clock.set(WEEK_CLOSES)
        tick()
        weekly, first_daily = all_periods(group)
        assert weekly.closes_at == WEEK_CLOSES
        assert first_daily.cadence == Cadence.DAILY
        assert (first_daily.opens_at, first_daily.k) == (WEEK_CLOSES, daily.k)
        assert first_daily.closes_at - first_daily.opens_at == timedelta(days=1)

    def test_daily_to_weekly_waits_for_sunday(self, group, clock):
        """PER-05: after the last daily period no window until the weekly one opens."""
        daily = scoring.default_params(Cadence.DAILY)
        change(group, cadence=Cadence.DAILY, k=daily.k, d=daily.d)
        tick()  # Friday 14:00 Berlin: the first daily window opens with the new settings
        [first] = all_periods(group)
        assert first.cadence == Cadence.DAILY
        weekly = scoring.default_params(Cadence.WEEKLY)
        change(group, cadence=Cadence.WEEKLY, k=weekly.k, d=weekly.d)
        assert settings.takes_effect_at(group, clock.now()) == WEEK_OPENS
        clock.set(first.closes_at)
        tick()
        assert len(all_periods(group)) == 1
        assert group.cadence == Cadence.DAILY
        clock.set(WEEK_OPENS)
        tick()
        assert all_periods(group)[-1].cadence == Cadence.WEEKLY

    def test_without_a_running_period_the_next_window_takes_over(self, group, clock):
        change(group, name="Neu")
        assert settings.takes_effect_at(group, clock.now()) == WEEK_OPENS

    def test_timezone_change_moves_the_next_window(self, group, clock):
        change(group, timezone="America/New_York")
        opens = settings.takes_effect_at(group, clock.now())
        assert opens == datetime(2026, 10, 25, 4, 0, tzinfo=UTC)  # Sunday 00:00 EDT
        clock.set(opens)
        tick()
        assert periods.open_period(group.id).opens_at == opens

    def test_ballot_follows_the_upcoming_cadence(self, group, clock):
        """VOT-10: on a Tuesday a weekly group waits for Sunday; switched to daily, the
        current daily window opens with the next update."""
        clock.set(datetime(2026, 10, 27, 10, 0, tzinfo=UTC))
        sunday = datetime(2026, 10, 31, 23, 0, tzinfo=UTC)  # 00:00 CET, after the switch
        assert voting.ballot(group, group.admin).next_opens_at == sunday
        daily = scoring.default_params(Cadence.DAILY)
        change(group, cadence=Cadence.DAILY, k=daily.k, d=daily.d)
        assert voting.ballot(group, group.admin).next_opens_at is None  # "opens soon"
        tick()
        assert periods.open_period(group.id).cadence == Cadence.DAILY


class TestAppliedChanges:
    def test_only_real_changes_count(self, group, clock):
        change(group, name="Eins", k=0.8)
        change(group, name="Runde")
        clock.set(WEEK_OPENS)
        tick()
        [(at, fields)] = settings.applied_changes(group.id, None)
        assert at == WEEK_OPENS
        assert fields == {SettingField.K}


@pytest.mark.parametrize(
    ("text", "value"), [("0,5", 0.5), (" 0.25 ", 0.25), ("x", None), ("inf", None), ("", None)]
)
def test_parse_number(text, value):
    parsed = settings.parse_number(text)
    assert parsed == value if value is not None else parsed != parsed


def test_format_param():
    assert settings.format_param(0.5) == "0,5"
    assert settings.format_param(0.123456789, settings.INPUT_DECIMALS) == "0,123456789"
