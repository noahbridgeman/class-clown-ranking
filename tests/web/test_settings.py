"""Settings page (SET-01…05) and the HTMX preview."""

import re

import pytest
from sqlalchemy import select

from app.domain import scoring
from app.domain.types import Cadence
from app.extensions import db
from app.models import SettingsChange
from app.services import settings
from tests.factories import WEEK_OPENS, add_member, make_group, make_user, tick


@pytest.fixture
def world(app):
    admin = make_user(display_name="Ada")
    group = make_group(admin, "Runde")
    member = add_member(group, make_user(display_name="Bo"))
    return group, admin, member


def form(**overrides):
    values = {
        "name": "Runde",
        "cadence": "weekly",
        "params_cadence": "weekly",
        "is_anonymous": "true",
        "timezone": "Europe/Berlin",
        "k": "0,5",
        "d": "0,95",
    }
    return {**values, **overrides}


def changes():
    return list(db.session.scalars(select(SettingsChange).order_by(SettingsChange.id)))


class TestReading:
    def test_members_see_all_values_without_a_form(self, world, login_as):
        """SET-02: the score parameters too."""
        group, _admin, member = world
        html = login_as(member).get(f"/g/{group.id}/settings").get_data(as_text=True)
        assert '<form class="form"' not in html
        for text in ("Runde", "wöchentlich", "anonym", "Europe/Berlin", "0,5", "0,95"):
            assert text in html
        assert "Nur der Admin" in html

    def test_admin_sees_the_form_with_preview(self, world, login_as):
        group, admin, _member = world
        html = login_as(admin).get(f"/g/{group.id}/settings").get_data(as_text=True)
        assert 'name="k"' in html and 'value="0,5"' in html
        assert "Höchster erreichbarer Score" in html
        assert "data-preview=" in html
        assert "/static/js/preview.js" in html

    def test_link_from_the_group_page(self, world, login_as):
        group, _admin, member = world
        html = login_as(member).get(f"/g/{group.id}/").get_data(as_text=True)
        assert f'href="/g/{group.id}/settings"' in html


class TestSaving:
    def test_change_is_pending_and_logged(self, world, login_as):
        """SET-01, SET-03: visible to every member as pending, with old and new value."""
        group, admin, member = world
        response = login_as(admin).post(
            f"/g/{group.id}/settings", data=form(name="Neu", is_anonymous="false")
        )
        assert response.status_code == 302
        assert group.name == "Runde"
        html = login_as(member).get(f"/g/{group.id}/settings").get_data(as_text=True)
        assert "Ausstehend ab So. 25.10.2026 um 00:00 Uhr" in html
        assert "Gruppenname: Runde → Neu" in html
        assert "Anonymität: anonym → offen" in html
        assert "ausstehend" in html

    def test_applied_changes_show_since_when(self, world, clock, login_as):
        group, admin, member = world
        login_as(admin).post(f"/g/{group.id}/settings", data=form(name="Neu"))
        clock.set(WEEK_OPENS)
        tick()
        html = login_as(member).get(f"/g/{group.id}/settings").get_data(as_text=True)
        assert "gilt seit 25.10.2026" in html
        assert "Ausstehend" not in html

    def test_nothing_changed(self, world, login_as):
        group, admin, _member = world
        client = login_as(admin)
        client.post(f"/g/{group.id}/settings", data=form())
        assert changes() == []
        assert "nichts geändert" in client.get(f"/g/{group.id}/settings").get_data(as_text=True)

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("k", "9", "K muss zwischen 0,05 und 2 liegen."),
            ("d", "eins", "d muss zwischen 0,5 und 0,99 liegen."),
            ("timezone", "Mars/Olympus", "Unbekannte Zeitzone."),
            ("name", " ", "Bitte gib einen Namen ein."),
            ("cadence", "monthly", "Ungültige Auswahl."),
        ],
    )
    def test_invalid_input(self, world, login_as, field, value, message):
        """SET-05: bounds are checked on the server, the form keeps the input."""
        group, admin, _member = world
        response = login_as(admin).post(f"/g/{group.id}/settings", data=form(**{field: value}))
        assert response.status_code == 400
        assert message in response.get_data(as_text=True)
        assert changes() == []

    def test_cadence_change_converts_k_and_d_without_javascript(self, world, login_as):
        """SET-04 / SCO-07: K and d were entered for weekly and are converted."""
        group, admin, _member = world
        login_as(admin).post(f"/g/{group.id}/settings", data=form(cadence="daily"))
        upcoming = settings.upcoming(group)
        expected = scoring.convert_params(
            scoring.ScoreParams(0.5, 0.95), Cadence.WEEKLY, Cadence.DAILY
        )
        assert upcoming.cadence == Cadence.DAILY
        assert upcoming.params == expected


class TestParams:
    def test_cadence_switch_fills_in_converted_values(self, world, login_as):
        group, admin, _member = world
        url = f"/g/{group.id}/settings/params"
        html = login_as(admin).get(url, query_string=form(cadence="daily")).get_data(as_text=True)
        daily = scoring.convert_params(
            scoring.ScoreParams(0.5, 0.95), Cadence.WEEKLY, Cadence.DAILY
        )
        k = re.search(r'name="k"[^>]*value="([^"]+)"', html).group(1)
        assert settings.parse_number(k) == pytest.approx(daily.k, rel=1e-9)
        assert 'name="params_cadence" value="daily"' in html
        assert "Höchster erreichbarer Score" in html

    def test_converted_bound_values_stay_valid(self, world, login_as):
        """A11: a weekly d at its bound is valid as daily too, after the round trip
        through the form."""
        group, admin, _member = world
        url = f"/g/{group.id}/settings/params"
        html = (
            login_as(admin)
            .get(url, query_string=form(cadence="daily", d="0,5", k="0,05"))
            .get_data(as_text=True)
        )
        assert 'class="error"' not in html
        k = re.search(r'name="k"[^>]*value="([^"]+)"', html).group(1)
        d = re.search(r'name="d"[^>]*value="([^"]+)"', html).group(1)
        login_as(admin).post(
            f"/g/{group.id}/settings", data=form(cadence="daily", params_cadence="daily", k=k, d=d)
        )
        assert settings.upcoming(group).cadence == Cadence.DAILY

    def test_invalid_values_show_the_bounds_and_no_preview(self, world, login_as):
        group, admin, _member = world
        url = f"/g/{group.id}/settings/params"
        html = login_as(admin).get(url, query_string=form(k="3")).get_data(as_text=True)
        assert "K muss zwischen 0,05 und 2 liegen." in html
        assert "data-preview" not in html
