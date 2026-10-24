from datetime import datetime
from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.types import Cadence
from app.extensions import db
from app.models.types import UTCDateTime
from app.models.user import EMAIL_MAX_LENGTH, User

GROUP_NAME_MAX_LENGTH = 60
TIMEZONE_MAX_LENGTH = 64

# Deleting a group removes everything that belongs to it (GRP-04).
GROUP_FK = {"ondelete": "CASCADE"}


def _enum(enum: type[StrEnum], name: str) -> Enum:
    """Stores the enum's values as text, guarded by a CHECK constraint."""
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=max(len(member.value) for member in enum),
        values_callable=lambda members: [member.value for member in members],
    )


class Group(db.Model):
    __tablename__ = "groups"
    __table_args__ = (Index(None, "created_by_user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # All settings columns hold the effective values (SET-01 and A6 from M6 on).
    name: Mapped[str] = mapped_column(String(GROUP_NAME_MAX_LENGTH))
    # Exactly one admin, enforced by the column itself (ROL-01).
    admin_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # Never changes, unlike the admin; limits new groups per person (A16).
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    cadence: Mapped[Cadence] = mapped_column(_enum(Cadence, "cadence"))
    is_anonymous: Mapped[bool]
    timezone: Mapped[str] = mapped_column(String(TIMEZONE_MAX_LENGTH))
    k: Mapped[float]
    d: Mapped[float]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)

    admin: Mapped[User] = relationship(foreign_keys=[admin_user_id])


class Membership(db.Model):
    """One row per person and group. Rejoining reactivates it, so color and history stay."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id"),
        UniqueConstraint("group_id", "color_index"),
        Index(None, "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", **GROUP_FK))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    first_joined_at: Mapped[datetime] = mapped_column(UTCDateTime)  # ROL-03 (A4)
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime)
    left_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # NULL = active
    color_index: Mapped[int]  # GRA-02, assigned once and never reused

    user: Mapped[User] = relationship()

    @property
    def is_active(self) -> bool:
        return self.left_at is None


class MembershipEventKind(StrEnum):
    JOINED = "joined"
    REJOINED = "rejoined"
    LEFT = "left"
    REMOVED = "removed"
    ADMIN_TRANSFERRED = "admin_transferred"


class MembershipEvent(db.Model):
    """Joins, departures and admin changes, for graph markers (MEM-03, GRA-07)."""

    __tablename__ = "membership_events"
    __table_args__ = (Index(None, "group_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", **GROUP_FK))
    # The member who joined or left, or the new admin.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[MembershipEventKind] = mapped_column(_enum(MembershipEventKind, "kind"))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # NULL for automatic changes such as ROL-03.
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class InvitationStatus(StrEnum):
    OPEN = "open"
    EXPIRED = "expired"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


class Invitation(db.Model):
    """An invitation to one address (INV-01). Its status is derived from the timestamps."""

    __tablename__ = "invitations"
    __table_args__ = (Index(None, "group_id", "email"), Index(None, "email", "created_at"))

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", **GROUP_FK))
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH))
    invited_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # Resending creates a new nonce, so the previous link stops working.
    nonce_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_sent_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    send_count: Mapped[int] = mapped_column(default=1)
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    accepted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    group: Mapped[Group] = relationship()
    invited_by: Mapped[User] = relationship(foreign_keys=[invited_by_user_id])

    def status(self, now: datetime) -> InvitationStatus:
        if self.revoked_at is not None:
            return InvitationStatus.REVOKED
        if self.accepted_at is not None:
            return InvitationStatus.ACCEPTED
        if now >= self.expires_at:
            return InvitationStatus.EXPIRED
        return InvitationStatus.OPEN
