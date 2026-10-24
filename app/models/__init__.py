"""SQLAlchemy models. Import every model module here so Alembic sees it."""

from app.models.auth import AllowedEmail, LoginToken
from app.models.group import (
    Group,
    Invitation,
    InvitationStatus,
    Membership,
    MembershipEvent,
    MembershipEventKind,
)
from app.models.period import (
    ImmutableError,
    Period,
    PeriodResult,
    PeriodStatus,
    Vote,
)
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
    "Period",
    "PeriodResult",
    "PeriodStatus",
    "User",
    "Vote",
]
