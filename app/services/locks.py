"""Serializes concurrent changes to one group's members, admin and invitations."""

from sqlalchemy import update

from app.extensions import db
from app.models import Group
from app.services.errors import NotFound


def lock_group(group: Group) -> None:
    """Locks the group until commit, then reloads everything read so far.

    Call it first, before changing anything in the transaction. A no-op UPDATE takes
    SQLite's write lock and a row lock in Postgres, so two requests that both read the
    member list (e.g. the last two members leaving) cannot interleave (ROL-01, A5).
    """
    result = db.session.execute(
        update(Group)
        .where(Group.id == group.id)
        .values(id=Group.id)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise NotFound  # deleted by a request that held the lock before us
    # Values loaded before the lock may be outdated now.
    db.session.expire_all()
