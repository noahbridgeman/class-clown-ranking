"""PER-02: the update runs once per period, however often and however parallel it is started."""

import contextlib
import threading
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import pytest
from flask import Flask
from sqlalchemy import func, select
from sqlalchemy.pool import NullPool

from app import create_app
from app.clock import FrozenClock
from app.config import TestConfig
from app.domain.scoring import default_params
from app.domain.types import Cadence
from app.extensions import db
from app.models import Period, PeriodResult, PeriodStatus
from app.services import periods, push, settings, voting
from tests.factories import (
    IN_WEEK_WINDOW,
    WEEK_CLOSES,
    WEEK_OPENS,
    add_member,
    make_daily,
    make_group,
    tick,
    vote,
)
from tests.services.test_push import AUTH, KEY

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
        for n, user in enumerate((group.admin, other)):
            push.subscribe(user, f"https://fcm.googleapis.com/fcm/send/{n}", KEY, AUTH)
    file_app.extensions["clock"].set(WEEK_CLOSES)
    outbox = file_app.extensions["push"].outbox
    outbox.clear()

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
    # NOT-03: the flag is set under the same lock, so each gets the scores once.
    scores = sorted(url for url, m in outbox if m.tag.endswith("-scores"))
    assert scores == [f"https://fcm.googleapis.com/fcm/send/{n}" for n in (0, 1)]


def test_pending_settings_are_taken_over_once(app, clock):
    """PER-02 with pending settings: a second run changes neither the takeover nor the group."""
    group = make_group()
    add_member(group)
    settings.change(group, group.admin, replace(settings.upcoming(group), name="Neu", k=0.8))
    clock.set(WEEK_OPENS)
    tick()
    before = [(c.applied_at, c.applied_in_period_id) for c in settings.log(group.id)]
    clock.set(WEEK_OPENS + timedelta(minutes=1))
    tick()
    assert [(c.applied_at, c.applied_in_period_id) for c in settings.log(group.id)] == before
    assert (group.name, group.k) == ("Neu", 0.8)
    assert counts()[1] == 1


def test_change_stays_pending_while_the_window_overlaps_the_latest_period(app, clock):
    """Daily to weekly: the daily period runs until Sunday 13:00, past the start of the
    weekly window, so that window gets no period and the change waits for next Sunday.
    The voting page says so too, even before tick has closed the daily period (VOT-10)."""
    group = make_daily(make_group())
    add_member(group)
    tick()
    clock.set(datetime(2026, 10, 24, 11, 0, tzinfo=UTC))  # Saturday 13:00 Berlin
    tick()  # daily window until Sunday 13:00
    weekly = default_params(Cadence.WEEKLY)
    wanted = replace(settings.upcoming(group), cadence=Cadence.WEEKLY, k=weekly.k, d=weekly.d)
    settings.change(group, group.admin, wanted)
    next_sunday = datetime(2026, 10, 31, 23, 0, tzinfo=UTC)
    clock.set(datetime(2026, 10, 25, 12, 0, tzinfo=UTC))  # the daily window has just ended
    assert voting.ballot(group, group.admin).next_opens_at == next_sunday
    assert settings.takes_effect_at(group, clock.now()) == next_sunday
    tick()
    tick()
    assert counts() == (0, 2, 4)
    assert group.cadence == Cadence.DAILY
    assert settings.pending_fields(group)
    clock.set(next_sunday)
    tick()
    assert group.cadence == Cadence.WEEKLY
