from datetime import datetime

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.types import UTCDateTime
from app.models.user import EMAIL_MAX_LENGTH


class AllowedEmail(db.Model):
    """Addresses that may create an account without an invitation (E3)."""

    __tablename__ = "allowed_emails"

    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime)


class LoginToken(db.Model):
    """A one-time login link (AUTH-02). Only the hash of the link's nonce is stored."""

    __tablename__ = "login_tokens"
    # The rate limit counts recent tokens per address (NFA-09).
    __table_args__ = (Index(None, "email", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH))
    nonce_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
