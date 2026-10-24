"""Leaderboard and graph on the group page (RNK-01…04, GRA-03, GRA-08)."""

import re

import pytest

from app.services import membership
from tests.factories import add_member, make_daily, make_group, make_user, next_day, tick, vote


@pytest.fixture
def daily(app):
    ada, bo, cleo = (make_user(display_name=name) for name in ("Ada", "Bo", "Cleo"))
    group = make_daily(make_group(ada))
    add_member(group, bo)
    add_member(group, cleo)
    tick()
    return group, ada, bo, cleo


def ranking_html(html: str) -> str:
    return html[html.index('<ul class="ranking">') :]


def ranked_names(html: str) -> list[str]:
    return re.findall(r'<span class="rank-name">\s*([^<]+?)\s*<', ranking_html(html))


class TestRanking:
    def test_before_the_first_result(self, daily, login_as):
        group, ada, *_ = daily
        html = login_as(ada).get(f"/g/{group.id}/").get_data(as_text=True)
        assert "Noch keine Ergebnisse" in html
        assert ranking_html(html).count("5,0") == 3
        assert ranking_html(html).count(">neu<") == 3

    def test_order_scores_changes_and_highlights(self, daily, clock, login_as):
        """RNK-01…03: sorted, one decimal, ▲/▼ with the change, highlights on top."""
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
        assert "Stand nach dem Fenster bis 25.10.2026" in html
        assert re.search(r"▲ \+\d,\d", ranking) and re.search(r"▼ −\d,\d", ranking)
        assert "Größter Anstieg" in html and "Größter Absturz" in html
        assert "Neu auf Platz 1" in html
        assert "↑ 2" in ranking

    def test_marks_the_own_entry(self, daily, login_as):
        """RNK-04"""
        group, _ada, bo, _cleo = daily
        html = ranking_html(login_as(bo).get(f"/g/{group.id}/").get_data(as_text=True))
        [mine] = re.findall(r'<li class="rank rank-me" aria-current="true">.*?</li>', html, re.S)
        assert "Bo" in mine and "(du)" in mine


class TestGraphPage:
    def test_container_and_scripts(self, daily, login_as):
        group, ada, *_ = daily
        html = login_as(ada).get(f"/g/{group.id}/").get_data(as_text=True)
        assert f'data-url="/g/{group.id}/graph.json"' in html
        assert 'data-range="4w"' in html
        assert re.search(r'echarts@[\d.]+/dist/echarts.min.js"\s+integrity="sha384-', html)
        assert "/static/js/graph.js" in html

    @pytest.mark.parametrize(("query", "selected"), [("?range=1y", "1y"), ("?range=x", "4w")])
    def test_range_links_work_without_javascript(self, daily, login_as, query, selected):
        group, ada, *_ = daily
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
        assert evil not in html
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
        places = re.findall(r'<span class="rank-place">(\d+)\.</span>', html)
        assert places == ["1", "1", "3"]
        assert re.search(r"Größter Anstieg</span> (Bo, Cleo|Cleo, Bo) ", html)

    def test_returner_without_new_result_shows_no_change(self, daily, clock, login_as):
        group, ada, bo, _cleo = daily
        vote(group, ada, bo, "up")
        next_day(clock)
        membership.leave(group, bo)
        next_day(clock)
        add_member(group, bo)
        html = login_as(ada).get(f"/g/{group.id}/").get_data(as_text=True)
        bo_row = re.search(r'<span class="rank-name">\s*Bo.*?</li>', html, re.S).group(0)
        assert '<span class="delta"></span>' in bo_row
        assert ">neu<" not in bo_row
