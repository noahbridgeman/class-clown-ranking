"""Errors that services raise and the web layer turns into responses."""

from app.i18n import t


class InvalidInput(ValueError):
    """The request cannot be carried out. Carries the translation key of the message."""

    def __init__(self, message_key: str, **params: object) -> None:
        super().__init__(message_key)
        self.message_key = message_key
        self.params = params

    def message(self) -> str:
        return t(self.message_key, **self.params)


class NotFound(LookupError):
    """The object does not exist in this group. Answered with 404 (A10)."""


class NotAllowed(PermissionError):
    """The actor lacks the role for this operation (NFA-07)."""
