import click
from flask import Flask
from flask.cli import AppGroup

from app.i18n import t
from app.services import auth, periods, push


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
    app.cli.command("tick", help=translate("cli.tick_help"))(_tick)
    push_group = AppGroup("push", help=translate("cli.push_help"))
    push_group.command("keygen", help=translate("cli.keygen_help"))(_keygen)
    app.cli.add_command(push_group)


def _allow(email: str) -> None:
    """Lets an address create an account without an invitation (E3)."""
    try:
        added = auth.allow_email(email)
    except auth.InvalidInput as invalid:
        raise click.BadParameter(t("cli.email_invalid"), param_hint="EMAIL") from invalid
    key = "cli.allow_added" if added else "cli.allow_exists"
    click.echo(t(key, email=auth.normalize_email(email)))


def _tick() -> None:
    """Closes and opens periods (PER-01…03). Run every minute by a systemd timer."""
    report = periods.tick()
    click.echo(
        t(
            "cli.tick_done",
            opened=report.opened,
            closed=report.closed,
            skipped=report.skipped,
            tokens=report.tokens_removed,
            pushes=report.pushes,
        )
    )
    if report.failed:
        failed = ", ".join(map(str, report.failed))
        raise click.ClickException(t("cli.tick_failed", groups=failed))


def _keygen() -> None:
    """Prints a new VAPID key pair for .env (A24). Changing it invalidates every device."""
    private, public = push.generate_vapid_keys()
    click.echo(f"VAPID_PRIVATE_KEY={private}\nVAPID_PUBLIC_KEY={public}")
    click.echo(t("cli.keygen_note"), err=True)
