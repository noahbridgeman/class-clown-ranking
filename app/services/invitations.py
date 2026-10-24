"""Invitations: sending, resending, revoking and accepting them (INV-01…05, NFA-09, A8)."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import func, select, update

from app.clock import get_clock
from app.extensions import db
from app.models import Group, Invitation, InvitationStatus, Membership, User
from app.services import auth, membership, notifications, tokens
from app.services.errors import InvalidInput, NotFound

TOKEN_SALT = "invitation"
RATE_LIMIT_WINDOW = timedelta(days=1)


class WrongAccount(Exception):
    """INV-02: the link was opened while logged in with another address."""


@dataclass(frozen=True)
class Sent:
    invitation: Invitation
    mail_sent: bool


@dataclass(frozen=True)
class Accepted:
    user: User
    group: Group


def invitations_of(group: Group) -> list[Invitation]:
    """INV-05: every invitation of the group, newest first."""
    return list(
        db.session.scalars(
            select(Invitation)
            .where(Invitation.group_id == group.id)
            .order_by(Invitation.created_at.desc(), Invitation.id.desc())
        )
    )


def invite(group: Group, actor: User, raw_email: str) -> Sent:
    """INV-01. An expired invitation to the same address is sent again instead."""
    membership.require_admin(group, actor)
    email = auth.normalize_email(raw_email)
    now = get_clock().now()
    if _is_active_member(group, email):
        raise InvalidInput("invitations.already_member")
    existing = _latest_pending(group, email)
    if existing is not None:
        if existing.status(now) is InvitationStatus.OPEN:
            raise InvalidInput("invitations.already_invited")
        return _send_again(group, existing, now)
    _check_room(group, now)
    _check_new_invitation_limits(group, email, now)
    nonce = tokens.new_nonce()
    invitation = Invitation(
        group_id=group.id,
        email=email,
        invited_by_user_id=actor.id,
        nonce_hash=tokens.hash_nonce(nonce),
        created_at=now,
        last_sent_at=now,
        expires_at=now + _lifetime(),
        send_count=1,
    )
    db.session.add(invitation)
    db.session.commit()
    return Sent(invitation, notifications.invitation(invitation, link(nonce)))


def resend(group: Group, actor: User, invitation_id: int) -> Sent:
    """INV-04: a new link replaces the old one, valid for the full lifetime again."""
    membership.require_admin(group, actor)
    invitation = _pending_or_not_found(group, invitation_id)
    return _send_again(group, invitation, get_clock().now())


def revoke(group: Group, actor: User, invitation_id: int) -> None:
    """INV-04: the link stops working at once."""
    membership.require_admin(group, actor)
    invitation = _pending_or_not_found(group, invitation_id)
    invitation.revoked_at = get_clock().now()
    db.session.commit()


def find_open(link_token: str) -> Invitation | None:
    """The invitation behind a link, if it can still be accepted."""
    nonce = tokens.unsign(link_token, TOKEN_SALT)
    if nonce is None:
        return None
    invitation = db.session.scalar(
        select(Invitation).where(Invitation.nonce_hash == tokens.hash_nonce(nonce))
    )
    if invitation is None or invitation.status(get_clock().now()) is not InvitationStatus.OPEN:
        return None
    return invitation


def accept(link_token: str, current: User | None) -> Accepted | None:
    """Joins the group. The link also logs in, creating the account if needed (INV-03).

    Returns None for an unknown, expired, revoked or used link. Raises WrongAccount if
    someone else is logged in (INV-02).
    """
    invitation = find_open(link_token)
    if invitation is None:
        return None
    if current is not None and current.email != invitation.email:
        raise WrongAccount
    now = get_clock().now()
    if not _claim(invitation, now):
        return None
    user = current or auth.account_with_email(invitation.email, now)
    auth.mark_verified(user, now)
    invitation.accepted_by_user_id = user.id
    group = invitation.group
    membership.join(group, user, now)
    db.session.commit()
    return Accepted(user, group)


def link(nonce: str) -> str:
    return f"{current_app.config['BASE_URL']}/invite/{tokens.sign(nonce, TOKEN_SALT)}"


def _claim(invitation: Invitation, now: datetime) -> bool:
    """Marks it accepted. The conditional UPDATE lets only one of two racing requests win."""
    result = db.session.execute(
        update(Invitation)
        .where(
            Invitation.id == invitation.id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > now,
        )
        .values(accepted_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return False
    invitation.accepted_at = now
    return True


def _send_again(group: Group, invitation: Invitation, now: datetime) -> Sent:
    config = current_app.config
    if invitation.send_count >= config["INVITATION_MAX_SENDS"]:
        raise InvalidInput("invitations.rate_limited")
    if now - invitation.last_sent_at < config["INVITATION_RESEND_INTERVAL"]:
        raise InvalidInput("invitations.resend_too_soon")
    if invitation.status(now) is InvitationStatus.EXPIRED:
        # Expired invitations do not count towards the size limit, so it is checked again.
        _check_room(group, now)
    nonce = tokens.new_nonce()
    invitation.nonce_hash = tokens.hash_nonce(nonce)
    invitation.last_sent_at = now
    invitation.expires_at = now + _lifetime()
    invitation.send_count += 1
    db.session.commit()
    return Sent(invitation, notifications.invitation(invitation, link(nonce)))


def _check_room(group: Group, now: datetime) -> None:
    """A8: members and open invitations together stay within the maximum group size."""
    taken = membership.member_count(group.id) + _open_count(group, now)
    if taken >= current_app.config["MAX_GROUP_SIZE"]:
        raise InvalidInput("invitations.group_full", max=current_app.config["MAX_GROUP_SIZE"])


def _check_new_invitation_limits(group: Group, email: str, now: datetime) -> None:
    """NFA-09: revoking and inviting again must not turn into a way to spam an address."""
    since = now - RATE_LIMIT_WINDOW
    per_group = _count(Invitation.group_id == group.id, Invitation.created_at > since)
    per_address = _count(Invitation.email == email, Invitation.created_at > since)
    config = current_app.config
    if (
        per_group >= config["INVITATIONS_PER_GROUP_PER_DAY"]
        or per_address >= config["INVITATIONS_PER_ADDRESS_PER_DAY"]
    ):
        raise InvalidInput("invitations.rate_limited")


def _open_count(group: Group, now: datetime) -> int:
    return _count(
        Invitation.group_id == group.id,
        Invitation.accepted_at.is_(None),
        Invitation.revoked_at.is_(None),
        Invitation.expires_at > now,
    )


def _count(*conditions: object) -> int:
    return db.session.scalar(select(func.count()).select_from(Invitation).where(*conditions))


def _latest_pending(group: Group, email: str) -> Invitation | None:
    """The open or expired invitation to this address; there is at most one."""
    return db.session.scalar(
        select(Invitation)
        .where(
            Invitation.group_id == group.id,
            Invitation.email == email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .order_by(Invitation.created_at.desc())
    )


def _pending_or_not_found(group: Group, invitation_id: int) -> Invitation:
    """Only invitations of this group, so ids from other groups look like missing ones."""
    invitation = db.session.get(Invitation, invitation_id)
    if invitation is None or invitation.group_id != group.id:
        raise NotFound
    if invitation.status(get_clock().now()) not in (
        InvitationStatus.OPEN,
        InvitationStatus.EXPIRED,
    ):
        raise InvalidInput("invitations.not_pending")
    return invitation


def _is_active_member(group: Group, email: str) -> bool:
    return (
        db.session.scalar(
            select(Membership.id)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.group_id == group.id,
                Membership.left_at.is_(None),
                User.email == email,
                User.deleted_at.is_(None),
            )
        )
        is not None
    )


def _lifetime() -> timedelta:
    return current_app.config["INVITATION_LIFETIME"]
