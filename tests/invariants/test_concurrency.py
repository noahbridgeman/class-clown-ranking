"""Concurrent requests must not break ROL-01 or A5 (lock_group).

Uses a file database with one connection per thread, unlike the shared in-memory one.
"""

import contextlib
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest
from flask import Flask
from sqlalchemy.pool import NullPool

from app import create_app
from app.clock import FrozenClock
from app.config import TestConfig
from app.extensions import db
from app.models import Group, User
from app.services import groups, membership
from tests.factories import add_member, make_group, make_user

# How long the first thread waits for the second to read the same state.
RACE_WINDOW_SECONDS = 0.5


@pytest.fixture
def file_app(tmp_path: Path) -> Iterator[Flask]:
    class FileDb(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'race.db'}"
        SQLALCHEMY_ENGINE_OPTIONS: ClassVar = {
            "poolclass": NullPool,
            "connect_args": {"timeout": 10},
        }

    app = create_app(FileDb, clock=FrozenClock(datetime(2026, 10, 24, 12, tzinfo=UTC)))
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.engine.dispose()


def race(app: Flask, monkeypatch: pytest.MonkeyPatch, *actions: Callable[[], None]) -> list:
    """Runs the actions in parallel threads, each pausing right after reading the members."""
    barrier = threading.Barrier(len(actions))
    original = membership.successor

    def successor_then_wait(group_id: int, user_id: int) -> object:
        result = original(group_id, user_id)
        # A broken barrier means the other thread is blocked by the lock, as it should be.
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait(timeout=RACE_WINDOW_SECONDS)
        return result

    monkeypatch.setattr(membership, "successor", successor_then_wait)
    outcomes: list = [None] * len(actions)

    def run(index: int, action: Callable[[], None]) -> None:
        with app.app_context():
            try:
                outcomes[index] = action()
            except Exception as error:  # collected and asserted by the test
                outcomes[index] = error

    threads = [threading.Thread(target=run, args=pair) for pair in enumerate(actions)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    return outcomes


def leave(group_id: int, user_id: int) -> Callable[[], object]:
    return lambda: groups.leave_group(
        db.session.get(Group, group_id), db.session.get(User, user_id)
    )


def test_last_two_members_leaving_at_once_keep_one_admin(file_app, monkeypatch):
    with file_app.app_context():
        admin = make_user()
        group = make_group(admin)
        other = add_member(group)
        ids = group.id, admin.id, other.id
    group_id, admin_id, other_id = ids

    outcomes = race(file_app, monkeypatch, leave(group_id, admin_id), leave(group_id, other_id))

    left = [o for o in outcomes if o is groups.LeaveResult.LEFT]
    refused = [
        o for o in outcomes if getattr(o, "message_key", None) == "groups.confirmation_mismatch"
    ]
    assert (len(left), len(refused)) == (1, 1), outcomes
    with file_app.app_context():
        group = db.session.get(Group, group_id)
        active = membership.active_members(group_id)
        assert [m.user_id for m in active] == [group.admin_user_id]


def test_transfer_and_leave_of_the_heir_at_once_keep_an_active_admin(file_app, monkeypatch):
    with file_app.app_context():
        admin = make_user()
        group = make_group(admin)
        heir = add_member(group)
        add_member(group)
        group_id, admin_id, heir_id = group.id, admin.id, heir.id

    def transfer() -> None:
        groups.transfer_admin(
            db.session.get(Group, group_id), db.session.get(User, admin_id), heir_id
        )

    race(file_app, monkeypatch, transfer, leave(group_id, heir_id))

    with file_app.app_context():
        group = db.session.get(Group, group_id)
        assert membership.active_membership(group_id, group.admin_user_id) is not None
