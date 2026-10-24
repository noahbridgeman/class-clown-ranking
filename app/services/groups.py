"""Creating, leaving and deleting groups, moving the admin role (GRP-01…04, ROL-01…03, A5)."""

from datetime import datetime, timedelta
from enum import StrEnum

from flask import current_app
from sqlalchemy import delete, func, select

from app.clock import get_clock
from app.domain.scoring import default_params
from app.domain.types import Cadence
from app.extensions import db
from app.models import Group, Membership, User
from app.models.group import GROUP_NAME_MAX_LENGTH
from app.services import membership, notifications
from app.services.errors import InvalidInput
from app.services.locks import lock_group
from app.services.text import clean_name

# Defaults from section 5 of the requirements (GRP-02).
DEFAULT_CADENCE = Cadence.WEEKLY
DEFAULT_ANONYMOUS = True
DEFAULT_TIMEZONE = "Europe/Berlin"
CREATION_WINDOW = timedelta(days=1)


class LeaveResult(StrEnum):
    LEFT = "left"
    GROUP_DELETED = "group_deleted"


def create_group(user: User, raw_name: str) -> Group:
    """GRP-01: the creator becomes the admin and first member."""
    now = get_clock().now()
    name = clean_name(raw_name, GROUP_NAME_MAX_LENGTH)
    _check_creation_limit(user, now)
    params = default_params(DEFAULT_CADENCE)
    group = Group(
        name=name,
        admin_user_id=user.id,
        created_by_user_id=user.id,
        cadence=DEFAULT_CADENCE,
        is_anonymous=DEFAULT_ANONYMOUS,
        timezone=DEFAULT_TIMEZONE,
        k=params.k,
        d=params.d,
        created_at=now,
    )
    db.session.add(group)
    db.session.flush()
    membership.join(group, user, now)
    db.session.commit()
    return group


def _check_creation_limit(user: User, now: datetime) -> None:
    """A16: each group can send invitations, so new groups per person are limited too."""
    recent = db.session.scalar(
        select(func.count())
        .select_from(Group)
        .where(Group.created_by_user_id == user.id, Group.created_at > now - CREATION_WINDOW)
    )
    if recent >= current_app.config["GROUPS_PER_USER_PER_DAY"]:
        raise InvalidInput("groups.rate_limited")


def groups_of(user: User) -> list[Group]:
    """GRP-03: all groups the user is an active member of, by name."""
    return list(
        db.session.scalars(
            select(Group)
            .join(Membership, Membership.group_id == Group.id)
            .where(Membership.user_id == user.id, Membership.left_at.is_(None))
            .order_by(Group.name, Group.id)
        )
    )


def get_group(group_id: int) -> Group | None:
    return db.session.get(Group, group_id)


def transfer_admin(group: Group, actor: User, user_id: int) -> None:
    """ROL-02: the admin hands the role to another active member."""
    lock_group(group)
    membership.require_admin(group, actor)
    if user_id == actor.id:
        raise InvalidInput("groups.already_admin")
    target = membership.require_active(group.id, user_id)
    membership.make_admin(group, target.user, actor_id=actor.id, now=get_clock().now())
    db.session.commit()
    notifications.admin_granted(target.user, group)


def delete_group(group: Group, actor: User, confirmation: str | None) -> None:
    """GRP-04: removes the group with all its data, confirmed by typing its name."""
    lock_group(group)
    membership.require_admin(group, actor)
    if not confirmation_matches(group, confirmation):
        raise InvalidInput("groups.confirmation_mismatch")
    # The foreign keys cascade to memberships, events and invitations (and later periods).
    db.session.execute(delete(Group).where(Group.id == group.id))
    db.session.commit()


def leave_group(group: Group, user: User, confirmation: str | None = None) -> LeaveResult:
    """MEM-01. The last member can only leave by deleting the group, confirmed by name (A5)."""
    lock_group(group)
    membership.require_active(group.id, user.id)
    if membership.successor(group.id, user.id) is None:
        delete_group(group, user, confirmation)
        return LeaveResult.GROUP_DELETED
    membership.leave(group, user)
    return LeaveResult.LEFT


def confirmation_matches(group: Group, confirmation: str | None) -> bool:
    return " ".join((confirmation or "").split()) == group.name
