import click
from flask import Flask
from flask.cli import AppGroup

from app.i18n import t
from app.services import auth


def register(app: Flask) -> None:
    # Help texts are resolved here because t() needs an app at import time otherwise.
    translate = app.extensions["translator"]
    users = AppGroup("users", help=translate("cli.users_help"))
    # Parameters are passed explicitly: click.argument would store them on _allow itself,
    # so every further app would add them again.
    users.command("allow", help=translate("cli.allow_help"), params=[click.Argument(["email"])])(
        _allow
    )
    app.cli.add_command(users)


def _allow(email: str) -> None:
    """Lets an address create an account without an invitation (E3)."""
    try:
        added = auth.allow_email(email)
    except auth.InvalidInput as invalid:
        raise click.BadParameter(t("cli.email_invalid"), param_hint="EMAIL") from invalid
    key = "cli.allow_added" if added else "cli.allow_exists"
    click.echo(t(key, email=auth.normalize_email(email)))
