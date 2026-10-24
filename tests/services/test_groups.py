from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.domain.scoring import DEFAULT_WEEKLY_PARAMS
from app.domain.types import Cadence
from app.extensions import db
from app.models import Group, Invitation, Membership, MembershipEvent, MembershipEventKind, User
from app.services import groups, invitations, membership
from app.services.errors import InvalidInput, NotAllowed, NotFound
from tests.factories import add_member, make_group, make_user


def count(model: type) -> int:
    return db.session.scalar(select(func.count()).select_from(model))


class TestCreate:
    def test_defaults(self, app, clock):
        group = groups.create_group(make_user(), "  Die   Runde ")
        assert group.name == "Die Runde"
        assert group.cadence is Cadence.WEEKLY
        assert group.is_anonymous is True
        assert group.timezone == "Europe/Berlin"
        assert (group.k, group.d) == (DEFAULT_WEEKLY_PARAMS.k, DEFAULT_WEEKLY_PARAMS.d)
        assert group.created_at == clock.now()

    def test_creator_is_admin_and_first_member(self, app, clock):
        user = make_user()
        group = groups.create_group(user, "Runde")
        assert group.admin_user_id == user.id
        member = membership.active_membership(group.id, user.id)
        assert member.color_index == 0
        assert member.first_joined_at == member.joined_at == clock.now()
        event = db.session.scalar(select(MembershipEvent))
        assert (event.kind, event.user_id) == (MembershipEventKind.JOINED, user.id)

    @pytest.mark.parametrize(
        ("raw", "key"),
        [
            ("", "validation.name_required"),
            ("x" * 61, "validation.name_too_long"),
            ("​", "validation.name_invalid"),
        ],
    )
    def test_invalid_names(self, app, raw, key):
        with pytest.raises(InvalidInput) as error:
            groups.create_group(make_user(), raw)
        assert error.value.message_key == key
        assert count(Group) == 0

    def test_three_new_groups_per_day(self, app, clock):
        user = make_user()
        for number in range(3):
            groups.create_group(user, f"G{number}")
        with pytest.raises(InvalidInput) as error:
            groups.create_group(user, "G3")
        assert error.value.message_key == "groups.rate_limited"
        clock.advance(timedelta(days=1))
        assert groups.create_group(user, "G3")

    def test_creation_limit_follows_the_creator_not_the_admin(self, app):
        user = make_user()
        for number in range(3):
            group = groups.create_group(user, f"G{number}")
            heir = add_member(group)
            groups.transfer_admin(group, user, heir.id)
        with pytest.raises(InvalidInput):
            groups.create_group(user, "G3")

    def test_sixty_characters_are_fine(self, app):
        assert groups.create_group(make_user(), "x" * 60).name == "x" * 60


class TestGroupsOf:
    def test_lists_active_memberships_by_name(self, app):
        user = make_user()
        b = make_group(user, "Beta")
        a = make_group(user, "Alpha")
        left = make_group(name="Gamma")
        add_member(left, user)
        membership.leave(left, user)
        make_group(name="Fremd")
        assert groups.groups_of(user) == [a, b]


class TestTransferAdmin:
    def test_moves_the_role_and_mails_the_new_admin(self, app, outbox):
        admin = make_user()
        group = make_group(admin, "Runde")
        heir = add_member(group)
        groups.transfer_admin(group, admin, heir.id)
        assert group.admin_user_id == heir.id
        event = db.session.scalars(select(MembershipEvent).order_by(MembershipEvent.id)).all()[-1]
        assert (event.kind, event.user_id, event.actor_user_id) == (
            MembershipEventKind.ADMIN_TRANSFERRED,
            heir.id,
            admin.id,
        )
        assert [mail.to for mail in outbox] == [heir.email]
        assert "„Runde“" in outbox[0].subject
        assert f"/g/{group.id}" in outbox[0].body

    def test_old_admin_stays_member(self, app):
        admin = make_user()
        group = make_group(admin)
        heir = add_member(group)
        groups.transfer_admin(group, admin, heir.id)
        assert membership.active_membership(group.id, admin.id) is not None

    def test_only_the_admin_may_transfer(self, app):
        group = make_group()
        member, other = add_member(group), add_member(group)
        with pytest.raises(NotAllowed):
            groups.transfer_admin(group, member, other.id)

    def test_target_must_be_an_active_member(self, app):
        admin = make_user()
        group = make_group(admin)
        with pytest.raises(NotFound):
            groups.transfer_admin(group, admin, make_user().id)

    def test_cannot_transfer_to_self(self, app):
        admin = make_user()
        group = make_group(admin)
        with pytest.raises(InvalidInput):
            groups.transfer_admin(group, admin, admin.id)

    def test_mail_failure_keeps_the_transfer(self, app, monkeypatch):
        admin = make_user()
        group = make_group(admin)
        heir = add_member(group)

        def fail(_mail):
            raise OSError("SMTP down")

        monkeypatch.setattr("app.services.mail.send", fail)
        groups.transfer_admin(group, admin, heir.id)
        db.session.expire_all()
        assert db.session.get(Group, group.id).admin_user_id == heir.id


class TestDelete:
    def test_removes_all_group_data_but_keeps_users(self, app):
        admin = make_user()
        group = make_group(admin, "Runde")
        add_member(group)
        invitations.invite(group, admin, "neu@example.org")
        other = make_group(name="Andere")
        users_before = count(User)
        groups.delete_group(group, admin, "Runde")
        db.session.expire_all()
        assert db.session.get(Group, group.id) is None
        assert db.session.scalars(select(Membership.group_id)).all() == [other.id]
        assert db.session.scalars(select(MembershipEvent.group_id)).all() == [other.id]
        assert count(Invitation) == 0
        assert count(User) == users_before

    @pytest.mark.parametrize("confirmation", [None, "", "runde", "Rund", "Runde!"])
    def test_needs_the_exact_name(self, app, confirmation):
        admin = make_user()
        group = make_group(admin, "Runde")
        with pytest.raises(InvalidInput):
            groups.delete_group(group, admin, confirmation)
        assert db.session.get(Group, group.id) is not None

    def test_only_the_admin_may_delete(self, app):
        group = make_group(name="Runde")
        member = add_member(group)
        with pytest.raises(NotAllowed):
            groups.delete_group(group, member, "Runde")

    def test_foreign_keys_are_enforced(self, app):
        """Cascades rely on SQLite's foreign key support being switched on."""
        assert db.session.execute(db.text("PRAGMA foreign_keys")).scalar() == 1


class TestLeaveGroup:
    def test_member_leaves(self, app):
        group = make_group()
        bo = add_member(group)
        assert groups.leave_group(group, bo) is groups.LeaveResult.LEFT
        assert membership.active_membership(group.id, bo.id) is None

    def test_last_member_needs_confirmation(self, app):
        admin = make_user()
        group = make_group(admin, name="Die Runde")
        with pytest.raises(InvalidInput) as error:
            groups.leave_group(group, admin, "falsch")
        assert error.value.message_key == "groups.confirmation_mismatch"
        assert db.session.get(Group, group.id) is not None

    def test_last_member_leaving_deletes_the_group(self, app):
        admin = make_user()
        group = make_group(admin, name="Die Runde")
        group_id = group.id
        result = groups.leave_group(group, admin, " Die  Runde ")
        assert result is groups.LeaveResult.GROUP_DELETED
        db.session.expire_all()
        assert db.session.get(Group, group_id) is None

    def test_non_member(self, app):
        with pytest.raises(NotFound):
            groups.leave_group(make_group(), make_user())
