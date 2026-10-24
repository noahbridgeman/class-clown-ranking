import re
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import InvitationStatus, User
from app.services import groups, invitations, membership
from app.services.errors import InvalidInput, NotAllowed, NotFound
from app.services.mail import Mail
from tests.factories import add_member, allow, make_group, make_user

LINK = re.compile(r"http://localhost:5000/invite/(\S+)")


def token(outbox: list[Mail]) -> str:
    return LINK.search(outbox[-1].body).group(1)


def count_users() -> int:
    return db.session.scalar(select(func.count()).select_from(User))


@pytest.fixture
def admin(app) -> User:
    return make_user("admin@example.org", display_name="Ada")


@pytest.fixture
def group(admin):
    return make_group(admin, "Runde")


class TestInvite:
    def test_creates_open_invitation_and_mails_link(self, group, admin, outbox, clock):
        sent = invitations.invite(group, admin, " Neu@Example.org ")
        invitation = sent.invitation
        assert sent.mail_sent
        assert invitation.email == "neu@example.org"
        assert invitation.status(clock.now()) is InvitationStatus.OPEN
        assert invitation.expires_at == clock.now() + timedelta(days=7)
        assert invitation.invited_by_user_id == admin.id
        (mail,) = outbox
        assert mail.to == "neu@example.org"
        assert mail.subject == "Ada lädt dich in „Runde“ ein"
        assert "7 Tage" in mail.body
        assert invitation.nonce_hash not in mail.body

    def test_only_the_admin_may_invite(self, group, outbox):
        member = add_member(group)
        with pytest.raises(NotAllowed):
            invitations.invite(group, member, "neu@example.org")
        assert outbox == []

    def test_active_member_cannot_be_invited(self, group, admin):
        add_member(group, make_user("bo@example.org"))
        with pytest.raises(InvalidInput) as error:
            invitations.invite(group, admin, "BO@example.org")
        assert error.value.message_key == "invitations.already_member"

    def test_own_address_counts_as_member(self, group, admin):
        with pytest.raises(InvalidInput):
            invitations.invite(group, admin, "admin@example.org")

    def test_former_member_can_be_invited(self, group, admin):
        former = add_member(group, make_user("bo@example.org"))
        membership.remove(group, admin, former.id)
        assert invitations.invite(group, admin, "bo@example.org").invitation

    def test_one_open_invitation_per_address(self, group, admin, outbox):
        invitations.invite(group, admin, "neu@example.org")
        with pytest.raises(InvalidInput) as error:
            invitations.invite(group, admin, "neu@example.org")
        assert error.value.message_key == "invitations.already_invited"
        assert len(outbox) == 1

    def test_same_address_in_another_group_is_independent(self, group, admin):
        invitations.invite(group, admin, "neu@example.org")
        other = make_group(admin, "Andere")
        assert invitations.invite(other, admin, "neu@example.org").invitation

    def test_inviting_an_expired_address_sends_the_old_invitation_again(
        self, group, admin, outbox, clock
    ):
        first = invitations.invite(group, admin, "neu@example.org").invitation
        old_link = token(outbox)
        clock.advance(timedelta(days=8))
        again = invitations.invite(group, admin, "neu@example.org").invitation
        assert again.id == first.id
        assert again.status(clock.now()) is InvitationStatus.OPEN
        assert invitations.find_open(old_link) is None
        assert invitations.find_open(token(outbox)).id == first.id

    def test_invalid_address(self, group, admin):
        with pytest.raises(InvalidInput):
            invitations.invite(group, admin, "kein-at")

    def test_mail_failure_is_reported(self, group, admin, monkeypatch):
        def fail(_mail):
            raise OSError("SMTP down")

        monkeypatch.setattr("app.services.mail.send", fail)
        sent = invitations.invite(group, admin, "neu@example.org")
        assert sent.mail_sent is False
        assert sent.invitation.id is not None


class TestGroupSize:
    """A8: members plus open invitations stay within 30."""

    def fill(self, group, members: int, invited: int, admin) -> None:
        for _ in range(members - 1):
            add_member(group)
        for number in range(invited):
            invitations.invite(group, admin, f"gast{number}@example.org")

    def test_thirtieth_seat_can_be_offered(self, group, admin):
        self.fill(group, members=20, invited=9, admin=admin)
        assert invitations.invite(group, admin, "letzte@example.org").invitation

    def test_full_group_refuses_more(self, group, admin):
        self.fill(group, members=20, invited=10, admin=admin)
        with pytest.raises(InvalidInput) as error:
            invitations.invite(group, admin, "zuviel@example.org")
        assert error.value.message_key == "invitations.group_full"
        assert "30" in error.value.message()

    def test_revoking_frees_a_seat(self, group, admin):
        self.fill(group, members=29, invited=1, admin=admin)
        pending = invitations.invitations_of(group)[0]
        invitations.revoke(group, admin, pending.id)
        assert invitations.invite(group, admin, "neu@example.org").invitation

    def test_expired_invitations_free_their_seat_until_resent(self, group, admin, clock):
        self.fill(group, members=29, invited=1, admin=admin)
        expired = invitations.invitations_of(group)[0]
        clock.advance(timedelta(days=8))
        invitations.invite(group, admin, "neu@example.org")
        with pytest.raises(InvalidInput) as error:
            invitations.resend(group, admin, expired.id)
        assert error.value.message_key == "invitations.group_full"


class TestRateLimits:
    def test_resend_needs_a_pause(self, group, admin, clock):
        invitation = invitations.invite(group, admin, "neu@example.org").invitation
        clock.advance(timedelta(minutes=10) - timedelta(seconds=1))
        with pytest.raises(InvalidInput) as error:
            invitations.resend(group, admin, invitation.id)
        assert error.value.message_key == "invitations.resend_too_soon"
        clock.advance(timedelta(seconds=1))
        assert invitations.resend(group, admin, invitation.id).mail_sent

    def test_at_most_five_sends_per_invitation(self, group, admin, clock, outbox):
        invitation = invitations.invite(group, admin, "neu@example.org").invitation
        for _ in range(4):
            clock.advance(timedelta(minutes=10))
            invitations.resend(group, admin, invitation.id)
        clock.advance(timedelta(minutes=10))
        with pytest.raises(InvalidInput) as error:
            invitations.resend(group, admin, invitation.id)
        assert error.value.message_key == "invitations.rate_limited"
        assert len(outbox) == 5

    def test_revoke_and_reinvite_is_limited_per_address(self, group, admin, outbox):
        for _ in range(5):
            invitation = invitations.invite(group, admin, "opfer@example.org").invitation
            invitations.revoke(group, admin, invitation.id)
        with pytest.raises(InvalidInput) as error:
            invitations.invite(group, admin, "opfer@example.org")
        assert error.value.message_key == "invitations.rate_limited"
        assert len(outbox) == 5

    def test_address_limit_spans_groups_and_inviters(self, app, outbox):
        for number in range(5):
            owner = make_user()
            invitations.invite(make_group(owner, f"G{number}"), owner, "opfer@example.org")
        owner = make_user()
        with pytest.raises(InvalidInput):
            invitations.invite(make_group(owner, "G5"), owner, "opfer@example.org")

    def test_inviter_limit_spans_their_groups(self, admin, app):
        app.config["INVITATIONS_PER_INVITER_PER_DAY"] = 4
        first, second = make_group(admin, "Eins"), make_group(admin, "Zwei")
        for number in range(2):
            invitations.invite(first, admin, f"a{number}@example.org")
            invitations.invite(second, admin, f"b{number}@example.org")
        with pytest.raises(InvalidInput) as error:
            invitations.invite(make_group(admin, "Drei"), admin, "c@example.org")
        assert error.value.message_key == "invitations.rate_limited"

    def test_inviter_limit_does_not_bind_a_co_admin(self, admin, app, group):
        app.config["INVITATIONS_PER_INVITER_PER_DAY"] = 1
        invitations.invite(group, admin, "a@example.org")
        heir = add_member(group)
        groups.transfer_admin(group, admin, heir.id)
        assert invitations.invite(group, heir, "b@example.org").invitation

    def test_address_limit_resets_after_a_day(self, group, admin, clock):
        for _ in range(5):
            invitation = invitations.invite(group, admin, "opfer@example.org").invitation
            invitations.revoke(group, admin, invitation.id)
        clock.advance(timedelta(days=1))
        assert invitations.invite(group, admin, "opfer@example.org").invitation

    def test_group_limit(self, group, admin, app):
        app.config["INVITATIONS_PER_GROUP_PER_DAY"] = 3
        for number in range(3):
            invitations.invite(group, admin, f"g{number}@example.org")
        with pytest.raises(InvalidInput) as error:
            invitations.invite(group, admin, "g3@example.org")
        assert error.value.message_key == "invitations.rate_limited"


class TestResendAndRevoke:
    def test_resend_names_the_current_admin(self, group, admin, outbox, clock):
        invitation = invitations.invite(group, admin, "neu@example.org").invitation
        heir = add_member(group, make_user(display_name="Bo"))
        groups.transfer_admin(group, admin, heir.id)
        clock.advance(timedelta(minutes=10))
        invitations.resend(group, heir, invitation.id)
        assert invitation.invited_by_user_id == heir.id
        assert outbox[-1].subject.startswith("Bo lädt dich")

    def test_resend_replaces_the_link(self, group, admin, outbox, clock):
        invitation = invitations.invite(group, admin, "neu@example.org").invitation
        old = token(outbox)
        clock.advance(timedelta(days=2))
        invitations.resend(group, admin, invitation.id)
        assert invitations.find_open(old) is None
        assert invitations.find_open(token(outbox)) == invitation
        assert invitation.expires_at == clock.now() + timedelta(days=7)
        assert invitation.send_count == 2

    def test_revoke_kills_the_link(self, group, admin, outbox, clock):
        invitation = invitations.invite(group, admin, "neu@example.org").invitation
        invitations.revoke(group, admin, invitation.id)
        assert invitation.status(clock.now()) is InvitationStatus.REVOKED
        assert invitations.find_open(token(outbox)) is None

    def test_expired_invitation_can_be_revoked(self, group, admin, clock):
        invitation = invitations.invite(group, admin, "neu@example.org").invitation
        clock.advance(timedelta(days=8))
        invitations.revoke(group, admin, invitation.id)
        assert invitation.status(clock.now()) is InvitationStatus.REVOKED

    @pytest.mark.parametrize("action", [invitations.resend, invitations.revoke])
    def test_accepted_or_revoked_cannot_change(self, group, admin, outbox, action):
        invitation = invitations.invite(group, admin, "neu@example.org").invitation
        invitations.revoke(group, admin, invitation.id)
        with pytest.raises(InvalidInput) as error:
            action(group, admin, invitation.id)
        assert error.value.message_key == "invitations.not_pending"

    @pytest.mark.parametrize("action", [invitations.resend, invitations.revoke])
    def test_invitation_of_another_group_is_not_found(self, admin, action):
        mine = make_group(admin, "Meine")
        other_admin = make_user()
        theirs = make_group(other_admin, "Fremde")
        foreign = invitations.invite(theirs, other_admin, "neu@example.org").invitation
        with pytest.raises(NotFound):
            action(mine, admin, foreign.id)
        assert foreign.revoked_at is None

    @pytest.mark.parametrize("action", [invitations.resend, invitations.revoke])
    def test_only_the_admin(self, group, admin, action):
        invitation = invitations.invite(group, admin, "neu@example.org").invitation
        with pytest.raises(NotAllowed):
            action(group, add_member(group), invitation.id)


class TestStatusList:
    def test_newest_first_with_derived_status(self, group, admin, clock):
        names = ["a", "b", "c", "d"]
        created = []
        for name in names:
            created.append(invitations.invite(group, admin, f"{name}@example.org").invitation)
            clock.advance(timedelta(minutes=1))
        invitations.revoke(group, admin, created[1].id)
        add_member(group, make_user("c-member@example.org"))
        clock.set(created[0].expires_at)
        listed = invitations.invitations_of(group)
        assert [i.email for i in listed] == [
            "d@example.org",
            "c@example.org",
            "b@example.org",
            "a@example.org",
        ]
        assert [i.status(clock.now()) for i in listed] == [
            InvitationStatus.OPEN,
            InvitationStatus.OPEN,
            InvitationStatus.REVOKED,
            InvitationStatus.EXPIRED,
        ]


class TestAccept:
    def test_new_address_gets_a_verified_account_without_allowlist(
        self, group, admin, outbox, clock
    ):
        invitations.invite(group, admin, "neu@example.org")
        clock.advance(timedelta(hours=1))
        accepted = invitations.accept(token(outbox), None)
        user = accepted.user
        assert accepted.group == group
        assert user.email == "neu@example.org"
        assert user.email_verified_at == clock.now()
        assert user.display_name is None
        assert membership.active_membership(group.id, user.id) is not None
        invitation = invitations.invitations_of(group)[0]
        assert invitation.status(clock.now()) is InvitationStatus.ACCEPTED
        assert invitation.accepted_by_user_id == user.id

    def test_existing_account_joins(self, group, admin, outbox):
        bo = make_user("bo@example.org")
        invitations.invite(group, admin, "bo@example.org")
        assert invitations.accept(token(outbox), None).user == bo
        assert count_users() == 2

    def test_logged_in_invitee_joins(self, group, admin, outbox):
        bo = make_user("bo@example.org")
        invitations.invite(group, admin, "bo@example.org")
        assert invitations.accept(token(outbox), bo).user == bo

    def test_wrong_account_is_refused_and_link_stays_valid(self, group, admin, outbox):
        invitations.invite(group, admin, "bo@example.org")
        intruder = make_user("eve@example.org")
        with pytest.raises(invitations.WrongAccount):
            invitations.accept(token(outbox), intruder)
        assert membership.active_membership(group.id, intruder.id) is None
        assert invitations.find_open(token(outbox)) is not None

    def test_link_works_only_once(self, group, admin, outbox):
        invitations.invite(group, admin, "neu@example.org")
        link = token(outbox)
        assert invitations.accept(link, None)
        assert invitations.accept(link, None) is None

    def test_expires_after_seven_days(self, group, admin, outbox, clock):
        invitations.invite(group, admin, "neu@example.org")
        clock.advance(timedelta(days=7) - timedelta(seconds=1))
        assert invitations.find_open(token(outbox)) is not None
        clock.advance(timedelta(seconds=1))
        assert invitations.accept(token(outbox), None) is None
        assert count_users() == 1

    def test_revoked_link_is_refused(self, group, admin, outbox):
        invitation = invitations.invite(group, admin, "neu@example.org").invitation
        invitations.revoke(group, admin, invitation.id)
        assert invitations.accept(token(outbox), None) is None

    @pytest.mark.parametrize("link", ["", "kaputt", "abc.def"])
    def test_garbage_links(self, app, link):
        assert invitations.accept(link, None) is None

    def test_login_token_is_not_an_invitation(self, group, admin, outbox):
        from app.services import auth

        allow("neu@example.org")
        auth.request_login("neu@example.org")
        login_token = re.search(r"/login/(\S+)", outbox[-1].body).group(1)
        assert invitations.accept(login_token, None) is None

    def test_rejoin_keeps_color(self, group, admin, outbox):
        bo = add_member(group, make_user("bo@example.org"))
        color = membership.active_membership(group.id, bo.id).color_index
        membership.leave(group, bo)
        invitations.invite(group, admin, "bo@example.org")
        invitations.accept(token(outbox), None)
        assert membership.active_membership(group.id, bo.id).color_index == color

    def test_deleted_group_invalidates_the_link(self, group, admin, outbox):
        invitations.invite(group, admin, "neu@example.org")
        groups.delete_group(group, admin, "Runde")
        assert invitations.accept(token(outbox), None) is None
