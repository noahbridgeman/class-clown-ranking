import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import User
from app.services import invitations, membership
from app.services.mail import Mail
from tests.factories import make_group, make_user

LINK = re.compile(r"http://localhost:5000(/invite/\S+)")


def invite_path(outbox: list[Mail]) -> str:
    return LINK.search(outbox[-1].body).group(1)


def session_user(client) -> str | None:
    with client.session_transaction() as session:
        return session.get("_user_id")


@pytest.fixture
def admin(app) -> User:
    return make_user("admin@example.org", display_name="Ada")


@pytest.fixture
def group(admin):
    return make_group(admin, "Runde")


class TestAdminPage:
    def test_lists_invitations_with_status(self, group, admin, login_as, clock):
        invitations.invite(group, admin, "offen@example.org")
        old = invitations.invite(group, admin, "weg@example.org").invitation
        invitations.revoke(group, admin, old.id)
        html = login_as(admin).get(f"/g/{group.id}/invitations").get_data(True)
        assert "offen@example.org" in html
        assert "offen bis 30.10.2026" in html
        assert "zurückgezogen" in html
        assert "7 Tage gültig" in html

    def test_invite_without_javascript_redirects(self, group, admin, login_as, outbox):
        client = login_as(admin)
        response = client.post(f"/g/{group.id}/invitations", data={"email": "neu@example.org"})
        assert response.location == f"/g/{group.id}/invitations"
        assert "Einladung an neu@example.org verschickt." in client.get(response.location).get_data(
            True
        )
        assert [mail.to for mail in outbox] == ["neu@example.org"]

    def test_invite_with_htmx_returns_the_list(self, group, admin, login_as):
        client = login_as(admin)
        response = client.post(
            f"/g/{group.id}/invitations",
            data={"email": "neu@example.org"},
            headers={"HX-Request": "true"},
        )
        html = response.get_data(True)
        assert response.status_code == 200
        assert html.lstrip().startswith('<div id="invitations">') or 'id="invitations"' in html
        assert "<html" not in html
        assert "verschickt" in html
        assert 'value=""' in html  # the field is cleared for the next address

    def test_htmx_error_keeps_the_input(self, group, admin, login_as):
        client = login_as(admin)
        response = client.post(
            f"/g/{group.id}/invitations",
            data={"email": "admin@example.org"},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 400
        html = response.get_data(True)
        assert "schon Mitglied" in html
        assert 'value="admin@example.org"' in html

    def test_resend_and_revoke(self, group, admin, login_as, outbox, clock):
        invitation = invitations.invite(group, admin, "neu@example.org").invitation
        client = login_as(admin)
        clock.advance(timedelta(minutes=10))
        client.post(f"/g/{group.id}/invitations/{invitation.id}/resend")
        assert len(outbox) == 2
        response = client.post(
            f"/g/{group.id}/invitations/{invitation.id}/revoke", headers={"HX-Request": "true"}
        )
        assert "Einladung zurückgezogen." in response.get_data(True)

    def test_resend_too_soon_shows_message(self, group, admin, login_as):
        invitation = invitations.invite(group, admin, "neu@example.org").invitation
        client = login_as(admin)
        response = client.post(
            f"/g/{group.id}/invitations/{invitation.id}/resend", headers={"HX-Request": "true"}
        )
        assert "gerade erst verschickt" in response.get_data(True)

    def test_mail_failure_is_shown(self, group, admin, login_as, monkeypatch):
        def fail(_mail):
            raise OSError("SMTP down")

        monkeypatch.setattr("app.services.mail.send", fail)
        client = login_as(admin)
        client.post(f"/g/{group.id}/invitations", data={"email": "neu@example.org"})
        html = client.get(f"/g/{group.id}/invitations").get_data(True)
        assert "konnte nicht verschickt werden" in html

    def test_invitation_ids_of_other_groups_are_404(self, group, admin, login_as):
        other_admin = make_user()
        other = make_group(other_admin, "Andere")
        foreign = invitations.invite(other, other_admin, "neu@example.org").invitation
        client = login_as(admin)
        assert client.post(f"/g/{group.id}/invitations/{foreign.id}/revoke").status_code == 404
        assert foreign.revoked_at is None


class TestAcceptAsGuest:
    def test_link_logs_in_creates_account_and_joins(self, group, admin, client, outbox):
        invitations.invite(group, admin, "neu@example.org")
        page = client.get(invite_path(outbox))
        html = page.get_data(True)
        assert "Ada lädt dich in die Gruppe „Runde“ ein" in html
        assert "meldest du dich gleichzeitig an" in html
        assert page.headers["Referrer-Policy"] == "no-referrer"
        assert page.headers["Cache-Control"] == "no-store"

        response = client.post(invite_path(outbox))
        assert response.location == f"/g/{group.id}/"
        user = db.session.scalar(select(User).where(User.email == "neu@example.org"))
        assert session_user(client) == user.get_id()
        # AUTH-04: a new account names itself first.
        assert client.get(response.location).location == "/account/name"
        client.post("/account/name", data={"display_name": "Neu"})
        assert "Runde" in client.get("/").get_data(True)
        assert client.get(f"/g/{group.id}/").status_code == 200

    def test_opening_the_link_does_not_use_it(self, group, admin, client, outbox):
        invitations.invite(group, admin, "neu@example.org")
        client.get(invite_path(outbox))
        client.get(invite_path(outbox))
        assert client.post(invite_path(outbox)).status_code == 302

    def test_used_link(self, group, admin, app, client, outbox):
        invitations.invite(group, admin, "neu@example.org")
        client.post(invite_path(outbox))
        other = app.test_client()
        assert other.get(invite_path(outbox)).status_code == 400
        response = other.post(invite_path(outbox))
        assert response.status_code == 400
        assert "Einladung ungültig" in response.get_data(True)
        assert session_user(other) is None

    def test_expired_link(self, group, admin, client, outbox, clock):
        invitations.invite(group, admin, "neu@example.org")
        clock.advance(timedelta(days=7))
        assert client.get(invite_path(outbox)).status_code == 400

    def test_login_session_is_fresh(self, group, admin, client, outbox):
        invitations.invite(group, admin, "neu@example.org")
        with client.session_transaction() as session:
            session["leftover"] = 1
        client.post(invite_path(outbox))
        with client.session_transaction() as session:
            assert "leftover" not in session


class TestAcceptWhileLoggedIn:
    def test_matching_account_joins(self, group, admin, login_as, outbox):
        bo = make_user("bo@example.org", display_name="Bo")
        invitations.invite(group, admin, "bo@example.org")
        client = login_as(bo)
        assert "Einladung annehmen" in client.get(invite_path(outbox)).get_data(True)
        client.post(invite_path(outbox))
        assert membership.active_membership(group.id, bo.id) is not None

    def test_nameless_account_can_accept(self, group, admin, login_as, outbox):
        bo = make_user("bo@example.org", display_name=None)
        invitations.invite(group, admin, "bo@example.org")
        client = login_as(bo)
        assert client.get(invite_path(outbox)).status_code == 200
        assert client.post(invite_path(outbox)).location == f"/g/{group.id}/"

    def test_wrong_account_is_refused(self, group, admin, login_as, outbox):
        eve = make_user("eve@example.org")
        invitations.invite(group, admin, "bo@example.org")
        client = login_as(eve)
        page = client.get(invite_path(outbox))
        assert page.status_code == 409
        assert "andere E-Mail-Adresse" in page.get_data(True)
        response = client.post(invite_path(outbox))
        assert response.status_code == 409
        assert membership.active_membership(group.id, eve.id) is None
        assert session_user(client) == eve.get_id()

    def test_logout_leads_back_to_the_invitation(self, group, admin, login_as, outbox):
        invitations.invite(group, admin, "bo@example.org")
        client = login_as(make_user("eve@example.org"))
        html = client.get(invite_path(outbox)).get_data(True)
        assert f'value="{invite_path(outbox)}"' in html
        response = client.post("/logout", data={"next": invite_path(outbox)})
        assert response.location == invite_path(outbox)
        assert session_user(client) is None
        assert client.post(invite_path(outbox)).location == f"/g/{group.id}/"


class TestLogoutNext:
    @pytest.mark.parametrize(
        "target",
        [
            "https://evil.example/invite/x",
            "//evil.example/invite/",
            "/invite//evil.example",
            "/account/name",
            "/invite/\\\\evil.example",
            "",
        ],
    )
    def test_only_invitation_paths_are_followed(self, login_as, target):
        client = login_as(make_user())
        assert client.post("/logout", data={"next": target}).location == "/"


def test_group_and_invitation_flow_with_csrf(csrf_app):
    """TestConfig disables CSRF, so the new forms run once with it switched on."""
    from tests.web.test_auth import csrf_token

    outbox = csrf_app.extensions["mail"].outbox
    admin = make_user("admin@example.org", display_name="Ada")
    client = csrf_app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = admin.get_id()

    page = client.get("/groups/new").get_data(True)
    assert client.post("/groups/new", data={"name": "Runde"}).status_code == 400
    response = client.post("/groups/new", data={"name": "Runde", "csrf_token": csrf_token(page)})
    home = response.location

    group_id = int(home.strip("/").split("/")[1])
    page = client.get(f"/g/{group_id}/invitations").get_data(True)
    data = {"email": "neu@example.org"}
    assert client.post(f"/g/{group_id}/invitations", data=data).status_code == 400
    client.post(f"/g/{group_id}/invitations", data={**data, "csrf_token": csrf_token(page)})
    assert [mail.to for mail in outbox] == ["neu@example.org"]

    guest = csrf_app.test_client()
    path = invite_path(outbox)
    page = guest.get(path).get_data(True)
    assert guest.post(path).status_code == 400
    assert guest.post(path, data={"csrf_token": csrf_token(page)}).location == home
