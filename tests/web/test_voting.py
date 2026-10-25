import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Vote
from tests.factories import (
    IN_WEEK_WINDOW,
    WEEK_CLOSES,
    add_member,
    make_group,
    make_user,
    tick,
    vote,
)

HTMX = {"HX-Request": "true"}


@pytest.fixture
def trio(app, clock):
    a, b, c = (make_user(display_name=name) for name in ("Ada", "Bo", "Cleo"))
    group = make_group(a, "Runde")
    add_member(group, b)
    add_member(group, c)
    clock.set(IN_WEEK_WINDOW)
    tick()
    return group, a, b, c


def page(client, group, headers=None) -> str:
    return client.get(f"/g/{group.id}/vote", headers=headers or {}).get_data(as_text=True)


class TestPage:
    def test_lists_the_others_with_progress_and_countdown(self, trio, login_as):
        """VOT-06, VOT-07."""
        group, a, _b, c = trio
        vote(group, c, a, "up")
        html = page(login_as(a), group)
        assert "Bo" in html and "Cleo" in html
        assert f"/vote/{a.id}" not in html  # no buttons for oneself (VOT-03)
        assert "Du hast 0 von 2 bewertet" in html
        assert "1 von 3 haben abgestimmt" in html
        assert "<h1>Voting offen</h1>" in html
        assert "Voting · Runde · 25./26.10." in html
        assert '<span class="cell-value">Mo 26.10., 13:00</span>' in html
        assert '<span class="cell-value">1 T 0:00 h</span>' in html
        assert "Anonym: Niemand sieht" in html
        assert html.count('class="progress-segment"') == 2

    def test_marks_own_votes(self, trio, login_as):
        group, a, b, c = trio
        vote(group, a, b, "up")
        vote(group, a, c, "down")
        html = page(login_as(a), group)
        assert html.count('aria-pressed="true"') == 2
        assert "Du hast 2 von 2 bewertet" in html
        assert html.count("progress-segment progress-done") == 2
        # Pressing a selected button again takes the vote back.
        assert html.count('value="none"') == 2

    def test_others_votes_stay_hidden(self, trio, login_as):
        """VOT-07 / NFA-06: someone else's votes leave no trace on the page."""
        group, a, b, c = trio
        vote(group, b, a, "up")
        vote(group, b, c, "down")
        html = page(login_as(c), group)
        assert 'aria-pressed="true"' not in html
        assert "1 von 3 haben abgestimmt" in html

    def test_outside_the_window_names_the_next_one(self, app, login_as):
        """VOT-10."""
        group = make_group()
        html = page(login_as(group.admin), group)
        assert "<h1>Voting geschlossen</h1>" in html
        assert "Noch gibt es keine Scores" in html
        assert "Nächstes Voting in" in html
        assert "So 25.10., 00:00 – Mo 26.10., 13:00" in html
        assert '<span class="status-countdown">1 T 10:00 h</span>' in html
        assert 'name="choice"' not in html

    def test_alone_in_the_group(self, app, clock, login_as):
        group = make_group()
        clock.set(IN_WEEK_WINDOW)
        tick()
        assert "Lade Leute in die Gruppe ein" in page(login_as(group.admin), group)

    def test_polling_returns_only_the_ballot(self, trio, login_as):
        group, a, *_ = trio
        html = page(login_as(a), group, HTMX)
        assert '<div id="ballot"' in html
        assert "<html" not in html

    def test_group_home_links_to_the_vote(self, trio, login_as):
        group, a, *_ = trio
        assert f"/g/{group.id}/vote" in login_as(a).get(f"/g/{group.id}/").get_data(True)


class TestClosedPage:
    def test_last_round_with_own_votes_and_score(self, trio, clock, login_as):
        group, a, b, c = trio
        vote(group, a, b, "up")
        vote(group, c, a, "up")
        clock.set(WEEK_CLOSES)
        tick()
        html = page(login_as(a), group)
        assert "Die neuen Scores sind seit Mo 26.10., 13:00 da" in html
        assert "Letzte Runde" in html
        assert '<span class="cell-value">1 / 2</span>' in html
        # Cleo rated Ada up, but it is her first result: a score without a change yet.
        assert re.search(r'Dein Score</span>\s*<span class="cell-value">\d,\d</span>', html)

    def test_shows_the_scores_next_to_the_names(self, trio, clock, login_as):
        group, a, b, _c = trio
        vote(group, a, b, "up")
        clock.set(WEEK_CLOSES)
        tick()
        clock.set(IN_WEEK_WINDOW + timedelta(days=7))
        tick()
        html = page(login_as(a), group)
        assert re.search(
            r'<span class="ballot-name">Bo</span>\s*<span class="ballot-score">\d,\d', html
        )


class TestCast:
    def test_htmx_vote_swaps_the_ballot(self, trio, login_as):
        group, a, b, _ = trio
        response = login_as(a).post(
            f"/g/{group.id}/vote/{b.id}", data={"choice": "up"}, headers=HTMX
        )
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "<html" not in html
        assert "Du hast 1 von 2 bewertet" in html
        assert db.session.scalar(select(Vote.value)) == 1

    def test_without_javascript_redirects_back(self, trio, login_as):
        group, a, b, _ = trio
        client = login_as(a)
        response = client.post(f"/g/{group.id}/vote/{b.id}", data={"choice": "down"})
        assert response.location == f"/g/{group.id}/vote"
        client.post(f"/g/{group.id}/vote/{b.id}", data={"choice": "none"})
        assert db.session.scalars(select(Vote)).all() == []

    def test_self_vote_shows_a_message(self, trio, login_as):
        group, a, *_ = trio
        response = login_as(a).post(
            f"/g/{group.id}/vote/{a.id}", data={"choice": "up"}, headers=HTMX
        )
        assert response.status_code == 400
        assert "Dich selbst kannst du nicht bewerten." in response.get_data(True)

    def test_invalid_choice(self, trio, login_as):
        group, a, b, _ = trio
        response = login_as(a).post(
            f"/g/{group.id}/vote/{b.id}", data={"choice": "sideways"}, headers=HTMX
        )
        assert response.status_code == 400
        assert "Ungültige Auswahl." in response.get_data(True)

    def test_late_vote_is_refused(self, trio, clock, login_as):
        """PER-03."""
        group, a, b, _ = trio
        clock.set(WEEK_CLOSES + timedelta(seconds=1))
        response = login_as(a).post(
            f"/g/{group.id}/vote/{b.id}", data={"choice": "up"}, headers=HTMX
        )
        assert response.status_code == 400
        assert "Das Voting ist zu Ende" in response.get_data(True)
        assert db.session.scalars(select(Vote)).all() == []


def test_vote_with_csrf_token(csrf_app):
    """TestConfig disables CSRF, so the ballot runs once with it switched on."""
    from tests.web.test_auth import csrf_token

    csrf_app.extensions["clock"].set(IN_WEEK_WINDOW)
    admin = make_user()
    group = make_group(admin)
    other = add_member(group)
    tick()
    client = csrf_app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = admin.get_id()
    url = f"/g/{group.id}/vote/{other.id}"
    page = client.get(f"/g/{group.id}/vote").get_data(True)
    assert client.post(url, data={"choice": "up"}).status_code == 400
    response = client.post(url, data={"choice": "up", "csrf_token": csrf_token(page)})
    assert response.status_code == 302
    assert db.session.scalar(select(Vote.value)) == 1


class TestReasons:
    @pytest.fixture
    def open_trio(self, app, clock):
        a, b, c = (make_user(display_name=name) for name in ("Ada", "Bo", "Cleo"))
        group = make_group(a, "Runde")
        group.is_anonymous = False
        add_member(group, b)
        add_member(group, c)
        clock.set(IN_WEEK_WINDOW)
        tick()
        return group, a, b, c

    def test_field_appears_after_voting_in_open_periods(self, open_trio, login_as):
        group, a, b, _c = open_trio
        client = login_as(a)
        assert 'name="reason"' not in page(client, group)
        vote(group, a, b, "up")
        html = page(client, group)
        assert html.count('name="reason"') == 1
        assert f'id="reason-{b.id}"' in html and "hx-preserve" in html

    def test_no_field_in_anonymous_periods(self, trio, login_as):
        group, a, b, _c = trio
        vote(group, a, b, "up")
        assert 'name="reason"' not in page(login_as(a), group)

    def test_saving_with_htmx_shows_it(self, open_trio, login_as):
        group, a, b, _c = open_trio
        vote(group, a, b, "up")
        response = login_as(a).post(
            f"/g/{group.id}/vote/{b.id}/reason", data={"reason": "Ente"}, headers=HTMX
        )
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'value="Ente"' in html and "Begründung gespeichert." in html

    def test_too_long_is_refused(self, open_trio, login_as):
        group, a, b, _c = open_trio
        vote(group, a, b, "up")
        response = login_as(a).post(
            f"/g/{group.id}/vote/{b.id}/reason", data={"reason": "x" * 141}, headers=HTMX
        )
        assert response.status_code == 400
        assert "Höchstens 140 Zeichen." in response.get_data(as_text=True)

    def test_without_javascript_redirects_back(self, open_trio, login_as):
        group, a, b, _c = open_trio
        vote(group, a, b, "up")
        response = login_as(a).post(f"/g/{group.id}/vote/{b.id}/reason", data={"reason": "Ente"})
        assert response.location == f"/g/{group.id}/vote"


def test_reason_without_csrf_token_is_refused_with_a_message(csrf_app):
    csrf_app.extensions["clock"].set(IN_WEEK_WINDOW)
    admin = make_user()
    group = make_group(admin)
    group.is_anonymous = False
    other = add_member(group)
    tick()
    vote(group, admin, other, "up")
    client = csrf_app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = admin.get_id()
    response = client.post(
        f"/g/{group.id}/vote/{other.id}/reason", data={"reason": "x"}, headers=HTMX
    )
    assert response.status_code == 400
    assert "Bitte lade die Seite neu" in response.get_data(as_text=True)
