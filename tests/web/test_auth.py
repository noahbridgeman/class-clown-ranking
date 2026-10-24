import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from flask import Flask, url_for
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from app import create_app
from app.clock import FrozenClock
from app.config import TestConfig
from app.extensions import db
from app.models import User
from app.services.mail import Mail
from tests.conftest import IsolatedClient
from tests.factories import allow, make_user

LINK = re.compile(r"http://localhost:5000(/login/\S+)")
CSRF_INPUT = re.compile(r'name="csrf_token" (?:type="hidden" )?value="([^"]+)"')
# Everything a client can observe about a response, except the timestamp header.
Observed = tuple[int, str | None, list[tuple[str, str]], bytes]


def link_path(outbox: list[Mail]) -> str:
    return LINK.search(outbox[-1].body).group(1)


def log_in_via_mail(client: FlaskClient, outbox: list[Mail], email: str) -> TestResponse:
    client.post("/login", data={"email": email})
    return client.post(link_path(outbox))


def current_user_id(client: FlaskClient) -> str | None:
    with client.session_transaction() as session:
        return session.get("_user_id")


def csrf_token(html: str) -> str:
    return CSRF_INPUT.search(html).group(1)


def observe(response: TestResponse) -> Observed:
    headers = sorted((name, value) for name, value in response.headers if name != "Date")
    return response.status_code, response.location, headers, response.get_data()


@pytest.fixture
def csrf_app() -> Iterator[Flask]:
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


class TestLoginFlow:
    def test_login_page_renders(self, client):
        html = client.get("/login").get_data(as_text=True)
        assert 'type="email"' in html
        assert "Link schicken" in html

    def test_full_flow_for_new_account(self, client, outbox):
        allow("neu@example.org")
        response = client.post("/login", data={"email": "Neu@Example.org"})
        assert response.status_code == 302
        assert response.location == "/login/sent"

        confirm = client.get(link_path(outbox))
        assert confirm.status_code == 200
        assert "Jetzt anmelden" in confirm.get_data(as_text=True)

        response = client.post(link_path(outbox))
        assert response.status_code == 302
        user = db.session.query(User).one()
        assert current_user_id(client) == user.get_id()
        # AUTH-04: the new account has to pick a name first.
        assert client.get("/").location == "/account/name"

    def test_opening_the_link_does_not_use_it_up(self, client, outbox):
        make_user("anna@example.org")
        client.post("/login", data={"email": "anna@example.org"})
        client.get(link_path(outbox))
        client.get(link_path(outbox))
        assert client.post(link_path(outbox)).status_code == 302

    def test_link_works_only_once(self, client, app, outbox):
        make_user("anna@example.org")
        log_in_via_mail(client, outbox, "anna@example.org")
        other = app.test_client()
        response = other.post(link_path(outbox))
        assert response.status_code == 400
        assert "abgelaufen oder wurde schon benutzt" in response.get_data(as_text=True)
        assert current_user_id(other) is None

    def test_expired_link_is_rejected(self, client, outbox, clock):
        make_user("anna@example.org")
        client.post("/login", data={"email": "anna@example.org"})
        clock.advance(timedelta(minutes=15))
        assert client.post(link_path(outbox)).status_code == 400
        assert current_user_id(client) is None

    def test_invalid_email_shows_error(self, client, outbox):
        response = client.post("/login", data={"email": "kein-at"})
        assert response.status_code == 400
        html = response.get_data(as_text=True)
        assert "gültige E-Mail-Adresse" in html
        assert 'aria-invalid="true"' in html
        assert outbox == []

    def test_login_page_redirects_when_logged_in(self, login_as):
        client = login_as(make_user())
        assert client.get("/login").location == "/"

    def test_mail_link_uses_base_url(self, client, app, outbox):
        app.config["BASE_URL"] = "https://ranking.example.org"
        make_user("anna@example.org")
        client.post("/login", data={"email": "anna@example.org"}, base_url="http://evil.example")
        assert "https://ranking.example.org/login/" in outbox[0].body
        assert "evil.example" not in outbox[0].body

    def test_mail_link_matches_confirm_route(self, client, app, outbox):
        make_user("anna@example.org")
        client.post("/login", data={"email": "anna@example.org"})
        token = link_path(outbox).removeprefix("/login/")
        with app.test_request_context():
            assert url_for("auth.confirm", token=token) == link_path(outbox)


class TestTokenPages:
    """The token is in the URL, so neither Referer headers nor caches may keep it."""

    @staticmethod
    def assert_protected(response: TestResponse) -> None:
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Cache-Control"] == "no-store"

    def test_confirm_page(self, client, outbox):
        make_user("anna@example.org")
        client.post("/login", data={"email": "anna@example.org"})
        self.assert_protected(client.get(link_path(outbox)))

    def test_invalid_link_page(self, client):
        self.assert_protected(client.post("/login/kaputt"))

    def test_csrf_error_page(self, csrf_app):
        client = csrf_app.test_client()
        response = client.post("/login/kaputt")
        assert response.status_code == 400
        assert "Sitzung abgelaufen" in response.get_data(as_text=True)
        self.assert_protected(response)

    def test_other_pages_are_unaffected(self, client):
        assert "Referrer-Policy" not in client.get("/login").headers


class TestNoAccountEnumeration:
    """E3: the response must not reveal whether an address has an account.

    Status, headers (including Set-Cookie) and body of the form POST and of the page it
    redirects to must be identical. The client loads the form first, like a browser.
    """

    def _respond(self, client: FlaskClient, email: str) -> tuple[Observed, Observed]:
        page = client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
        data = {"email": email, "csrf_token": token}
        response = client.post("/login", data=data)
        return observe(response), observe(client.get(response.location))

    @pytest.fixture(params=["csrf_off", "csrf_on"])
    def setup(self, request: pytest.FixtureRequest) -> tuple[FlaskClient, list[Mail]]:
        target = request.getfixturevalue("csrf_app" if request.param == "csrf_on" else "app")
        return target.test_client(), target.extensions["mail"].outbox

    @pytest.fixture
    def client_and_outbox(
        self, setup: tuple[FlaskClient, list[Mail]]
    ) -> tuple[FlaskClient, list[Mail]]:
        client, outbox = setup
        client.get("/login")  # the session cookie is set once, on the first visit
        return client, outbox

    def test_known_and_unknown_addresses_look_the_same(self, client_and_outbox):
        client, outbox = client_and_outbox
        make_user("anna@example.org")
        allow("neu@example.org")
        known = self._respond(client, "anna@example.org")
        allowed = self._respond(client, "neu@example.org")
        unknown = self._respond(client, "fremd@example.org")
        assert known == allowed == unknown
        assert [mail.to for mail in outbox] == ["anna@example.org", "neu@example.org"]

    def test_no_cookie_is_set_by_the_request(self, client_and_outbox):
        client, _ = client_and_outbox
        make_user("anna@example.org")
        (post, page) = self._respond(client, "anna@example.org")
        assert all(name != "Set-Cookie" for name, _ in post[2] + page[2])

    def test_rate_limited_address_looks_the_same(self, client_and_outbox):
        client, outbox = client_and_outbox
        make_user("anna@example.org")
        first = self._respond(client, "anna@example.org")
        for _ in range(5):
            limited = self._respond(client, "anna@example.org")
        assert len(outbox) == 5
        assert limited == first == self._respond(client, "fremd@example.org")

    def test_mail_failure_looks_the_same(self, client_and_outbox, monkeypatch):
        from app.services import auth

        client, _ = client_and_outbox
        make_user("anna@example.org")

        def fail(_mail: Mail) -> None:
            raise OSError("SMTP down")

        monkeypatch.setattr(auth.mail, "send", fail)
        assert self._respond(client, "anna@example.org") == self._respond(client, "x@example.org")


class TestAccountSwitch:
    """A logged-in browser opens a login link that was requested on another device."""

    @staticmethod
    def request_link(app: Flask, outbox: list[Mail], email: str) -> str:
        app.test_client().post("/login", data={"email": email})
        return link_path(outbox)

    def test_login_starts_a_fresh_session(self, app, login_as, outbox):
        client = login_as(make_user("anna@example.org"))
        with client.session_transaction() as session:
            session["selected_group"] = 42
        bo = make_user("bo@example.org")
        client.post(self.request_link(app, outbox, "bo@example.org"))
        with client.session_transaction() as session:
            assert "selected_group" not in session
            assert session["_user_id"] == bo.get_id()

    def test_nameless_account_can_use_a_login_link(self, app, login_as, outbox):
        client = login_as(make_user("neu@example.org", display_name=None))
        bo = make_user("bo@example.org", display_name="Bo")
        path = self.request_link(app, outbox, "bo@example.org")
        assert client.get(path).status_code == 200
        assert client.post(path).location == "/"
        assert current_user_id(client) == bo.get_id()


class TestRememberSession:
    def test_login_sets_30_day_remember_cookie(self, client, app, outbox):
        make_user("anna@example.org")
        response = log_in_via_mail(client, outbox, "anna@example.org")
        cookie = next(c for c in response.headers.getlist("Set-Cookie") if "remember_token" in c)
        assert "HttpOnly" in cookie
        assert "SameSite=Lax" in cookie
        assert "Expires=" in cookie
        assert app.config["REMEMBER_COOKIE_DURATION"] == timedelta(days=30)

    def test_remember_cookie_restores_session(self, client, outbox):
        make_user("anna@example.org", display_name="Anna")
        log_in_via_mail(client, outbox, "anna@example.org")
        with client.session_transaction() as session:
            session.clear()  # browser restarted, session cookie gone
        html = client.get("/").get_data(as_text=True)
        assert "Hallo, Anna!" in html


class TestSessionVersion:
    def test_bumping_the_version_ends_the_session(self, login_as):
        user = make_user(display_name="Anna")
        client = login_as(user)
        assert "Hallo, Anna!" in client.get("/").get_data(as_text=True)
        user.session_version += 1
        db.session.commit()
        assert "Hallo, Anna!" not in client.get("/").get_data(as_text=True)

    def test_bumping_the_version_invalidates_the_remember_cookie(self, client, outbox):
        user = make_user("anna@example.org", display_name="Anna")
        log_in_via_mail(client, outbox, "anna@example.org")
        user.session_version += 1
        db.session.commit()
        with client.session_transaction() as session:
            session.clear()
        assert "Hallo, Anna!" not in client.get("/").get_data(as_text=True)

    def test_deleted_account_is_logged_out(self, login_as, clock):
        user = make_user(display_name="Anna")
        client = login_as(user)
        user.deleted_at = clock.now()
        db.session.commit()
        assert "Hallo, Anna!" not in client.get("/").get_data(as_text=True)

    @pytest.mark.parametrize("session_id", ["1", "1:", ":1", "x:1", "1:x", "1:²", "999:1"])
    def test_malformed_session_ids_are_ignored(self, client, session_id):
        make_user(display_name="Anna")
        with client.session_transaction() as session:
            session["_user_id"] = session_id
        response = client.get("/")
        assert response.status_code == 200
        assert "Hallo" not in response.get_data(as_text=True)


class TestLogout:
    def test_logout_ends_session_and_remember_cookie(self, client, outbox):
        make_user("anna@example.org", display_name="Anna")
        log_in_via_mail(client, outbox, "anna@example.org")
        response = client.post("/logout")
        assert response.location == "/"
        assert client.get_cookie("remember_token") is None
        assert current_user_id(client) is None
        assert "Hallo, Anna!" not in client.get("/").get_data(as_text=True)

    def test_logout_needs_post(self, login_as):
        client = login_as(make_user())
        assert client.get("/logout").status_code == 405

    def test_htmx_logout_redirects_via_header(self, login_as):
        client = login_as(make_user())
        response = client.post("/logout", headers={"HX-Request": "true"})
        assert response.status_code == 204
        assert response.headers["HX-Redirect"] == "/"

    def test_nav_shows_logout_when_logged_in(self, login_as):
        html = login_as(make_user()).get("/").get_data(as_text=True)
        assert 'action="/logout"' in html
        assert "Name ändern" in html

    def test_nav_shows_login_when_logged_out(self, client):
        html = client.get("/").get_data(as_text=True)
        assert 'href="/login"' in html
        assert 'action="/logout"' not in html


class TestNameGate:
    """AUTH-04: without a display name nothing else is reachable."""

    @pytest.fixture
    def nameless(self, login_as):
        return login_as(make_user(display_name=None))

    @pytest.mark.parametrize("path", ["/", "/login", "/login/sent", "/gibt-es-nicht"])
    def test_redirects_everything_to_name_form(self, nameless, path):
        response = nameless.get(path)
        assert response.status_code == 302
        assert response.location == "/account/name"

    def test_htmx_requests_get_redirect_header(self, nameless):
        response = nameless.get("/", headers={"HX-Request": "true"})
        assert response.status_code == 204
        assert response.headers["HX-Redirect"] == "/account/name"

    def test_name_form_logout_and_static_stay_reachable(self, nameless):
        assert nameless.get("/account/name").status_code == 200
        with nameless.get("/static/css/app.css") as response:
            assert response.status_code == 200
        assert nameless.post("/logout").location == "/"

    def test_first_time_form_asks_for_a_name(self, nameless):
        html = nameless.get("/account/name").get_data(as_text=True)
        assert "Wie sollen dich die anderen sehen?" in html
        assert "Name ändern" not in html

    def test_setting_a_name_opens_the_app(self, nameless):
        response = nameless.post("/account/name", data={"display_name": "  Anna  "})
        assert response.location == "/"
        assert "Hallo, Anna!" in nameless.get("/").get_data(as_text=True)

    def test_blank_name_is_rejected(self, nameless):
        response = nameless.post("/account/name", data={"display_name": "   "})
        assert response.status_code == 400
        assert "Bitte gib einen Namen ein." in response.get_data(as_text=True)
        assert nameless.get("/").location == "/account/name"

    def test_logged_out_visitors_are_not_gated(self, client):
        assert client.get("/").status_code == 200


class TestChangeName:
    def test_form_is_prefilled(self, login_as):
        client = login_as(make_user(display_name="Anna"))
        html = client.get("/account/name").get_data(as_text=True)
        assert 'value="Anna"' in html
        assert "Anzeigenamen ändern" in html

    def test_changes_name(self, login_as):
        user = make_user(display_name="Anna")
        client = login_as(user)
        client.post("/account/name", data={"display_name": "Anna Lena"})
        db.session.expire_all()
        assert db.session.get(User, user.id).display_name == "Anna Lena"

    def test_too_long_name_is_rejected(self, login_as):
        client = login_as(make_user(display_name="Anna"))
        response = client.post("/account/name", data={"display_name": "x" * 41})
        assert response.status_code == 400
        assert "höchstens 40 Zeichen" in response.get_data(as_text=True)

    def test_name_is_escaped(self, login_as):
        client = login_as(make_user(display_name="<script>x</script>"))
        html = client.get("/").get_data(as_text=True)
        assert "<script>x</script>" not in html
        assert "&lt;script&gt;" in html

    def test_requires_login(self, client):
        response = client.get("/account/name")
        assert response.status_code == 302
        assert response.location == "/login"

    def test_htmx_request_without_login_redirects_via_header(self, client):
        response = client.get("/account/name", headers={"HX-Request": "true"})
        assert response.status_code == 204
        assert response.headers["HX-Redirect"] == "/login"


class TestWithCsrf:
    """TestConfig disables CSRF, so the forms are exercised once with it switched on."""

    def test_full_flow_with_csrf(self, csrf_app):
        client = csrf_app.test_client()
        outbox = csrf_app.extensions["mail"].outbox
        allow("neu@example.org")

        page = client.get("/login").get_data(as_text=True)
        assert client.post("/login", data={"email": "neu@example.org"}).status_code == 400
        response = client.post(
            "/login", data={"email": "neu@example.org", "csrf_token": csrf_token(page)}
        )
        assert response.location == "/login/sent"

        path = link_path(outbox)
        confirm = client.get(path).get_data(as_text=True)
        assert client.post(path).status_code == 400
        assert client.post(path, data={"csrf_token": csrf_token(confirm)}).status_code == 302

        form = client.get("/account/name").get_data(as_text=True)
        assert client.post("/account/name", data={"display_name": "Anna"}).status_code == 400
        response = client.post(
            "/account/name", data={"display_name": "Anna", "csrf_token": csrf_token(form)}
        )
        assert response.location == "/"

        home = client.get("/").get_data(as_text=True)
        assert client.post("/logout").status_code == 400
        assert client.post("/logout", data={"csrf_token": csrf_token(home)}).location == "/"

    def test_link_without_csrf_token_stays_usable(self, csrf_app):
        client = csrf_app.test_client()
        outbox = csrf_app.extensions["mail"].outbox
        make_user("anna@example.org")
        page = client.get("/login").get_data(as_text=True)
        client.post("/login", data={"email": "anna@example.org", "csrf_token": csrf_token(page)})
        path = link_path(outbox)
        client.post(path)  # rejected for the missing CSRF token
        confirm = client.get(path).get_data(as_text=True)
        assert client.post(path, data={"csrf_token": csrf_token(confirm)}).status_code == 302
