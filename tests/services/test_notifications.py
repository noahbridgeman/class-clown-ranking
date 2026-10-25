"""Which pushes the period update and the requests send, and to whom (section 11, A24)."""

from dataclasses import replace
from datetime import timedelta

import pytest

from app.extensions import db
from app.models import NotificationKind
from app.services import groups, membership, push, settings, voting
from tests.factories import (
    IN_WEEK_WINDOW,
    WEEK_CLOSES,
    WEEK_OPENS,
    add_member,
    make_group,
    make_user,
    tick,
    vote,
)
from tests.services.test_push import AUTH, KEY

REMINDER_AT = WEEK_CLOSES - timedelta(hours=2)


@pytest.fixture
def outbox(app):
    return app.extensions["push"].outbox


def subscribe(user) -> str:
    url = f"https://fcm.googleapis.com/fcm/send/{user.display_name}-{user.id}"
    push.subscribe(user, url, KEY, AUTH)
    return url


@pytest.fixture
def trio(app):
    a, b, c = (make_user(display_name=name) for name in ("Ada", "Bo", "Cleo"))
    group = make_group(a, "Runde")
    add_member(group, b)
    add_member(group, c)
    endpoints = {u.display_name: subscribe(u) for u in (a, b, c)}
    return group, a, b, c, endpoints


def received(outbox, endpoints) -> dict[str, list[str]]:
    """Name → bodies of the pushes that reached that person, in order."""
    by_endpoint = {url: name for name, url in endpoints.items()}
    result: dict[str, list[str]] = {}
    for url, message in outbox:
        result.setdefault(by_endpoint[url], []).append(message.body)
    return result


class TestPeriodUpdate:
    def test_window_open_goes_to_everyone_once(self, trio, clock, outbox):
        group, *_users, endpoints = trio
        clock.set(WEEK_OPENS)
        report = tick()
        tick()
        assert report.pushes == 3
        got = received(outbox, endpoints)
        assert got == {name: ["Das Voting ist offen, bis Mo 26.10., 13:00."] for name in endpoints}
        assert all(m.url == f"/g/{group.id}/vote" for _, m in outbox)

    def test_reminder_two_hours_before_to_those_not_done(self, trio, clock, outbox):
        """NOT-03 and section 11: once, and only if not everyone else was rated."""
        group, a, b, c, endpoints = trio
        clock.set(IN_WEEK_WINDOW)
        tick()
        vote(group, a, b, "up")
        vote(group, a, c, "down")
        vote(group, b, a, "up")
        outbox.clear()
        clock.set(REMINDER_AT - timedelta(minutes=1))
        tick()
        assert outbox == []
        clock.set(REMINDER_AT)
        tick()
        clock.set(REMINDER_AT + timedelta(minutes=30))
        tick()
        assert received(outbox, endpoints) == {
            "Bo": ["Das Voting endet Mo 26.10., 13:00. Du hast 1 von 2 bewertet."],
            "Cleo": ["Das Voting endet Mo 26.10., 13:00. Du hast 0 von 2 bewertet."],
        }

    def test_scores_with_the_own_score_once(self, trio, clock, outbox):
        group, a, b, _c, endpoints = trio
        clock.set(IN_WEEK_WINDOW)
        tick()
        vote(group, a, b, "up")
        outbox.clear()
        clock.set(WEEK_CLOSES)
        tick()
        tick()
        got = received(outbox, endpoints)
        assert got["Bo"][0].startswith("Die neuen Scores sind da. Dein Score: ")
        assert "▲" in got["Bo"][0]
        assert all(len(bodies) == 1 for bodies in got.values())
        assert all(m.url == f"/g/{group.id}/" for _, m in outbox)

    def test_scores_of_a_period_closed_by_a_leave(self, trio, clock, outbox):
        """Plan section 5: a join or leave closes the period, the next tick announces it."""
        group, _a, _b, c, endpoints = trio
        clock.set(IN_WEEK_WINDOW)
        tick()
        outbox.clear()
        clock.set(WEEK_CLOSES + timedelta(seconds=30))
        membership.leave(group, c)  # closes the period before tick
        assert outbox == []
        tick()
        got = received(outbox, endpoints)
        assert set(got) == {"Ada", "Bo"}  # Cleo has left

    def test_who_joined_after_the_window_gets_no_scores_push(self, trio, clock, outbox):
        """A24: only members with a score of their own; the join closes the period first."""
        group, _a, _b, _c, endpoints = trio
        clock.set(IN_WEEK_WINDOW)
        tick()
        clock.set(WEEK_CLOSES + timedelta(seconds=30))
        dora = add_member(group, make_user(display_name="Dora"))
        endpoints["Dora"] = subscribe(dora)
        outbox.clear()
        tick()
        assert set(received(outbox, endpoints)) == {"Ada", "Bo", "Cleo"}

    def test_skipped_periods_announce_nothing(self, trio, clock, outbox):
        group, _a, b, c, _endpoints = trio
        clock.set(IN_WEEK_WINDOW)
        tick()
        membership.leave(group, b)
        membership.leave(group, c)
        outbox.clear()
        clock.set(WEEK_CLOSES)
        tick()
        assert outbox == []

    def test_overtaking_reaches_both_sides(self, trio, clock, outbox):
        group, a, b, c, endpoints = trio
        clock.set(IN_WEEK_WINDOW)
        tick()
        vote(group, b, a, "up")  # week 1: Ada ahead of Bo
        clock.set(WEEK_CLOSES)
        tick()
        clock.set(IN_WEEK_WINDOW + timedelta(days=7))
        tick()
        vote(group, a, b, "up")
        vote(group, c, b, "up")
        vote(group, b, a, "down")
        vote(group, c, a, "down")
        outbox.clear()
        clock.set(WEEK_CLOSES + timedelta(days=7))
        tick()
        got = received(outbox, endpoints)
        assert "Du hast Ada überholt." in got["Bo"]  # Cleo was level, not ahead
        assert "Du hast Ada überholt." in got["Cleo"]
        assert "Bo, Cleo haben dich überholt." in got["Ada"]
        assert all(m.tag == f"g{group.id}-overtaken" for _, m in outbox if "überholt" in m.body)

    def test_a_failing_push_service_does_not_repeat_or_break_the_update(
        self, trio, clock, outbox, app, monkeypatch
    ):
        _group, *_ = trio

        def broken(target, message):
            raise ConnectionError("down")

        monkeypatch.setattr(app.extensions["push"], "send", broken)
        clock.set(WEEK_OPENS)
        report = tick()
        assert report.opened == 1 and report.failed == [] and report.pushes == 0
        monkeypatch.undo()
        tick()
        assert outbox == []  # flagged already: at most once (NOT-03)


class TestNoVotesInPushes:
    """NOT-04: swapping who voted how changes no push, in either mode."""

    @pytest.mark.parametrize("anonymous", [True, False])
    def test_swapped_votes_give_the_same_pushes(self, app, clock, anonymous):
        start = clock.now()
        outbox = app.extensions["push"].outbox
        seen = []
        for swap in (False, True):
            clock.set(start)
            db.session.remove()
            db.drop_all()
            db.create_all()
            outbox.clear()
            names = ("Ada", "Bo", "Cleo", "Dora")
            users = {n: make_user(display_name=n) for n in names}
            group = make_group(users["Ada"])
            group.is_anonymous = anonymous
            db.session.commit()
            for n in names[1:]:
                add_member(group, users[n])
            for user in users.values():
                subscribe(user)
            clock.set(IN_WEEK_WINDOW)
            tick()
            first, second = ("down", "up") if swap else ("up", "down")
            # Ada rates everyone, Bo only Cleo: the reminder goes to Bo, Cleo and Dora.
            vote(group, users["Ada"], users["Bo"], "up")
            vote(group, users["Ada"], users["Dora"], "down")
            vote(group, users["Ada"], users["Cleo"], first)
            vote(group, users["Bo"], users["Cleo"], second)
            if not anonymous:
                voting.set_reason(group, users["Ada"], users["Cleo"].id, "Die Ente")
            for moment in (REMINDER_AT, WEEK_CLOSES):
                clock.set(moment)
                tick()
            assert not any("Ente" in m.body for _, m in outbox)
            reminded = {url for url, m in outbox if "endet" in m.body}
            assert len(reminded) == 3
            seen.append(list(outbox))
        assert seen[0] == seen[1]


class TestFromRequests:
    def test_settings_change_reaches_everyone_but_the_admin(self, trio, clock, outbox):
        group, a, _b, _c, endpoints = trio
        wanted = replace(settings.upcoming(group), is_anonymous=False, name="Neue Runde")
        settings.change(group, a, wanted)
        got = received(outbox, endpoints)
        assert set(got) == {"Bo", "Cleo"}
        assert got["Bo"] == [
            "Neue Einstellungen (Name der Gruppe, Anonymität), gültig ab So 25.10., 00:00."
        ]

    def test_saving_without_changes_sends_nothing(self, trio, outbox):
        group, a, *_ = trio
        settings.change(group, a, settings.upcoming(group))
        assert outbox == []

    def test_new_admin_by_transfer_and_by_leaving(self, trio, outbox):
        """ROL-02, ROL-03: push besides the mail."""
        group, a, b, _c, endpoints = trio
        groups.transfer_admin(group, a, b.id)
        membership.leave(group, b)  # the role goes on to the longest-standing member
        got = received(outbox, endpoints)
        assert got == {
            "Bo": ["Du bist jetzt Admin der Gruppe."],
            "Ada": ["Du bist jetzt Admin der Gruppe."],
        }
        assert all(m.url == f"/g/{group.id}/settings" for _, m in outbox)

    def test_switched_off_admin_push_still_mails(self, trio, outbox, app):
        group, a, b, _c, _endpoints = trio
        push.set_preferences(b, group.id, set(NotificationKind) - {NotificationKind.ADMIN_GRANTED})
        groups.transfer_admin(group, a, b.id)
        assert outbox == []
        assert app.extensions["mail"].outbox[-1].to == b.email
