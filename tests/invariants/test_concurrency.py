"""Concurrent requests must not break ROL-01 or A5 (lock_group).

Uses a file database with one connection per thread, unlike the shared in-memory one.
"""

import contextlib
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
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
from app.services import groups, membership, periods, push, settings
from tests.factories import WEEK_CLOSES, WEEK_OPENS, add_member, make_group, make_user
from tests.services.test_push import AUTH, KEY

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


def race(
    app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    *actions: Callable[[], object],
    pause_after: tuple[object, str] = (membership, "successor"),
) -> list:
    """Runs the actions in parallel threads, each pausing right after the given read
    (by default reading the members)."""
    barrier = threading.Barrier(len(actions))
    module, name = pause_after
    original = getattr(module, name)

    def read_then_wait(*args: object, **kwargs: object) -> object:
        result = original(*args, **kwargs)
        # A broken barrier means the other thread is blocked by the lock, as it should be.
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait(timeout=RACE_WINDOW_SECONDS)
        return result

    monkeypatch.setattr(module, name, read_then_wait)
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


def test_settings_change_racing_the_window_opening_is_all_or_nothing(file_app, monkeypatch):
    """SET-01: a change saved while tick opens the window lands either completely in the
    new period's snapshot or completely in the next one, never half."""
    with file_app.app_context():
        file_app.extensions["clock"].set(WEEK_OPENS)
        admin = make_user()
        group = make_group(admin)
        add_member(group)
        group_id, admin_id = group.id, admin.id

    def change() -> object:
        group = db.session.get(Group, group_id)
        wanted = replace(settings.upcoming(group), is_anonymous=False, k=0.8, name="Neu")
        return settings.change(group, db.session.get(User, admin_id), wanted)

    outcomes = race(file_app, monkeypatch, change, periods.tick, pause_after=(settings, "upcoming"))

    assert not [o for o in outcomes if isinstance(o, Exception)], outcomes
    with file_app.app_context():
        group = db.session.get(Group, group_id)
        period = periods.open_period(group_id)
        log = settings.log(group_id)
        snapshot = (period.is_anonymous, period.k)
        assert snapshot in {(True, 0.5), (False, 0.8)}
        applied = snapshot == (False, 0.8)
        assert {c.applied_in_period_id for c in log} == {period.id if applied else None}
        assert group.name == ("Neu" if applied else group.name)


def test_a_leave_racing_tick_announces_the_scores_once(file_app, monkeypatch):
    """NOT-03, plan section 5: a leave after the window's end closes the period itself;
    whichever comes first, the scores go out exactly once."""
    with file_app.app_context():
        clock = file_app.extensions["clock"]
        clock.set(WEEK_OPENS)
        admin = make_user()
        group = make_group(admin)
        stays, leaves = add_member(group), add_member(group)
        periods.tick()
        for n, user in enumerate((admin, stays)):
            push.subscribe(user, f"https://fcm.googleapis.com/fcm/send/{n}", KEY, AUTH)
        group_id, leaving_id = group.id, leaves.id
        clock.set(WEEK_CLOSES)
    outbox = file_app.extensions["push"].outbox
    outbox.clear()

    def leave_now() -> object:
        group = db.session.get(Group, group_id)
        return membership.leave(group, db.session.get(User, leaving_id))

    outcomes = race(
        file_app, monkeypatch, leave_now, periods.tick, pause_after=(periods, "open_period")
    )
    assert not [o for o in outcomes if isinstance(o, Exception)], outcomes
    with file_app.app_context():
        periods.tick()  # announces a period the leave closed
        periods.tick()
    scores = sorted(url for url, m in outbox if m.tag.endswith("-scores"))
    assert scores == [f"https://fcm.googleapis.com/fcm/send/{n}" for n in (0, 1)]
