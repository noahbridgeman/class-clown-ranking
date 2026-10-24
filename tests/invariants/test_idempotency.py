"""PER-02: the update runs once per period, however often and however parallel it is started."""

import contextlib
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest
from flask import Flask
from sqlalchemy import func, select
from sqlalchemy.pool import NullPool

from app import create_app
from app.clock import FrozenClock
from app.config import TestConfig
from app.extensions import db
from app.models import Period, PeriodResult, PeriodStatus
from app.services import periods
from tests.factories import IN_WEEK_WINDOW, WEEK_CLOSES, add_member, make_group, tick, vote

RACE_WINDOW_SECONDS = 0.5


def counts() -> tuple[int, int, int]:
    def count(*where):
        return db.session.scalar(select(func.count()).select_from(Period).where(*where))

    results = db.session.scalar(select(func.count()).select_from(PeriodResult))
    return count(Period.status == PeriodStatus.OPEN), count(), results


def test_running_twice_changes_nothing(app, clock):
    group = make_group()
    other = add_member(group)
    clock.set(IN_WEEK_WINDOW)
    tick()
    vote(group, group.admin, other, "up")
    clock.set(WEEK_CLOSES)
    first = tick()
    after_first = counts()
    second = tick()
    assert (first.closed, second.closed, second.opened) == (1, 0, 0)
    assert counts() == after_first == (0, 1, 2)


@pytest.fixture
def file_app(tmp_path: Path) -> Iterator[Flask]:
    class FileDb(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'tick.db'}"
        SQLALCHEMY_ENGINE_OPTIONS: ClassVar = {
            "poolclass": NullPool,
            "connect_args": {"timeout": 10},
        }

    app = create_app(FileDb, clock=FrozenClock(IN_WEEK_WINDOW))
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.engine.dispose()


def test_parallel_runs_compute_once(file_app, monkeypatch):
    """Both runs read the open period at the same moment; the group lock serializes them."""
    with file_app.app_context():
        group = make_group()
        other = add_member(group)
        tick()
        vote(group, group.admin, other, "up")
    file_app.extensions["clock"].set(WEEK_CLOSES)

    barrier = threading.Barrier(2)
    original = periods.open_period

    def open_period_then_wait(group_id: int) -> object:
        result = original(group_id)
        # A broken barrier means the other run is blocked by the lock, as it should be.
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait(timeout=RACE_WINDOW_SECONDS)
        return result

    monkeypatch.setattr(periods, "open_period", open_period_then_wait)
    reports: list = [None, None]

    def run(index: int) -> None:
        with file_app.app_context():
            reports[index] = periods.tick()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert all(report.failed == [] for report in reports), reports
    assert sum(report.closed for report in reports) == 1
    with file_app.app_context():
        assert counts() == (0, 1, 2)
