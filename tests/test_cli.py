from sqlalchemy import select

from app.extensions import db
from app.models import AllowedEmail
from app.services import periods
from tests.factories import IN_WEEK_WINDOW, make_group


def test_users_allow_adds_normalized_address(app):
    result = app.test_cli_runner().invoke(args=["users", "allow", " Anna@Example.org "])
    assert result.exit_code == 0
    assert "anna@example.org hinzugefügt." in result.output
    assert db.session.scalars(select(AllowedEmail.email)).all() == ["anna@example.org"]


def test_users_allow_twice_reports_existing_entry(app):
    runner = app.test_cli_runner()
    runner.invoke(args=["users", "allow", "anna@example.org"])
    result = runner.invoke(args=["users", "allow", "ANNA@example.org"])
    assert result.exit_code == 0
    assert "stand schon auf der Liste" in result.output


def test_users_allow_rejects_invalid_address(app):
    result = app.test_cli_runner().invoke(args=["users", "allow", "kein-at"])
    assert result.exit_code != 0
    assert "keine gültige E-Mail-Adresse" in result.output
    assert db.session.scalars(select(AllowedEmail)).all() == []


def test_tick_reports_what_it_did(app, clock):
    make_group()
    clock.set(IN_WEEK_WINDOW)
    result = app.test_cli_runner().invoke(args=["tick"])
    assert result.exit_code == 0
    assert "1 geöffnet, 0 berechnet, 0 übersprungen" in result.output


def test_tick_fails_loudly_when_a_group_fails(app, clock, monkeypatch):
    group = make_group()
    clock.set(IN_WEEK_WINDOW)
    monkeypatch.setattr(periods, "_open_current", lambda *_: 1 / 0)
    result = app.test_cli_runner().invoke(args=["tick"])
    assert result.exit_code != 0
    assert f"Fehler bei den Gruppen {group.id}" in result.output


def test_push_keygen_prints_a_key_pair_for_env(app):
    result = app.test_cli_runner().invoke(args=["push", "keygen"])
    assert result.exit_code == 0
    lines = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert set(lines) == {"VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY"}
    assert len(lines["VAPID_PUBLIC_KEY"]) == 87  # 65 bytes, base64url without padding
