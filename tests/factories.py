"""Small helpers to create rows directly, bypassing services."""

from itertools import count

from app.clock import get_clock
from app.extensions import db
from app.models import AllowedEmail, User

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
