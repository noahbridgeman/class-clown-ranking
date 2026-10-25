"""Leaderboard and graph on the group page (RNK-01…04, GRA-03, GRA-08)."""

import re

import pytest

from app.services import membership
from tests.factories import (
    IN_WEEK_WINDOW,
    WEEK_CLOSES,
    add_member,
    make_daily,
    make_group,
    make_user,
    next_day,
    tick,
    vote,
)


@pytest.fixture
def daily(app):
    ada, bo, cleo = (make_user(display_name=name) for name in ("Ada", "Bo", "Cleo"))
    group = make_daily(make_group(ada))
    add_member(group, bo)
    add_member(group, cleo)
    tick()
    return group, ada, bo, cleo


def ranking_html(html: str) -> str:
    return html[html.index('<ol class="ranking"') :]


def ranked_names(html: str) -> list[str]:
    return re.findall(r'<span class="rank-name">([^<]+?)\s*[<]', ranking_html(html))


def rows(html: str) -> list[str]:
    return re.findall(r'<li class="rank.*?</li>', ranking_html(html), re.S)


class TestRanking:
    def test_before_the_first_result(self, daily, login_as):
        """INV-06: everyone at 5,0 on a shared place 01, marked new, the first voting named."""
        group, ada, *_ = daily
        html = login_as(ada).get(f"/g/{group.id}/").get_data(as_text=True)
        assert "<h1>Ranking</h1>" in html
        assert "noch kein Voting" in html
        assert ranking_html(html).count('<span class="rank-score">5,0</span>') == 3
        assert ranking_html(html).count(">Neu<") == 3
        assert re.findall(r'<span class="rank-place">(\d+)</span>', html) == ["01", "01", "01"]
        assert "Der erste Score kommt nach dem Voting" in html
        assert 'id="graph"' not in html  # nothing to draw yet

    def test_order_scores_changes_and_highlights(self, daily, clock, login_as):
        """RNK-01…03: sorted, one decimal, ▲/▼ with the change, highlight cells on top."""
        group, ada, bo, cleo = daily
        vote(group, ada, bo, "up")
        vote(group, bo, ada, "up")
        next_day(clock)
        vote(group, ada, cleo, "up")
        vote(group, bo, cleo, "up")
        vote(group, cleo, bo, "down")
        next_day(clock)
        html = login_as(ada).get(f"/g/{group.id}/").get_data(as_text=True)
        ranking = ranking_html(html)
        assert ranked_names(html) == ["Cleo", "Ada", "Bo"]
        assert "<h1>Ranking 25.10.</h1>" in html
        assert "Stand So 25.10., 13:00" in html
        assert re.search(r"▲ \d,\d", ranking) and re.search(r"▼ \d,\d", ranking)
        cell = (
            r'cell-{}">\s*<span class="cell-label">{}</span>\s*<span class="cell-value">{} {}\d,\d'
        )
        assert re.search(cell.format("up", "Größter Anstieg", "Cleo", "▲"), html)
        assert re.search(cell.format("down", "Größter Absturz", "Bo", "▼"), html)
        # A22: "best score so far" goes before the biggest gain.
        assert "rank-label-best" in rows(html)[0]
        assert "rank-label-drop" in rows(html)[2]

    def test_weekly_heading_names_the_calendar_week(self, app, clock, login_as):
        ada, bo = make_user(display_name="Ada"), make_user(display_name="Bo")
        group = make_group(ada)
        add_member(group, bo)
        clock.set(IN_WEEK_WINDOW)
        tick()
        clock.set(WEEK_CLOSES)
        tick()
        html = login_as(ada).get(f"/g/{group.id}/").get_data(as_text=True)
        assert "<h1>Ranking KW 44</h1>" in html

    def test_marks_the_own_entry(self, daily, login_as):
        """RNK-04"""
        group, _ada, bo, _cleo = daily
        html = login_as(bo).get(f"/g/{group.id}/").get_data(as_text=True)
        [mine] = [row for row in rows(html) if "rank-me" in row]
        assert 'aria-current="true"' in mine
        assert ">Bo <span" in mine and '<span class="badge badge-ink">Du</span>' in mine

    def test_status_block_links_to_the_open_voting(self, daily, login_as):
        group, ada, bo, _cleo = daily
        vote(group, ada, bo, "up")
        html = login_as(ada).get(f"/g/{group.id}/").get_data(as_text=True)
        assert f'<a class="status-block status-dark" href="/g/{group.id}/vote">' in html
        assert "Voting offen" in html and "1 / 2 bewertet · bis Sa 13:00" in html
        assert "23:00 h ›" in html


class TestTicker:
    def test_average_and_every_member(self, daily, clock, login_as):
        group, ada, bo, _cleo = daily
        vote(group, ada, bo, "up")
        next_day(clock)
        html = login_as(ada).get(f"/g/{group.id}/").get_data(as_text=True)
        ticker = html[html.index('<div class="ticker"') : html.index("</header>")]
        assert "Gruppenschnitt" in ticker
        for name in ("Ada", "Bo", "Cleo"):
            assert ticker.count(f'<span class="ticker-item">{name} ') == 2  # loops seamlessly
        assert ticker.count('aria-hidden="true"') == 1

    def test_new_group(self, daily, login_as):
        group, ada, *_ = daily
        html = login_as(ada).get(f"/g/{group.id}/").get_data(as_text=True)
        assert "Neue Gruppe · Spaßvögel" in html
        assert "Gruppenschnitt" not in html


class TestGraphPage:
    def test_container_and_scripts(self, daily, clock, login_as):
        group, ada, *_ = daily
        next_day(clock)
        html = login_as(ada).get(f"/g/{group.id}/").get_data(as_text=True)
        assert f'data-url="/g/{group.id}/graph.json"' in html
        assert 'data-range="4w"' in html
        assert re.search(r'echarts@[\d.]+/dist/echarts.min.js"\s+integrity="sha384-', html)
        assert "/static/js/graph.js" in html

    @pytest.mark.parametrize(("query", "selected"), [("?range=1y", "1y"), ("?range=x", "4w")])
    def test_range_links_work_without_javascript(self, daily, clock, login_as, query, selected):
        group, ada, *_ = daily
        next_day(clock)
        html = login_as(ada).get(f"/g/{group.id}/{query}").get_data(as_text=True)
        assert f'data-range="{selected}"' in html
        current = re.findall(r'data-range="(\w+)" aria-current="true"', html)
        assert current == [selected]


class TestGraphJson:
    def test_returns_the_series(self, daily, clock, login_as):
        group, ada, bo, _cleo = daily
        vote(group, ada, bo, "up")
        next_day(clock)
        response = login_as(ada).get(f"/g/{group.id}/graph.json?range=1w")
        assert response.status_code == 200
        body = response.get_json()
        assert body["range"] == "1w"
        assert {s["name"] for s in body["series"]} == {"Ada", "Bo", "Cleo"}

    def test_defaults_to_four_weeks(self, daily, login_as):
        group, ada, *_ = daily
        assert login_as(ada).get(f"/g/{group.id}/graph.json").get_json()["range"] == "4w"

    def test_rejects_unknown_ranges(self, daily, login_as):
        group, ada, *_ = daily
        assert login_as(ada).get(f"/g/{group.id}/graph.json?range=2w").status_code == 400


class TestEdgeCases:
    def test_names_are_escaped(self, app, clock, login_as):
        """A display name is user input; it must not become markup anywhere."""
        evil = "<img src=x onerror=alert(1)>"
        ada, bo = make_user(display_name=evil), make_user(display_name="Bo")
        group = make_daily(make_group(ada))
        add_member(group, bo)
        tick()
        vote(group, bo, ada, "up")
        next_day(clock)
        vote(group, bo, ada, "up")
        vote(group, ada, bo, "down")
        next_day(clock)
        html = login_as(bo).get(f"/g/{group.id}/").get_data(as_text=True)
        assert "Größter Anstieg" in html
        assert evil not in html  # leaderboard, highlight cells and ticker
        assert "&lt;img src=x onerror=alert(1)&gt;" in html
        # In the JSON it is plain data; graph.js escapes it before it reaches the DOM.
        response = login_as(bo).get(f"/g/{group.id}/graph.json")
        assert response.mimetype == "application/json"
        assert evil in [s["name"] for s in response.get_json()["series"]]

    def test_group_without_results(self, app, login_as):
        ada = make_user(display_name="Ada")
        group = make_group(ada)
        client = login_as(ada)
        html = client.get(f"/g/{group.id}/").get_data(as_text=True)
        assert ranked_names(html) == ["Ada"]
        assert client.get(f"/g/{group.id}/graph.json").get_json()["series"] == []

    def test_ties_share_a_place_and_highlight(self, daily, clock, login_as):
        """A7: equal scores share the place; tied movements list every name."""
        group, ada, bo, cleo = daily
        next_day(clock)
        vote(group, ada, bo, "up")
        vote(group, ada, cleo, "up")
        next_day(clock)
        html = login_as(ada).get(f"/g/{group.id}/").get_data(as_text=True)
        places = re.findall(r'<span class="rank-place">(\d+)</span>', html)
        assert places == ["01", "01", "03"]
        assert re.search(r'<span class="cell-value">(Bo, Cleo|Cleo, Bo) ▲', html)

    def test_returner_without_new_result_shows_no_change(self, daily, clock, login_as):
        group, ada, bo, _cleo = daily
        vote(group, ada, bo, "up")
        next_day(clock)
        membership.leave(group, bo)
        next_day(clock)
        add_member(group, bo)
        html = login_as(ada).get(f"/g/{group.id}/").get_data(as_text=True)
        [bo_row] = [row for row in rows(html) if ">Bo<" in row or ">Bo " in row]
        assert (
            '<span class="rank-delta" title="Veränderung durch das letzte Voting">–</span>'
            in bo_row
        )
        assert ">Neu<" not in bo_row
