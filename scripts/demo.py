"""Demo data for the running app, in a database of its own.

python scripts/demo.py [--email du@example.org --name Noah] [--force]
DATABASE_URL=sqlite:///demo.db flask --app app run --debug

Plays several weeks up to now with a frozen clock: a weekly WG (open, with one anonymous
stretch and a late joiner) and a daily, anonymous office group. The running window has
votes from the others, the viewer's own are left open. Logging in works as usual; the
link appears in the server's terminal. Without `flask tick` the periods do not move on.
"""

import argparse
import random
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The test helpers create the rows; they are not part of the installed package.
sys.path.insert(0, str(ROOT))

from flask import Flask  # noqa: E402
from flask_migrate import upgrade  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import create_app  # noqa: E402
from app.clock import FrozenClock  # noqa: E402
from app.config import DevConfig  # noqa: E402
from app.domain.scoring import default_params  # noqa: E402
from app.domain.types import Cadence  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Group, User  # noqa: E402
from app.services import auth, invitations, membership, periods, settings, voting  # noqa: E402
from tests.factories import add_member, make_group, make_user, tick, vote  # noqa: E402

DEFAULT_DB = ROOT / "instance" / "demo.db"
WEEKS = 9
STEP = timedelta(hours=1)
# Chance of an up per target, so the ranking has a shape.
STRENGTH = {
    "Felix": 0.7,
    "Lena": 0.64,
    "Sophie": 0.52,
    "Ali": 0.45,
    "Tim": 0.36,
    "Mara": 0.6,
    "Paul": 0.4,
    "Kim": 0.55,
}
VIEWER_STRENGTH = 0.56
REASONS = (
    "Pfandautomat-Witz zum dritten Mal",
    "Die Geschichte mit der Ente",
    "Hat den Kühlschrank-Zettel gereimt",
    "Wortspiel beim Frühstück, leider gut",
    "Zu früh am Morgen für so was",
    "Die Imitation vom Vermieter",
    "Hat über den eigenen Witz gelacht, bevor er fertig war",
)


class DemoConfig(DevConfig):
    MAIL_BACKEND = "memory"  # invitations of the demo should not show up in a terminal


def main(argv: Sequence[str] | None = None, now: datetime | None = None) -> int:
    args = _parse(argv)
    db_path = Path(args.db).resolve()
    if db_path.exists():
        if not args.force:
            print(f"{db_path} gibt es schon. Mit --force neu anlegen.")
            return 1
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(UTC)
    clock = FrozenClock(now - timedelta(weeks=WEEKS))
    app = _app(db_path, clock)
    with app.app_context():
        upgrade(directory=str(ROOT / "migrations"))
        viewer = _seed(clock, now, args.email, args.name)
        print(_summary(db_path, viewer))
        db.session.remove()
        db.engine.dispose()
    return 0


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demo-Daten für die laufende App.")
    parser.add_argument("--email", help="eigene Adresse, ersetzt Jonas als Hauptperson")
    parser.add_argument("--name", default="Jonas", help="Anzeigename der Hauptperson")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite-Datei")
    parser.add_argument("--force", action="store_true", help="vorhandene Datei ersetzen")
    return parser.parse_args(argv)


def _app(db_path: Path, clock: FrozenClock) -> Flask:
    config = type("Config", (DemoConfig,), {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}"})
    return create_app(config, clock=clock)


def _seed(clock: FrozenClock, now: datetime, email: str | None, name: str) -> User:
    rng = random.Random(43)
    viewer = make_user(auth.normalize_email(email) if email else "jonas@example.org", name)
    people = {n: make_user(f"{n.lower()}@example.org", n) for n in STRENGTH}
    strength = {viewer.id: VIEWER_STRENGTH} | {people[n].id: s for n, s in STRENGTH.items()}

    wg = make_group(viewer, "WG Hinterhof")
    _change(wg, viewer, is_anonymous=False)
    for n in ("Felix", "Lena", "Sophie", "Ali"):
        add_member(wg, people[n])

    events = {
        timedelta(weeks=3): lambda: add_member(wg, people["Tim"]),
        timedelta(weeks=5): lambda: _change(wg, viewer, is_anonymous=True),
        timedelta(weeks=6, days=3): lambda: _change(wg, viewer, is_anonymous=False),
        timedelta(weeks=6): lambda: _office(people, viewer),
        timedelta(weeks=WEEKS) - timedelta(days=2): lambda: invitations.invite(
            wg, viewer, "paul.w@example.org"
        ),
    }
    start = clock.now()
    voted: set[int] = set()
    while clock.now() < now:
        for offset in [o for o in events if start + o <= clock.now()]:
            events.pop(offset)()
        tick()
        for group in db.session.scalars(select(Group)).all():
            _vote_once(group, voted, viewer, strength, now, rng)
        clock.advance(STEP)
    clock.set(now)
    tick()
    return viewer


def _office(people: dict[str, User], viewer: User) -> Group:
    office = make_group(people["Felix"], "Büro")
    params = default_params(Cadence.DAILY)
    _change(
        office, people["Felix"], cadence=Cadence.DAILY, is_anonymous=True, k=params.k, d=params.d
    )
    for user in (viewer, people["Lena"], people["Mara"], people["Paul"], people["Kim"]):
        add_member(office, user)
    return office


def _change(group: Group, actor: User, **fields: object) -> None:
    settings.change(group, actor, replace(settings.upcoming(group), **fields))


def _vote_once(
    group: Group,
    voted: set[int],
    viewer: User,
    strength: dict[int, float],
    now: datetime,
    rng: random.Random,
) -> None:
    """Everyone votes once per period; in the running one the viewer only on a few."""
    period = periods.open_period(group.id)
    if period is None or period.id in voted:
        return
    voted.add(period.id)
    running = period.closes_at > now
    members = [m.user for m in membership.active_members(group.id)]
    for voter in members:
        targets = [t for t in members if t.id != voter.id and rng.random() < 0.7]
        if voter.id == viewer.id and running:
            targets = targets[:2]
        for target in targets:
            vote(group, voter, target, "up" if rng.random() < strength[target.id] else "down")
            if not period.is_anonymous and rng.random() < 0.15:
                voting.set_reason(group, voter, target.id, rng.choice(REASONS))


def _summary(db_path: Path, viewer: User) -> str:
    url = f"sqlite:///{db_path}"
    return "\n".join(
        (
            f"Demo-Daten in {db_path}",
            "",
            f"  DATABASE_URL={url} flask --app app run --debug",
            f"  DATABASE_URL={url} flask --app app tick   # Perioden weiterschalten",
            "",
            f"Anmelden als {viewer.email} (oder felix@, lena@, mara@ … example.org),",
            "der Link steht im Terminal des Servers.",
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
