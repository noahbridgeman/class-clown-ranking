"""VOT-07 / NFA-06: while the window is open, no page shows anything of other people's votes.

Renders every member page of the group for a third person, once before and once after two
others voted. Apart from the count of members who voted, the pages must be identical.
Walks app.url_map, so pages added later (graph, overview) are covered automatically.
"""

import re

import pytest
from flask import Flask

from tests.factories import IN_WEEK_WINDOW, add_member, make_group, make_user, tick, vote

VOTER_COUNT = re.compile(r"\d+ von \d+ Mitgliedern haben schon abgestimmt")
CSRF = re.compile(r'(csrf[-_]token"?\s*(?:content|value)=)"[^"]*"|"X-CSRFToken": "[^"]*"')
HTMX = {"HX-Request": "true"}


def member_pages(app: Flask, group_id: int) -> list[str]:
    urls = []
    for rule in app.url_map.iter_rules():
        if rule.arguments == {"group_id"} and "GET" in rule.methods:
            urls.append(rule.build({"group_id": group_id}, append_unknown=False)[1])
    assert urls
    return sorted(urls)


def snapshot(client, urls: list[str]) -> dict[tuple[str, bool], str]:
    pages = {}
    for url in urls:
        for htmx in (False, True):
            html = client.get(url, headers=HTMX if htmx else {}).get_data(as_text=True)
            html = VOTER_COUNT.sub("COUNT", CSRF.sub("CSRF", html))
            pages[url, htmx] = html
    return pages


@pytest.mark.parametrize("anonymous", [True, False])
def test_open_window_shows_nothing_of_others_votes(app, clock, login_as, anonymous):
    """Holds in the open mode too, as long as the window is open (VOT-07)."""
    a, b, observer = make_user(), make_user(), make_user()
    group = make_group(a)
    group.is_anonymous = anonymous
    add_member(group, b)
    add_member(group, observer)
    clock.set(IN_WEEK_WINDOW)
    tick()
    client = login_as(observer)
    urls = member_pages(app, group.id)

    before = snapshot(client, urls)
    vote(group, a, b, "up")
    vote(group, a, observer, "down")
    vote(group, b, a, "down")
    after = snapshot(client, urls)

    assert after == before


def test_the_count_is_the_only_difference(app, clock, login_as):
    a, b, observer = make_user(), make_user(), make_user()
    group = make_group(a)
    add_member(group, b)
    add_member(group, observer)
    clock.set(IN_WEEK_WINDOW)
    tick()
    client = login_as(observer)
    url = f"/g/{group.id}/vote"
    assert "0 von 3 Mitgliedern" in client.get(url).get_data(True)
    vote(group, a, b, "up")
    assert "1 von 3 Mitgliedern" in client.get(url).get_data(True)
