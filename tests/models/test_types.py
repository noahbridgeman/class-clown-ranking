from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import StatementError

from app.extensions import db
from app.models import User


def test_timestamps_come_back_as_aware_utc(app):
    berlin = timezone(timedelta(hours=2))
    db.session.add(
        User(email="a@example.org", created_at=datetime(2026, 10, 23, 14, tzinfo=berlin))
    )
    db.session.commit()
    db.session.expire_all()
    user = db.session.query(User).one()
    assert user.created_at == datetime(2026, 10, 23, 12, tzinfo=UTC)
    assert user.created_at.tzinfo is UTC


def test_naive_timestamps_are_rejected(app):
    db.session.add(User(email="a@example.org", created_at=datetime(2026, 10, 23, 12)))
    with pytest.raises(StatementError, match="Naive datetimes"):
        db.session.commit()
    db.session.rollback()


def test_session_id_contains_version(app):
    user = User(id=7, session_version=3)
    assert user.get_id() == "7:3"
