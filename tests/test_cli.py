from sqlalchemy import select

from app.extensions import db
from app.models import AllowedEmail


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
