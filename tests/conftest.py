import contextvars
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.clock import FrozenClock
from app.config import TestConfig
from app.extensions import db
from app.models import User
from app.services.mail import Mail


class IsolatedClient(FlaskClient):
    """Runs every request in its own app context, as in production.

    Flask reuses an already pushed app context for requests, so without this the test's
    context would leak g (and with it the cached current_user) and the db session
    from one request into the next.

    Limits: the in-memory database uses one shared connection (StaticPool), so test and
    request share a transaction. Commit test data before a request, since a rollback in
    the request would discard it. ``with client:`` does not work, because its contexts
    would be opened and closed in different contextvars contexts. Tests of real
    concurrency (M4: parallel tick runs) need a file database with NullPool.
    """

    def open(self, *args: Any, **kwargs: Any) -> Any:
        return contextvars.Context().run(super().open, *args, **kwargs)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 10, 23, 12, 0, tzinfo=UTC))


@pytest.fixture
def app(clock: FrozenClock) -> Iterator[Flask]:
    app = create_app(TestConfig, clock=clock)
    app.test_client_class = IsolatedClient
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def outbox(app: Flask) -> list[Mail]:
    return app.extensions["mail"].outbox


@pytest.fixture
def login_as(client: FlaskClient) -> Callable[[User], FlaskClient]:
    """Logs the test client in without going through the mail flow."""

    def login(user: User) -> FlaskClient:
        with client.session_transaction() as session:
            session["_user_id"] = user.get_id()
            session["_fresh"] = True
        return client

    return login


@pytest.fixture
def csrf_app() -> Iterator[Flask]:
    """An app with CSRF protection on; TestConfig switches it off for the other tests."""

    class WithCsrf(TestConfig):
        WTF_CSRF_ENABLED = True

    app = create_app(WithCsrf, clock=FrozenClock(datetime(2026, 10, 23, 12, tzinfo=UTC)))
    app.test_client_class = IsolatedClient
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
