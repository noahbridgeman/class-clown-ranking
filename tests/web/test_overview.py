"""Pages of the voting overview and the member detail view (OVW-01…07, A23)."""

from datetime import timedelta

import pytest

from app.extensions import db
from app.services import membership, voting
from tests.factories import (
    IN_WEEK_WINDOW,
    WEEK_CLOSES,
    add_member,
    make_group,
    make_user,
    tick,
    vote,
)

WEEK = timedelta(days=7)


@pytest.fixture
def trio(app, clock):
    a, b, c = (make_user(display_name=name) for name in ("Ada", "Bo", "Cleo"))
    group = make_group(a, "Runde")
    add_member(group, b)
    add_member(group, c)
    return group, a, b, c


def run_week(clock, group, votes, week: int = 0, anonymous: bool = True, reasons=()) -> None:
    group.is_anonymous = anonymous
    db.session.commit()
    clock.set(IN_WEEK_WINDOW + week * WEEK)
    tick()
    for voter, target, choice in votes:
        vote(group, voter, target, choice)
    for voter, target, text in reasons:
        voting.set_reason(group, voter, target.id, text)
    clock.set(WEEK_CLOSES + week * WEEK)
    tick()


def get(client, url: str) -> str:
    response = client.get(url)
    assert response.status_code == 200, url
    return response.get_data(as_text=True)


class TestOverview:
    def test_ranking_links_to_it_once_there_are_results(self, trio, clock, login_as):
        group, a, b, _c = trio
        client = login_as(a)
        assert "Voting-Übersicht" not in get(client, f"/g/{group.id}/")
        run_week(clock, group, [(a, b, "up")])
        assert f'href="/g/{group.id}/overview"' in get(client, f"/g/{group.id}/")

    def test_empty_before_the_first_window(self, trio, login_as):
        group, a, _b, _c = trio
        html = get(login_as(a), f"/g/{group.id}/overview")
        assert "Noch gab es kein Voting" in html
        assert login_as(a).get(f"/g/{group.id}/overview/1").status_code == 404

    def test_running_period_shows_no_results(self, trio, clock, login_as):
        """OVW-06, OVW-07."""
        group, a, b, c = trio
        clock.set(IN_WEEK_WINDOW)
        tick()
        vote(group, a, b, "up")
        vote(group, c, a, "down")
        html = get(login_as(a), f"/g/{group.id}/overview")
        assert "Läuft bis" in html and "Nur für dich sichtbar" in html
        assert 'vote-chip-up">Bo' in html and 'vote-chip-skipped">Cleo' in html
        assert "matrix" not in html and "volume" not in html

    def test_anonymous_period_shows_counts_net_and_change(self, trio, clock, login_as):
        """OVW-02, A23."""
        group, a, b, c = trio
        run_week(clock, group, [(a, b, "up"), (c, b, "up"), (b, a, "down")])
        html = get(login_as(c), f"/g/{group.id}/overview")
        assert "ANONYM" in html.upper() and "Anonyme Runde" in html
        assert '<table class="volume">' in html and 'class="matrix"' not in html
        assert "2/0" in html and "+1,00" in html and "−1,00" in html
        assert "Cleo (du)" in html
        assert 'aria-label="2 Up, 0 Down"' in html

    def test_open_period_shows_matrix_and_reasons(self, trio, clock, login_as):
        """OVW-03, OVW-04: rows vote, columns are rated; reasons are linked from the cell."""
        group, a, b, c = trio
        run_week(
            clock,
            group,
            [(a, b, "up"), (c, b, "down")],
            anonymous=False,
            reasons=[(a, b, "Die Ente")],
        )
        html = get(login_as(c), f"/g/{group.id}/overview")
        assert 'class="matrix"' in html and "Nicht anonym" in html
        assert f'href="#reason-{a.id}-{b.id}"' in html
        assert f'id="reason-{a.id}-{b.id}"' in html and "„Die Ente“" in html
        assert "Begründungen · 1" in html
        assert html.count("vote-mark-skipped") == 4  # all but Ada→Bo and Cleo→Bo
        assert "Netto" in html and "Score Δ" in html

    def test_switcher_moves_between_periods(self, trio, clock, login_as):
        """OVW-01: the newest first, ‹ goes back."""
        group, a, b, _c = trio
        run_week(clock, group, [(a, b, "up")])
        run_week(clock, group, [(a, b, "down")], week=1, anonymous=False)
        client = login_as(a)
        newest = get(client, f"/g/{group.id}/overview")
        assert "KW 45" in newest and f'href="/g/{group.id}/overview/1"' in newest
        older = get(client, f"/g/{group.id}/overview/1")
        assert "KW 44" in older and f'href="/g/{group.id}/overview/2"' in older
        assert client.get(f"/g/{group.id}/overview/3").status_code == 404

    def test_names_link_to_the_detail_view(self, trio, clock, login_as):
        group, a, b, _c = trio
        run_week(clock, group, [(a, b, "up")])
        assert f'href="/g/{group.id}/members/{b.id}"' in get(login_as(a), f"/g/{group.id}/overview")


class TestMemberPage:
    def test_shows_results_votes_and_reasons(self, trio, clock, login_as):
        """OVW-05."""
        group, a, b, c = trio
        run_week(clock, group, [(a, b, "up"), (b, c, "down")])
        run_week(
            clock,
            group,
            [(a, b, "down"), (b, a, "up")],
            week=1,
            anonymous=False,
            reasons=[(a, b, "Zu laut")],
        )
        html = get(login_as(c), f"/g/{group.id}/members/{b.id}")
        assert "Runden · 2" in html and 'class="score-chart"' in html
        assert "Erhaltene Begründungen" in html and "„Zu laut“" in html
        assert "Abgegebene Votes" in html and 'vote-chip-up">Ada' in html
        assert 'vote-chip-down">Cleo' not in html  # Bo's vote in the anonymous week

    def test_own_page_shows_own_anonymous_votes(self, trio, clock, login_as):
        """OVW-07."""
        group, _a, b, c = trio
        run_week(clock, group, [(b, c, "down")])
        html = get(login_as(b), f"/g/{group.id}/members/{b.id}")
        assert "Nur für dich sichtbar" in html and 'vote-chip-down">Cleo' in html

    def test_former_members_and_strangers(self, trio, clock, login_as):
        group, a, b, _c = trio
        run_week(clock, group, [(a, b, "up")])
        membership.leave(group, b)
        client = login_as(a)
        assert "Ausgetreten" in get(client, f"/g/{group.id}/members/{b.id}")
        stranger = make_user()
        assert client.get(f"/g/{group.id}/members/{stranger.id}").status_code == 404

    def test_member_without_results(self, trio, login_as):
        group, a, b, _c = trio
        html = get(login_as(a), f"/g/{group.id}/members/{b.id}")
        assert "Noch kein Ergebnis" in html and "score-chart" not in html
