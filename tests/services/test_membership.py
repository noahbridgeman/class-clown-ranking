from datetime import timedelta

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Group, Membership, MembershipEvent, MembershipEventKind
from app.services import membership
from app.services.errors import InvalidInput, NotAllowed, NotFound
from tests.factories import add_member, make_group, make_user


def events(group: Group) -> list[tuple[MembershipEventKind, int, int | None]]:
    rows = db.session.scalars(
        select(MembershipEvent)
        .where(MembershipEvent.group_id == group.id)
        .order_by(MembershipEvent.id)
    )
    return [(row.kind, row.user_id, row.actor_user_id) for row in rows]


def assert_single_active_admin(group: Group) -> None:
    """ROL-01: exactly one admin, and the admin is an active member."""
    db.session.refresh(group)
    assert membership.active_membership(group.id, group.admin_user_id) is not None


class TestJoin:
    def test_colors_are_assigned_in_order(self, app):
        group = make_group()
        members = [add_member(group) for _ in range(3)]
        indexes = [membership.active_membership(group.id, m.id).color_index for m in members]
        assert indexes == [1, 2, 3]

    def test_rejoin_reuses_the_row_color_and_first_join(self, app, clock):
        group = make_group()
        user = add_member(group)
        before = membership.active_membership(group.id, user.id)
        first_joined, color = before.first_joined_at, before.color_index
        clock.advance(timedelta(days=3))
        membership.leave(group, user)
        clock.advance(timedelta(days=3))
        add_member(group, user)
        after = membership.active_membership(group.id, user.id)
        assert after.id == before.id
        assert after.color_index == color
        assert after.first_joined_at == first_joined
        assert after.joined_at == clock.now()
        assert events(group)[-2:] == [
            (MembershipEventKind.LEFT, user.id, user.id),
            (MembershipEventKind.REJOINED, user.id, user.id),
        ]

    def test_colors_of_former_members_are_not_reused(self, app):
        group = make_group()
        leaver = add_member(group)
        membership.leave(group, leaver)
        newcomer = add_member(group)
        assert membership.active_membership(group.id, newcomer.id).color_index == 2

    def test_joining_twice_changes_nothing(self, app):
        group = make_group()
        user = add_member(group)
        add_member(group, user)
        rows = db.session.scalars(select(Membership).where(Membership.user_id == user.id)).all()
        assert len(rows) == 1
        assert [kind for kind, *_ in events(group)].count(MembershipEventKind.JOINED) == 2


class TestLeave:
    def test_member_leaves(self, app, clock):
        group = make_group()
        user = add_member(group)
        membership.leave(group, user)
        assert membership.active_membership(group.id, user.id) is None
        row = db.session.scalar(select(Membership).where(Membership.user_id == user.id))
        assert row.left_at == clock.now()
        assert_single_active_admin(group)

    def test_admin_hands_over_to_earliest_member(self, app, clock, outbox):
        admin = make_user()
        group = make_group(admin)
        clock.advance(timedelta(days=1))
        earliest = add_member(group)
        clock.advance(timedelta(days=1))
        add_member(group)
        membership.leave(group, admin)
        assert group.admin_user_id == earliest.id
        assert events(group)[-1] == (MembershipEventKind.ADMIN_TRANSFERRED, earliest.id, None)
        assert [mail.to for mail in outbox] == [earliest.email]
        assert "Admin" in outbox[0].subject
        assert_single_active_admin(group)

    def test_first_join_counts_not_the_latest_rejoin(self, app, clock):
        admin = make_user()
        group = make_group(admin)
        clock.advance(timedelta(days=1))
        veteran = add_member(group)
        clock.advance(timedelta(days=1))
        other = add_member(group)
        clock.advance(timedelta(days=1))
        membership.leave(group, veteran)
        add_member(group, veteran)  # A4: first_joined_at stays day 1
        membership.leave(group, admin)
        assert group.admin_user_id == veteran.id
        assert group.admin_user_id != other.id

    def test_tie_goes_to_the_older_membership(self, app):
        admin = make_user()
        group = make_group(admin)
        first, _second = add_member(group), add_member(group)  # same clock time
        membership.leave(group, admin)
        assert group.admin_user_id == first.id

    def test_last_member_cannot_simply_leave(self, app):
        admin = make_user()
        group = make_group(admin)
        with pytest.raises(InvalidInput) as error:
            membership.leave(group, admin)
        assert error.value.message_key == "groups.last_member"
        assert_single_active_admin(group)

    def test_non_member_cannot_leave(self, app):
        group = make_group()
        with pytest.raises(NotFound):
            membership.leave(group, make_user())


class TestRemove:
    def test_admin_removes_member(self, app, clock):
        admin = make_user()
        group = make_group(admin)
        user = add_member(group)
        membership.remove(group, admin, user.id)
        assert membership.active_membership(group.id, user.id) is None
        assert events(group)[-1] == (MembershipEventKind.REMOVED, user.id, admin.id)

    def test_member_cannot_remove(self, app):
        group = make_group()
        user, other = add_member(group), add_member(group)
        with pytest.raises(NotAllowed):
            membership.remove(group, user, other.id)
        assert membership.active_membership(group.id, other.id) is not None

    def test_admin_cannot_remove_self(self, app):
        admin = make_user()
        group = make_group(admin)
        with pytest.raises(InvalidInput):
            membership.remove(group, admin, admin.id)
        assert_single_active_admin(group)

    @pytest.mark.parametrize("who", ["stranger", "former", "unknown"])
    def test_only_active_members_can_be_removed(self, app, who):
        admin = make_user()
        group = make_group(admin)
        if who == "stranger":
            target = make_user().id
        elif who == "former":
            target = add_member(group).id
            membership.remove(group, admin, target)
        else:
            target = 9999
        with pytest.raises(NotFound):
            membership.remove(group, admin, target)

    def test_member_of_another_group_cannot_be_removed(self, app):
        admin = make_user()
        group = make_group(admin)
        outsider = add_member(make_group())
        with pytest.raises(NotFound):
            membership.remove(group, admin, outsider.id)

    def test_former_admin_has_no_admin_rights(self, app):
        admin = make_user()
        group = make_group(admin)
        heir = add_member(group)
        victim = add_member(group)
        membership.leave(group, admin)
        add_member(group, admin)
        assert group.admin_user_id == heir.id
        with pytest.raises(NotAllowed):
            membership.remove(group, admin, victim.id)
