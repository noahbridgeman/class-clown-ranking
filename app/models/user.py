from datetime import datetime

from flask_login import UserMixin
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.types import UTCDateTime

EMAIL_MAX_LENGTH = 254
DISPLAY_NAME_MAX_LENGTH = 40


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Normalized (stripped, lower case). NULL once the account is deleted (NFA-05).
    email: Mapped[str | None] = mapped_column(String(EMAIL_MAX_LENGTH), unique=True)
    # NULL until the first login sets it (AUTH-04).
    display_name: Mapped[str | None] = mapped_column(String(DISPLAY_NAME_MAX_LENGTH))
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Part of the session id, so increasing it ends every session of this user.
    session_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    def get_id(self) -> str:
        return f"{self.id}:{self.session_version}"

    @property
    def is_active(self) -> bool:
        return self.deleted_at is None

    @property
    def needs_display_name(self) -> bool:
        return self.display_name is None
