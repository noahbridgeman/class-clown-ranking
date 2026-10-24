"""Screenshots of every page, to check that a refactoring changes nothing visible.

python scripts/screenshots.py capture /tmp/shots/before
python scripts/screenshots.py capture /tmp/shots/after
python scripts/screenshots.py compare /tmp/shots/before /tmp/shots/after

Renders all pages with fixed data and a frozen clock through the Flask test client, then
photographs them with headless Chrome at phone and desktop width. Output is deterministic,
so unchanged pages give byte-identical PNGs. Needs Google Chrome or Chromium (path via
--chrome or $CHROME). New pages belong in render_pages().
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The test helpers seed the data; they are not part of the installed package.
sys.path.insert(0, str(ROOT))

from flask import Flask  # noqa: E402
from flask.testing import FlaskClient  # noqa: E402

from app import create_app  # noqa: E402
from app.clock import FrozenClock  # noqa: E402
from app.config import TestConfig  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import User  # noqa: E402
from app.services import invitations, membership  # noqa: E402
from app.services.mail import Mail  # noqa: E402
from tests.conftest import IsolatedClient  # noqa: E402
from tests.factories import (  # noqa: E402
    IN_WEEK_WINDOW,
    WEEK_CLOSES,
    add_member,
    allow,
    make_group,
    make_user,
    tick,
    vote,
)

START = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
SIZES = {"mobile": (390, 1500), "desktop": (1280, 1100)}
# Headless Chrome has a minimum window width, so narrow sizes are rendered in an iframe.
MIN_WINDOW_WIDTH = 600
CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
    "chromium-browser",
)
CSRF_VALUE = re.compile(r'(csrf[-_]token"?\s*(?:content|value)=)"[^"]*"')
CSRF_HEADER = re.compile(r'"X-CSRFToken": "[^"]*"')
REMOTE_SCRIPT = re.compile(r'<script src="https://[^>]*></script>')


class Pages:
    """Collects rendered pages by name."""

    def __init__(self, app: Flask) -> None:
        self.app = app
        self.html: dict[str, str] = {}

    def client(self, user: User | None = None) -> FlaskClient:
        client = self.app.test_client()
        if user is not None:
            with client.session_transaction() as session:
                session["_user_id"] = user.get_id()
        return client

    def grab(
        self,
        name: str,
        client: FlaskClient,
        url: str,
        method: str = "GET",
        data: dict[str, str] | None = None,
    ) -> None:
        response = client.open(url, method=method, data=data or {}, follow_redirects=True)
        self.html[name] = response.get_data(as_text=True)


def render_pages() -> dict[str, str]:
    """Every page in its typical states, by name."""
    clock = FrozenClock(START)
    app = create_app(TestConfig, clock=clock)
    app.test_client_class = IsolatedClient
    pages = Pages(app)
    with app.app_context():
        db.create_all()
        outbox: list[Mail] = app.extensions["mail"].outbox
        ada = make_user("ada@example.org", "Ada")
        bo = make_user("bo@example.org", "Bo Brettspiel")
        cleo = make_user("cleo@example.org", "Cleo")
        loner = make_user("solo@example.org", "Solo")
        group = make_group(ada, "Die Spaßvögel")
        add_member(group, bo)
        add_member(group, cleo)
        make_group(ada, "Büro")
        solo = make_group(loner, "Allein")
        for email in ("eins@example.org", "zwei@example.org", "drei@example.org"):
            invitations.invite(group, ada, email)
        invitations.revoke(group, ada, invitations.invitations_of(group)[0].id)
        g = f"/g/{group.id}"

        guest = pages.client()
        pages.grab("index_guest", guest, "/")
        pages.grab("login", guest, "/login")
        pages.grab("login_error", guest, "/login", "POST", {"email": "kein-at"})
        allow("gast@example.org")
        pages.grab("login_sent", guest, "/login", "POST", {"email": "gast@example.org"})
        pages.grab("login_confirm", guest, _link_path(outbox[-1]))
        pages.grab("login_invalid", guest, "/login/kaputt")
        pages.grab("invite_accept", guest, _link_path(outbox[1]))
        pages.grab("invite_invalid", guest, "/invite/kaputt")
        pages.grab("invite_wrong_account", pages.client(cleo), _link_path(outbox[2]))
        pages.grab("not_found", guest, "/gibt-es-nicht")

        nameless = make_user("neu@example.org", None)
        pages.grab("name_first", pages.client(nameless), "/account/name")
        pages.grab("name_change", pages.client(ada), "/account/name")
        pages.grab("index_member", pages.client(ada), "/")
        pages.grab("index_no_groups", pages.client(make_user("leer@example.org", "Leer")), "/")
        pages.grab("group_new", pages.client(ada), "/groups/new")
        pages.grab("group_new_error", pages.client(ada), "/groups/new", "POST", {"name": " "})
        pages.grab("group_home_admin", pages.client(ada), f"{g}/")
        pages.grab("group_home_member", pages.client(bo), f"{g}/")
        pages.grab("group_flash", pages.client(ada), f"{g}/members/{ada.id}/remove", "POST")
        pages.grab("leave_member", pages.client(bo), f"{g}/leave")
        pages.grab("leave_admin", pages.client(ada), f"{g}/leave")
        pages.grab("leave_last", pages.client(loner), f"/g/{solo.id}/leave")
        pages.grab("delete", pages.client(ada), f"{g}/delete")
        pages.grab("delete_error", pages.client(ada), f"{g}/delete", "POST", {"confirmation": "x"})
        pages.grab("invitations", pages.client(ada), f"{g}/invitations")
        pages.grab("forbidden", pages.client(bo), f"{g}/invitations")

        pages.grab("vote_closed", pages.client(ada), f"{g}/vote")
        clock.set(IN_WEEK_WINDOW)
        tick()
        vote(group, ada, bo, "up")
        vote(group, cleo, ada, "down")
        pages.grab("vote_open", pages.client(ada), f"{g}/vote")
        pages.grab("vote_error", pages.client(ada), f"{g}/vote/{ada.id}", "POST", {"choice": "up"})
        pages.grab("vote_alone", pages.client(loner), f"/g/{solo.id}/vote")
        vote(group, bo, cleo, "up")
        clock.set(WEEK_CLOSES)
        tick()
        pages.grab("group_ranking_first", pages.client(bo), f"{g}/")
        clock.set(IN_WEEK_WINDOW + timedelta(days=7))
        tick()
        vote(group, ada, cleo, "up")
        vote(group, bo, cleo, "up")
        vote(group, cleo, bo, "down")
        clock.set(WEEK_CLOSES + timedelta(days=7))
        tick()
        pages.grab("group_ranking", pages.client(bo), f"{g}/")
        pages.grab("group_ranking_year", pages.client(bo), f"{g}/?range=1y")
        pages.grab("settings_admin", pages.client(ada), f"{g}/settings")
        settings_form = {
            "name": "Die Spaßvögel",
            "cadence": "daily",
            "params_cadence": "weekly",
            "is_anonymous": "false",
            "timezone": "Europe/Berlin",
            "k": "0,5",
            "d": "0,95",
        }
        pages.grab(
            "settings_error",
            pages.client(ada),
            f"{g}/settings",
            "POST",
            {**settings_form, "k": "9", "params_cadence": "daily"},
        )
        pages.client(ada).post(f"{g}/settings", data=settings_form)
        pages.grab("settings_member", pages.client(bo), f"{g}/settings")
        membership.leave(group, cleo)
        db.session.remove()
        db.drop_all()
        db.engine.dispose()

    html = pages.html
    html["group_home_admin_open"] = html["group_home_admin"].replace("<details ", "<details open ")
    return html


def _link_path(mail: Mail) -> str:
    match = re.search(r"https?://[^/\s]+(/\S+)", mail.body)
    if match is None:
        raise ValueError(f"no link in mail {mail.subject!r}")
    return match.group(1)


def localize(html: str) -> str:
    """Points static files to the working copy, drops CDN scripts, fixes CSRF tokens."""
    static = (ROOT / "app" / "static").as_uri()
    html = html.replace('href="/static/', f'href="{static}/').replace(
        'src="/static/', f'src="{static}/'
    )
    html = REMOTE_SCRIPT.sub("", html)
    html = CSRF_VALUE.sub(r'\1"x"', html)
    return CSRF_HEADER.sub('"X-CSRFToken": "x"', html)


def find_chrome(explicit: str | None) -> str:
    for candidate in (explicit, os.environ.get("CHROME"), *CHROME_CANDIDATES):
        if candidate and (Path(candidate).exists() or shutil.which(candidate)):
            return candidate
    raise SystemExit("Chrome nicht gefunden, Pfad mit --chrome oder $CHROME angeben.")


def capture(out: Path, chrome: str) -> int:
    pages = render_pages()
    out.mkdir(parents=True, exist_ok=True)
    for name, html in pages.items():
        source = out / f"{name}.html"
        source.write_text(localize(html))
        for size, (width, height) in SIZES.items():
            _shoot(chrome, source, out / f"{name}-{size}.png", width, height)
    print(f"{len(pages)} Seiten, {len(pages) * len(SIZES)} Screenshots in {out}")
    return 0


def _shoot(chrome: str, source: Path, png: Path, width: int, height: int) -> None:
    target = source
    if width < MIN_WINDOW_WIDTH:
        target = png.with_suffix(".frame.html")
        # A wrapper page outside the app, so the inline style rule does not apply.
        target.write_text(
            f'<body style="margin:0"><iframe src="{source.name}" '
            f'style="border:0;width:{width}px;height:{height}px"></iframe></body>'
        )
    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--window-size={max(width, MIN_WINDOW_WIDTH)},{height}",
            f"--screenshot={png}",
            # Same origin for the iframe, or Chrome ignores autofocus inside it.
            "--allow-file-access-from-files",
            target.as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )


def differences(before: Path, after: Path) -> list[str]:
    """Names of screenshots that differ or exist on one side only."""
    old = {path.name for path in before.glob("*.png")}
    new = {path.name for path in after.glob("*.png")}
    changed = {
        name for name in old & new if (before / name).read_bytes() != (after / name).read_bytes()
    }
    return sorted(changed | (old ^ new))


def compare(before: Path, after: Path) -> int:
    found = differences(before, after)
    total = len({path.name for path in [*before.glob("*.png"), *after.glob("*.png")]})
    for name in found:
        print(f"anders: {name}")
    print(f"{total - len(found)} von {total} Screenshots gleich.")
    return 1 if found else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    shoot = commands.add_parser("capture", help="Alle Seiten rendern und fotografieren")
    shoot.add_argument("out", type=Path)
    shoot.add_argument("--chrome", help="Pfad zu Chrome oder Chromium")
    check = commands.add_parser("compare", help="Zwei Aufnahmen vergleichen")
    check.add_argument("before", type=Path)
    check.add_argument("after", type=Path)
    args = parser.parse_args(argv)
    if args.command == "capture":
        return capture(args.out, find_chrome(args.chrome))
    return compare(args.before, args.after)


if __name__ == "__main__":
    sys.exit(main())
