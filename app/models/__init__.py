"""SQLAlchemy models. Import every model module here so Alembic sees it."""

from app.models.auth import AllowedEmail, LoginToken
from app.models.group import (
    Group,
    Invitation,
    InvitationStatus,
    Membership,
    MembershipEvent,
    MembershipEventKind,
    SettingField,
    SettingsChange,
)
from app.models.period import (
    ImmutableError,
    Period,
    PeriodResult,
    PeriodStatus,
    Vote,
)
from app.models.push import NotificationKind, NotificationPreference, PushSubscription
from app.models.user import User

__all__ = [
    "AllowedEmail",
    "Group",
    "ImmutableError",
    "Invitation",
    "InvitationStatus",
    "LoginToken",
    "Membership",
    "MembershipEvent",
    "MembershipEventKind",
    "NotificationKind",
    "NotificationPreference",
    "Period",
    "PeriodResult",
    "PeriodStatus",
    "PushSubscription",
    "SettingField",
    "SettingsChange",
    "User",
    "Vote",
]
