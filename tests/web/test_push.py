"""PWA and push in the browser (NFA-02, NOT-01, NOT-02, A24)."""

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import NotificationKind, PushSubscription
from app.services import push
from tests.factories import IN_WEEK_WINDOW, WEEK_CLOSES, add_member, make_group, make_user, tick
from tests.services.test_push import AUTH, KEY

ENDPOINT = "https://fcm.googleapis.com/fcm/send/device-1"
SUBSCRIPTION = {"endpoint": ENDPOINT, "keys": {"p256dh": KEY, "auth": AUTH}}


@pytest.fixture
def pair(app):
    a, b = make_user(display_name="Ada"), make_user(display_name="Bo")
    group = make_group(a, "Runde")
    add_member(group, b)
    return group, a, b


def stored() -> list[tuple[int, str]]:
    return [(s.user_id, s.endpoint) for s in db.session.scalars(select(PushSubscription))]


class TestPwa:
    def test_manifest_makes_it_installable(self, client):
        response = client.get("/manifest.webmanifest")
        assert response.mimetype == "application/manifest+json"
        manifest = response.get_json()
        assert manifest["display"] == "standalone" and manifest["start_url"] == "/"
        assert manifest["name"] == "Spaßvogel-Ranking"
        sizes = {icon["sizes"] for icon in manifest["icons"]}
        assert {"192x192", "512x512"} <= sizes
        assert any(icon.get("purpose") == "maskable" for icon in manifest["icons"])
        for icon in manifest["icons"]:
            response = client.get(icon["src"])
            assert response.status_code == 200 and response.mimetype == "image/png"
            response.close()

    def test_service_worker_from_the_root_and_not_cached(self, client):
        response = client.get("/sw.js")
        assert response.status_code == 200
        assert response.mimetype in {"text/javascript", "application/javascript"}
        assert response.headers["Cache-Control"] == "no-cache"
        assert b"notificationclick" in response.data

    def test_every_page_links_manifest_icon_and_push_script(self, client):
        html = client.get("/").get_data(as_text=True)
        assert 'rel="manifest" href="/manifest.webmanifest"' in html
        assert 'rel="apple-touch-icon"' in html
        assert "js/push.js" in html


class TestSubscription:
    def test_subscribe_and_unsubscribe(self, pair, login_as):
        _group, a, _b = pair
        client = login_as(a)
        assert client.post("/push/subscription", json=SUBSCRIPTION).status_code == 200
        assert stored() == [(a.id, ENDPOINT)]
        client.post("/push/subscription/delete", json={"endpoint": ENDPOINT})
        assert stored() == []

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"endpoint": "https://intranet.example.org/hook", "keys": SUBSCRIPTION["keys"]},
            {"endpoint": ENDPOINT, "keys": "kaputt"},
            {"endpoint": ENDPOINT, "keys": {"p256dh": KEY}},
        ],
    )
    def test_invalid_subscriptions_are_refused(self, pair, login_as, body):
        _group, a, _b = pair
        response = login_as(a).post("/push/subscription", json=body)
        assert response.status_code == 400
        assert "nicht anmelden" in response.get_json()["error"]
        assert stored() == []

    def test_guests_cannot_subscribe(self, client):
        assert client.post("/push/subscription", json=SUBSCRIPTION).status_code == 302
        assert stored() == []

    def test_needs_the_csrf_header(self, csrf_app):
        with csrf_app.app_context():
            user = make_user()
            client = csrf_app.test_client()
            with client.session_transaction() as session:
                session["_user_id"] = user.get_id()
            assert client.post("/push/subscription", json=SUBSCRIPTION).status_code == 400
            assert stored() == []

    def test_logout_ends_the_pushes_of_this_device(self, pair, login_as):
        _group, a, _b = pair
        push.subscribe(a, ENDPOINT, KEY, AUTH)
        page = login_as(a).get("/account/name").get_data(as_text=True)
        assert 'name="endpoint"' in page and "data-push-endpoint" in page
        login_as(a).post("/logout", data={"endpoint": ENDPOINT})
        assert stored() == []


class TestPreferences:
    def test_settings_page_has_the_section_for_every_member(self, pair, login_as):
        group, _a, b = pair
        html = login_as(b).get(f"/g/{group.id}/settings").get_data(as_text=True)
        assert 'id="benachrichtigungen"' in html and "data-push" in html
        assert html.count('name="kind"') == len(NotificationKind)
        assert html.count(" checked>") >= len(NotificationKind)  # all on by default

    def test_saving_by_htmx_and_without_javascript(self, pair, login_as):
        """NOT-02."""
        group, _a, b = pair
        client = login_as(b)
        url = f"/g/{group.id}/notifications"
        response = client.post(
            url, data={"kind": ["window_open", "overtaken"]}, headers={"HX-Request": "true"}
        )
        assert response.status_code == 200 and "Benachrichtigungen gespeichert" in response.text
        prefs = push.preferences(b.id, group.id)
        assert {k for k, on in prefs.items() if on} == {
            NotificationKind.WINDOW_OPEN,
            NotificationKind.OVERTAKEN,
        }
        response = client.post(url, data={})
        assert response.status_code == 302 and response.location.endswith("#benachrichtigungen")
        assert not any(push.preferences(b.id, group.id).values())

    def test_unknown_kinds_are_ignored(self, pair, login_as):
        group, _a, b = pair
        login_as(b).post(f"/g/{group.id}/notifications", data={"kind": ["spam", "reminder"]})
        on = {k for k, v in push.preferences(b.id, group.id).items() if v}
        assert on == {NotificationKind.REMINDER}


class TestOffer:
    def test_closed_voting_offers_push_when_configured(self, app, pair, clock, login_as):
        group, a, _b = pair
        clock.set(IN_WEEK_WINDOW)
        tick()
        clock.set(WEEK_CLOSES)
        tick()
        url = f"/g/{group.id}/vote"
        assert "Erinnerung aufs Handy?" not in login_as(a).get(url).text  # no keys in tests
        app.config["VAPID_PUBLIC_KEY"] = "BPublicKey"
        html = login_as(a).get(url).text
        assert "Erinnerung aufs Handy?" in html
        assert 'data-key="BPublicKey"' in html and 'data-state="noscript"' in html
