"""Joining, leaving and removing members (MEM-01, MEM-02, MEM-04, ROL-03, A5)."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.clock import get_clock
from app.extensions import db
from app.models import Group, Membership, MembershipEvent, MembershipEventKind, User
from app.services import notifications
from app.services.errors import InvalidInput, NotAllowed, NotFound


class LeaveResult(StrEnum):
    LEFT = "left"
    GROUP_DELETED = "group_deleted"


def active_membership(group_id: int, user_id: int) -> Membership | None:
    return db.session.scalar(
        select(Membership).where(
            Membership.group_id == group_id,
            Membership.user_id == user_id,
            Membership.left_at.is_(None),
        )
    )


def active_members(group_id: int) -> list[Membership]:
    """Active members, longest-standing first."""
    return list(
        db.session.scalars(
            select(Membership)
            .options(joinedload(Membership.user))
            .where(Membership.group_id == group_id, Membership.left_at.is_(None))
            .order_by(Membership.first_joined_at, Membership.id)
        )
    )


def member_count(group_id: int) -> int:
    return db.session.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.group_id == group_id, Membership.left_at.is_(None))
    )


def join(group: Group, user: User, now: datetime) -> Membership:
    """Adds the user, or reactivates the old membership (MEM-04). Does not commit."""
    membership = db.session.scalar(
        select(Membership).where(Membership.group_id == group.id, Membership.user_id == user.id)
    )
    if membership is None:
        membership = Membership(
            group_id=group.id,
            user_id=user.id,
            first_joined_at=now,
            joined_at=now,
            color_index=_free_color_index(group.id),
        )
        db.session.add(membership)
        _record(group, user.id, MembershipEventKind.JOINED, now, actor_id=user.id)
    elif not membership.is_active:
        membership.joined_at = now
        membership.left_at = None
        _record(group, user.id, MembershipEventKind.REJOINED, now, actor_id=user.id)
    return membership


def leave(group: Group, user: User, confirmation: str | None = None) -> LeaveResult:
    """MEM-01. A leaving admin hands over to the longest-standing member (ROL-03).

    The last member can only leave by deleting the group, confirmed by its name (A5).
    """
    membership = _active_or_not_found(group.id, user.id)
    now = get_clock().now()
    heir = successor(group.id, user.id)
    if heir is None:
        from app.services import groups  # groups imports this module

        groups.delete_group(group, user, confirmation)
        return LeaveResult.GROUP_DELETED
    membership.left_at = now
    _record(group, user.id, MembershipEventKind.LEFT, now, actor_id=user.id)
    new_admin = None
    if group.admin_user_id == user.id:
        make_admin(group, heir.user, actor_id=None, now=now)
        new_admin = heir.user
    db.session.commit()
    if new_admin is not None:
        notifications.admin_granted(new_admin, group)
    return LeaveResult.LEFT


def remove(group: Group, actor: User, user_id: int) -> None:
    """MEM-02. The admin removes someone else; leaving is a separate operation."""
    require_admin(group, actor)
    if user_id == actor.id:
        raise InvalidInput("groups.cannot_remove_self")
    membership = _active_or_not_found(group.id, user_id)
    now = get_clock().now()
    membership.left_at = now
    _record(group, user_id, MembershipEventKind.REMOVED, now, actor_id=actor.id)
    db.session.commit()


def make_admin(group: Group, user: User, actor_id: int | None, now: datetime) -> None:
    """Moves the admin role (ROL-01: there is always exactly one). Does not commit."""
    group.admin_user_id = user.id
    _record(group, user.id, MembershipEventKind.ADMIN_TRANSFERRED, now, actor_id=actor_id)


def require_admin(group: Group, actor: User) -> None:
    if group.admin_user_id != actor.id or active_membership(group.id, actor.id) is None:
        raise NotAllowed


def require_active(group_id: int, user_id: int) -> Membership:
    return _active_or_not_found(group_id, user_id)


def _active_or_not_found(group_id: int, user_id: int) -> Membership:
    membership = active_membership(group_id, user_id)
    if membership is None:
        raise NotFound
    return membership


def successor(group_id: int, leaving_user_id: int) -> Membership | None:
    """ROL-03: the earliest first join wins (A4), ties go to the older membership row."""
    others = [m for m in active_members(group_id) if m.user_id != leaving_user_id]
    return others[0] if others else None


def _free_color_index(group_id: int) -> int:
    """The smallest index no membership row of the group holds. Rows are never deleted."""
    used = set(
        db.session.scalars(select(Membership.color_index).where(Membership.group_id == group_id))
    )
    return next(index for index in range(len(used) + 1) if index not in used)


def _record(
    group: Group, user_id: int, kind: MembershipEventKind, now: datetime, actor_id: int | None
) -> None:
    db.session.add(
        MembershipEvent(
            group_id=group.id, user_id=user_id, kind=kind, occurred_at=now, actor_user_id=actor_id
        )
    )
