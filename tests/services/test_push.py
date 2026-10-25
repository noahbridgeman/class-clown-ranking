"""Subscriptions, preferences and delivery of pushes (NOT-01, NOT-02, A24)."""

import base64
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import NotificationKind, PushSubscription
from app.services import push
from app.services.errors import InvalidInput
from app.services.push import Delivery, Push
from tests.factories import make_group, make_user

KEY = "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM"
AUTH = "tBHItJI5svbpez7KI4CCXg"


def endpoint(n: int = 1) -> str:
    return f"https://fcm.googleapis.com/fcm/send/device-{n}"


def subscribe(user, n: int = 1) -> None:
    push.subscribe(user, endpoint(n), KEY, AUTH)


def subscriptions() -> list[PushSubscription]:
    return list(db.session.scalars(select(PushSubscription).order_by(PushSubscription.id)))


@pytest.fixture
def outbox(app):
    return app.extensions["push"].outbox


def delivery(user, group, kind=NotificationKind.WINDOW_OPEN) -> Delivery:
    return Delivery(user.id, group.id, kind, Push("Runde", "Hallo", f"/g/{group.id}/", "t"))


class TestSubscribe:
    def test_stores_and_updates_by_endpoint(self, app):
        user = make_user()
        subscribe(user)
        subscribe(user)
        assert [(s.user_id, s.endpoint) for s in subscriptions()] == [(user.id, endpoint())]

    def test_an_endpoint_moves_to_the_account_now_using_the_device(self, app):
        first, second = make_user(), make_user()
        subscribe(first)
        subscribe(second)
        assert [s.user_id for s in subscriptions()] == [second.id]

    @pytest.mark.parametrize(
        "url",
        [
            "http://fcm.googleapis.com/fcm/send/x",  # not https
            "https://localhost/push",  # no push service (SSRF)
            "https://169.254.169.254/latest",
            "https://evilfcm.googleapis.com.example.org/x",
            "https://example.org/?fcm.googleapis.com",
            "https://fcm.googleapis.com/" + "x" * 1100,
        ],
    )
    def test_only_known_push_services(self, app, url):
        with pytest.raises(InvalidInput):
            push.subscribe(make_user(), url, KEY, AUTH)
        assert subscriptions() == []

    def test_known_services_and_their_subdomains(self, app):
        user = make_user()
        for url in (
            "https://updates.push.services.mozilla.com/wpush/v2/x",
            "https://web.push.apple.com/abc",
            "https://wns2-db5p.notify.windows.com/w/?token=x",
        ):
            push.subscribe(user, url, KEY, AUTH)
        assert len(subscriptions()) == 3

    @pytest.mark.parametrize("key", ["", "kein base64!", "a" * 300])
    def test_keys_are_checked(self, app, key):
        with pytest.raises(InvalidInput):
            push.subscribe(make_user(), endpoint(), key, AUTH)

    def test_keeps_the_newest_per_account(self, app, clock):
        user = make_user()
        limit = app.config["PUSH_SUBSCRIPTIONS_PER_USER"]
        for n in range(limit + 2):
            clock.advance(timedelta(minutes=1))
            subscribe(user, n)
        kept = {s.endpoint for s in subscriptions()}
        assert len(kept) == limit and endpoint(0) not in kept and endpoint(limit + 1) in kept

    def test_unsubscribe_only_own(self, app):
        owner, other = make_user(), make_user()
        subscribe(owner)
        push.unsubscribe(other, endpoint())
        assert len(subscriptions()) == 1
        push.unsubscribe(owner, endpoint())
        push.unsubscribe(owner, None)
        assert subscriptions() == []


class TestDeliver:
    def test_to_every_device_of_the_recipient(self, app, outbox):
        user, other = make_user(), make_user()
        group = make_group(user)
        subscribe(user, 1)
        subscribe(user, 2)
        subscribe(other, 3)
        assert push.deliver([delivery(user, group)]) == 2
        assert sorted(e for e, _ in outbox) == [endpoint(1), endpoint(2)]

    def test_switched_off_occasions_are_skipped(self, app, outbox):
        """NOT-02: per group and occasion."""
        user = make_user()
        group, other_group = make_group(user), make_group(user, "Andere")
        subscribe(user)
        push.set_preferences(user, group.id, set(NotificationKind) - {NotificationKind.REMINDER})
        push.deliver(
            [
                delivery(user, group, NotificationKind.REMINDER),
                delivery(user, group, NotificationKind.WINDOW_OPEN),
                delivery(user, other_group, NotificationKind.REMINDER),
            ]
        )
        assert len(outbox) == 2
        prefs = push.preferences(user.id, group.id)
        assert not prefs[NotificationKind.REMINDER] and prefs[NotificationKind.OVERTAKEN]
        assert all(push.preferences(user.id, other_group.id).values())

    def test_gone_subscriptions_are_removed(self, app, outbox):
        user = make_user()
        group = make_group(user)
        subscribe(user, 1)
        subscribe(user, 2)
        app.extensions["push"].gone.add(endpoint(1))
        assert push.deliver([delivery(user, group)]) == 1
        assert [s.endpoint for s in subscriptions()] == [endpoint(2)]

    def test_a_failing_service_is_only_logged(self, app, monkeypatch):
        user = make_user()
        group = make_group(user)
        subscribe(user)

        def broken(target, message):
            raise ConnectionError("down")

        monkeypatch.setattr(app.extensions["push"], "send", broken)
        assert push.deliver([delivery(user, group)]) == 0
        assert len(subscriptions()) == 1


def test_vapid_keys_have_the_formats_browser_and_pywebpush_expect():
    from py_vapid import Vapid02

    private, public = push.generate_vapid_keys()
    raw_public = base64.urlsafe_b64decode(public + "=" * (-len(public) % 4))
    assert len(raw_public) == 65 and raw_public[0] == 4  # uncompressed P-256 point
    assert Vapid02.from_string(private).public_key is not None


def test_payload_is_what_the_service_worker_reads():
    message = Push("Runde", "Äpfel", "/g/1/", "g1-scores")
    assert push.payload(message) == (
        '{"title": "Runde", "body": "Äpfel", "url": "/g/1/", "tag": "g1-scores"}'
    )
