from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Timestamps are always stored and returned as timezone-aware UTC.

    SQLite has no timezone support and returns naive values, so they are marked as UTC
    on the way out. Naive values on the way in are rejected rather than guessed.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed, use clock.now()")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def text_enum(enum: type[StrEnum], name: str) -> Enum:
    """Stores the enum's values as text, guarded by a CHECK constraint."""
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=max(len(member.value) for member in enum),
        values_callable=lambda members: [member.value for member in members],
    )
