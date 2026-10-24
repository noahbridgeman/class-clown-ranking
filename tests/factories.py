"""Small helpers to create rows directly, bypassing services."""

from datetime import UTC, datetime
from itertools import count

from app.clock import get_clock
from app.domain.scoring import default_params
from app.domain.types import Cadence
from app.extensions import db
from app.models import AllowedEmail, Group, User
from app.services import groups, membership, periods, voting

# The weekly window after the conftest clock (Fri 23.10.2026): Sunday 00:00 CEST to
# Monday 13:00 CET, across the end of daylight saving time.
WEEK_OPENS = datetime(2026, 10, 24, 22, 0, tzinfo=UTC)
WEEK_CLOSES = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
IN_WEEK_WINDOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)

_numbers = count(1)


def make_user(email: str | None = None, display_name: str | None = "Testperson") -> User:
    now = get_clock().now()
    user = User(
        email=email or f"person{next(_numbers)}@example.org",
        display_name=display_name,
        email_verified_at=now,
        created_at=now,
    )
    db.session.add(user)
    db.session.commit()
    return user


def allow(email: str) -> None:
    db.session.add(AllowedEmail(email=email, added_at=get_clock().now()))
    db.session.commit()


def make_group(admin: User | None = None, name: str = "Spaßvögel") -> Group:
    return groups.create_group(admin or make_user(), name)


def add_member(group: Group, user: User | None = None) -> User:
    """Joins directly, as if an invitation had been accepted."""
    user = user or make_user()
    membership.join(group, user, get_clock().now())
    db.session.commit()
    return user


def make_daily(group: Group) -> Group:
    """Switches the effective settings directly; the settings flow follows in M6."""
    params = default_params(Cadence.DAILY)
    group.cadence, group.k, group.d = Cadence.DAILY, params.k, params.d
    db.session.commit()
    return group


def tick() -> periods.TickReport:
    return periods.tick()


def vote(group: Group, voter: User, target: User, choice: str = "up") -> None:
    voting.set_vote(group, voter, target.id, voting.Choice(choice))
