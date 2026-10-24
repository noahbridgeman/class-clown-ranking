from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    SmallInteger,
    UniqueConstraint,
    event,
    inspect,
    text,
)
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from app.domain.scoring import ScoreParams
from app.domain.types import Cadence
from app.extensions import db
from app.models.group import GROUP_FK
from app.models.types import UTCDateTime, text_enum


class PeriodStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    SKIPPED = "skipped"  # fewer than 2 active members at closing (PER-06, A2)


# The settings a period copies from its group when it opens (VOT-09, SET-01, SCO-09).
SNAPSHOT_FIELDS = ("group_id", "seq", "opens_at", "closes_at", "cadence", "is_anonymous", "k", "d")


class Period(db.Model):
    """One voting window (E1). Its snapshot is fixed when it opens and never changes."""

    __tablename__ = "periods"
    __table_args__ = (
        UniqueConstraint("group_id", "seq"),
        Index(None, "group_id", "closes_at"),
        # At most one open period per group (PER-02).
        Index(
            "ix_periods_one_open_per_group",
            "group_id",
            unique=True,
            sqlite_where=text("status = 'open'"),
            postgresql_where=text("status = 'open'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", **GROUP_FK))
    seq: Mapped[int]  # 1, 2, … per group
    opens_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # Every vote is checked against this, not against the status (PER-03).
    closes_at: Mapped[datetime] = mapped_column(UTCDateTime)
    cadence: Mapped[Cadence] = mapped_column(text_enum(Cadence, "cadence"))
    is_anonymous: Mapped[bool]
    k: Mapped[float]
    d: Mapped[float]
    status: Mapped[PeriodStatus] = mapped_column(text_enum(PeriodStatus, "status"))
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # when the update ran

    @property
    def params(self) -> ScoreParams:
        return ScoreParams(k=self.k, d=self.d)

    def accepts_votes(self, now: datetime) -> bool:
        return self.status == PeriodStatus.OPEN and self.opens_at <= now < self.closes_at


class Vote(db.Model):
    """Up (+1) or down (−1). Retracting deletes the row (VOT-05).

    The voter is stored even in anonymous periods, because voters see their own votes.
    Only app.services.vote_queries reads votes with their voter (NFA-06).
    """

    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("period_id", "voter_user_id", "target_user_id"),  # VOT-02
        CheckConstraint("voter_user_id <> target_user_id", name="no_self_vote"),  # VOT-03
        CheckConstraint("value IN (-1, 1)", name="value"),
        Index(None, "period_id", "target_user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id", ondelete="CASCADE"))
    voter_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    target_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    value: Mapped[int] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PeriodResult(db.Model):
    """A member's result of one closed period (SCO-06). Inserted once, never changed."""

    __tablename__ = "period_results"
    __table_args__ = (
        UniqueConstraint("period_id", "user_id"),  # PER-02
        Index(None, "user_id", "period_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    ups: Mapped[int]
    downs: Mapped[int]
    net: Mapped[float]
    rating_before: Mapped[float]
    rating_after: Mapped[float]
    score: Mapped[float]


class ImmutableError(RuntimeError):
    """Raised when stored history would be changed (SCO-06, VOT-09)."""


@event.listens_for(PeriodResult, "before_update")
def _results_never_change(_mapper: Mapper[Any], _connection: Any, result: PeriodResult) -> None:
    raise ImmutableError(f"period result {result.id} must not be changed (SCO-06)")


@event.listens_for(Period, "before_update")
def _snapshot_never_changes(_mapper: Mapper[Any], _connection: Any, period: Period) -> None:
    state = inspect(period)
    changed = [name for name in SNAPSHOT_FIELDS if state.attrs[name].history.has_changes()]
    if changed:
        raise ImmutableError(f"period {period.id}: {', '.join(changed)} must not change (VOT-09)")
