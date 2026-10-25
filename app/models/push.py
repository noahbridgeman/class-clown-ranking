from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.group import GROUP_FK
from app.models.types import UTCDateTime, text_enum

# Push services hand out endpoints of a few hundred characters; keys are base64url.
ENDPOINT_MAX_LENGTH = 1024
KEY_MAX_LENGTH = 256


class NotificationKind(StrEnum):
    """The push occasions of section 11 (A24), each switchable per group (NOT-02)."""

    WINDOW_OPEN = "window_open"
    REMINDER = "reminder"
    SCORES_PUBLISHED = "scores_published"
    OVERTAKEN = "overtaken"
    SETTINGS_CHANGED = "settings_changed"
    ADMIN_GRANTED = "admin_granted"


class PushSubscription(db.Model):
    """One browser on one device (NFA-04). Removed when the push service reports it gone."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(ENDPOINT_MAX_LENGTH), unique=True)
    p256dh: Mapped[str] = mapped_column(String(KEY_MAX_LENGTH))
    auth: Mapped[str] = mapped_column(String(KEY_MAX_LENGTH))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class NotificationPreference(db.Model):
    """An occasion switched on or off for one group (NOT-02). Without a row it is on."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", **GROUP_FK), primary_key=True)
    kind: Mapped[NotificationKind] = mapped_column(
        text_enum(NotificationKind, "kind"), primary_key=True
    )
    enabled: Mapped[bool]
