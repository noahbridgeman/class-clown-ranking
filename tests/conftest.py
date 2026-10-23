from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.clock import FrozenClock
from app.config import TestConfig
from app.extensions import db


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 10, 23, 12, 0, tzinfo=UTC))


@pytest.fixture
def app(clock: FrozenClock) -> Iterator[Flask]:
    app = create_app(TestConfig, clock=clock)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()
