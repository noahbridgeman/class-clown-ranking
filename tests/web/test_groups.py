from sqlalchemy import select

from app.extensions import db
from app.models import Group
from app.services import membership
from tests.factories import add_member, make_group, make_user


class TestIndex:
    def test_lists_own_groups(self, login_as):
        user = make_user(display_name="Anna")
        make_group(user, "Alpha")
        make_group(name="Fremd")
        html = login_as(user).get("/").get_data(as_text=True)
        assert "Alpha" in html
        assert "Fremd" not in html
        assert "Neue Gruppe erstellen" in html

    def test_without_groups(self, login_as):
        html = login_as(make_user()).get("/").get_data(as_text=True)
        assert "noch in keiner Gruppe" in html


class TestCreate:
    def test_creates_group_and_redirects(self, login_as):
        user = make_user()
        client = login_as(user)
        response = client.post("/groups/new", data={"name": "  Die Runde "})
        group = db.session.scalar(select(Group))
        assert response.location == f"/g/{group.id}/"
        html = client.get(response.location).get_data(as_text=True)
        assert "Die Runde" in html
        assert "ist erstellt" in html
        assert group.admin_user_id == user.id

    def test_invalid_name(self, login_as):
        response = login_as(make_user()).post("/groups/new", data={"name": "  "})
        assert response.status_code == 400
        assert "Bitte gib einen Namen ein." in response.get_data(as_text=True)
        assert db.session.scalar(select(Group)) is None

    def test_requires_login(self, client):
        assert client.get("/groups/new").location == "/login"


class TestHome:
    def test_shows_members_with_admin_badge_and_self(self, login_as):
        admin = make_user(display_name="Ada")
        group = make_group(admin, "Runde")
        bo = add_member(group, make_user(display_name="Bo"))
        html = login_as(bo).get(f"/g/{group.id}/").get_data(as_text=True)
        assert "Mitglieder (2)" in html
        assert "Ada" in html and "Bo" in html
        assert "Admin</span>" in html
        assert "(du)" in html
        assert "Verwalten" not in html
        assert "Einladungen" not in html

    def test_admin_sees_management(self, login_as):
        admin = make_user()
        group = make_group(admin)
        add_member(group)
        html = login_as(admin).get(f"/g/{group.id}/").get_data(as_text=True)
        assert html.count("Verwalten") == 1  # not for the admin's own row
        assert f"/g/{group.id}/invitations" in html
        assert f"/g/{group.id}/delete" in html

    def test_former_members_are_not_listed(self, login_as):
        admin = make_user()
        group = make_group(admin)
        gone = add_member(group, make_user(display_name="Weg"))
        membership.leave(group, gone)
        assert "Weg" not in login_as(admin).get(f"/g/{group.id}/").get_data(as_text=True)


class TestManageMembers:
    def test_remove(self, login_as):
        admin = make_user()
        group = make_group(admin)
        bo = add_member(group, make_user(display_name="Bo"))
        client = login_as(admin)
        response = client.post(f"/g/{group.id}/members/{bo.id}/remove")
        assert response.location == f"/g/{group.id}/"
        assert "Bo wurde aus der Gruppe entfernt." in client.get(response.location).get_data(True)
        assert membership.active_membership(group.id, bo.id) is None

    def test_flash_names_deleted_accounts_as_such(self, login_as):
        admin = make_user()
        group = make_group(admin)
        gone = add_member(group, make_user(display_name=None))
        client = login_as(admin)
        client.post(f"/g/{group.id}/members/{gone.id}/remove")
        html = client.get(f"/g/{group.id}/").get_data(True)
        assert "Gelöschtes Mitglied wurde aus der Gruppe entfernt." in html
        assert "None" not in html

    def test_remove_self_is_refused_with_message(self, login_as):
        admin = make_user()
        group = make_group(admin)
        client = login_as(admin)
        client.post(f"/g/{group.id}/members/{admin.id}/remove")
        assert "Dich selbst kannst du nicht entfernen" in client.get(f"/g/{group.id}/").get_data(
            True
        )

    def test_remove_stranger_is_404(self, login_as):
        admin = make_user()
        group = make_group(admin)
        stranger = make_user()
        assert (
            login_as(admin).post(f"/g/{group.id}/members/{stranger.id}/remove").status_code == 404
        )

    def test_transfer_admin(self, login_as, outbox):
        admin = make_user()
        group = make_group(admin)
        bo = add_member(group, make_user(display_name="Bo"))
        client = login_as(admin)
        client.post(f"/g/{group.id}/members/{bo.id}/admin")
        db.session.expire_all()
        assert db.session.get(Group, group.id).admin_user_id == bo.id
        assert [mail.to for mail in outbox] == [bo.email]
        # The former admin lost the management controls.
        assert "Verwalten" not in client.get(f"/g/{group.id}/").get_data(True)


class TestLeave:
    def test_member_leaves(self, login_as):
        group = make_group(name="Runde")
        bo = add_member(group)
        client = login_as(bo)
        assert "Mit einer neuen Einladung" in client.get(f"/g/{group.id}/leave").get_data(True)
        response = client.post(f"/g/{group.id}/leave")
        assert response.location == "/"
        assert "verlassen" in client.get("/").get_data(True)
        assert client.get(f"/g/{group.id}/").status_code == 404

    def test_admin_sees_successor(self, login_as):
        admin = make_user()
        group = make_group(admin)
        add_member(group, make_user(display_name="Bo"))
        html = login_as(admin).get(f"/g/{group.id}/leave").get_data(True)
        assert "geht die Rolle automatisch an Bo" in html

    def test_last_member_must_type_the_name(self, login_as):
        admin = make_user()
        group = make_group(admin, "Runde")
        group_id = group.id
        client = login_as(admin)
        html = client.get(f"/g/{group.id}/leave").get_data(True)
        assert "letzte Mitglied" in html
        assert 'name="confirmation"' in html
        assert client.post(f"/g/{group.id}/leave", data={"confirmation": "x"}).status_code == 400
        response = client.post(f"/g/{group.id}/leave", data={"confirmation": "Runde"})
        assert response.location == "/"
        assert "gelöscht" in client.get("/").get_data(True)
        db.session.expire_all()
        assert db.session.get(Group, group_id) is None


class TestDelete:
    def test_delete_with_confirmation(self, login_as):
        admin = make_user()
        group = make_group(admin, "Runde")
        group_id = group.id
        add_member(group)
        client = login_as(admin)
        assert "endgültig" in client.get(f"/g/{group.id}/delete").get_data(True)
        wrong = client.post(f"/g/{group.id}/delete", data={"confirmation": "runde"})
        assert wrong.status_code == 400
        assert "stimmt nicht" in wrong.get_data(True)
        response = client.post(f"/g/{group.id}/delete", data={"confirmation": "Runde"})
        assert response.location == "/"
        db.session.expire_all()
        assert db.session.get(Group, group_id) is None
