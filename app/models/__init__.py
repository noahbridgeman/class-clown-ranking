"""SQLAlchemy models. Import every model module here so Alembic sees it."""

from app.models.auth import AllowedEmail, LoginToken
from app.models.user import User

__all__ = ["AllowedEmail", "LoginToken", "User"]
