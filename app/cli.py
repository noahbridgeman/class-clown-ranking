import click
from flask import Flask
from flask.cli import AppGroup

from app.i18n import t
from app.services import auth

users = AppGroup("users", help="Konten und Allowlist verwalten.")


@users.command("allow")
@click.argument("email")
def allow(email: str) -> None:
    """Erlaubt einer Adresse, ein Konto ohne Einladung anzulegen (E3)."""
    try:
        added = auth.allow_email(email)
    except auth.InvalidInput as invalid:
        raise click.BadParameter(t("cli.email_invalid"), param_hint="EMAIL") from invalid
    key = "cli.allow_added" if added else "cli.allow_exists"
    click.echo(t(key, email=auth.normalize_email(email)))


def register(app: Flask) -> None:
    app.cli.add_command(users)
