"""VOT-07 / NFA-06: while the window is open, no page shows anything of other people's votes.

Renders every member page of the group for a third person, once before and once after two
others voted. Apart from the count of members who voted, the pages must be identical.
Walks app.url_map with every member and period filled in, so pages added later are
covered automatically. Further down: closed anonymous periods (OVW-02, OVW-07).
"""

import re
from datetime import timedelta

import pytest
from flask import Flask

from app.extensions import db
from app.models import User
from app.services import periods, vote_queries, voting
from app.services.vote_queries import AnonymityViolation
from tests.factories import (
    IN_WEEK_WINDOW,
    WEEK_CLOSES,
    add_member,
    make_group,
    make_user,
    tick,
    vote,
)

VOTER_COUNT = re.compile(r"\d+ von \d+ haben abgestimmt")
CSRF = re.compile(r'(csrf[-_]token"?\s*(?:content|value)=)"[^"]*"|"X-CSRFToken": "[^"]*"')
HTMX = {"HX-Request": "true"}


def snapshot(client, urls: list[str]) -> dict[tuple[str, bool], str]:
    pages = {}
    for url in urls:
        for htmx in (False, True):
            html = client.get(url, headers=HTMX if htmx else {}).get_data(as_text=True)
            html = VOTER_COUNT.sub("COUNT", CSRF.sub("CSRF", html))
            pages[url, htmx] = html
    return pages


@pytest.mark.parametrize("anonymous", [True, False])
@pytest.mark.parametrize("with_history", [False, True])
def test_open_window_shows_nothing_of_others_votes(app, clock, login_as, anonymous, with_history):
    """Holds in the open mode too, as long as the window is open (VOT-07)."""
    a, b, observer = make_user(), make_user(), make_user()
    group = make_group(a)
    group.is_anonymous = anonymous
    add_member(group, b)
    add_member(group, observer)
    if with_history:
        # A closed period first, so ticker, labels, sparklines and scores are drawn too.
        clock.set(IN_WEEK_WINDOW - timedelta(days=7))
        tick()
        vote(group, a, b, "up")
        vote(group, b, observer, "down")
        clock.set(WEEK_CLOSES - timedelta(days=7))
        tick()
    clock.set(IN_WEEK_WINDOW)
    tick()
    client = login_as(observer)
    seqs = [1, 2] if with_history else [1]
    urls = all_member_pages(app, group.id, [a.id, b.id, observer.id], seqs)

    before = snapshot(client, urls)
    vote(group, a, b, "up")
    vote(group, a, observer, "down")
    vote(group, b, a, "down")
    if not anonymous:
        voting.set_reason(group, a, b.id, "Die Sache mit der Ente")  # VOT-08
    after = snapshot(client, urls)

    assert after == before
    # Neither does the rated person see a reason given to them (VOT-07, VOT-08).
    rated = snapshot(login_as(b), urls)
    assert not any("Ente" in html for html in rated.values())


def test_the_count_is_the_only_difference(app, clock, login_as):
    a, b, observer = make_user(), make_user(), make_user()
    group = make_group(a)
    add_member(group, b)
    add_member(group, observer)
    clock.set(IN_WEEK_WINDOW)
    tick()
    client = login_as(observer)
    url = f"/g/{group.id}/vote"
    assert "0 von 3 haben abgestimmt" in client.get(url).get_data(True)
    vote(group, a, b, "up")
    assert "1 von 3 haben abgestimmt" in client.get(url).get_data(True)


# After the window: closed anonymous periods (OVW-02, OVW-07, VOT-09, NFA-06).

NAMES = ("Ada", "Bo", "Cleo", "Dora", "Eli")


def all_member_pages(app: Flask, group_id: int, user_ids: list[int], seqs: list[int]) -> list[str]:
    """Every GET page of the group, once per member and period where the route takes one."""
    urls = []
    for rule in app.url_map.iter_rules():
        if "group_id" not in rule.arguments or "GET" not in rule.methods:
            continue
        assert rule.arguments <= {"group_id", "user_id", "seq"}, rule.rule
        values: list[dict[str, int]] = [{"group_id": group_id}]
        if "user_id" in rule.arguments:
            values = [{**v, "user_id": u} for v in values for u in user_ids]
        if "seq" in rule.arguments:
            values = [{**v, "seq": seq} for v in values for seq in seqs]
        urls.extend(rule.build(v, append_unknown=False)[1] for v in values)
    return sorted(urls)


def closed_anonymous_world(app: Flask, clock, swap: bool) -> tuple[dict[str, User], list[str]]:
    """Ada and Bo rate Cleo and Dora, one up and one down each; swap exchanges who gave
    which, so every count stays the same. Then a newer period opens, not anonymous, with
    swapped votes as well."""
    users = {name: make_user(f"{name.lower()}@example.org", name) for name in NAMES}
    group = make_group(users["Ada"])
    for name in NAMES[1:]:
        add_member(group, users[name])
    clock.set(IN_WEEK_WINDOW)
    tick()
    first, second = ("down", "up") if swap else ("up", "down")
    vote(group, users["Ada"], users["Cleo"], first)
    vote(group, users["Bo"], users["Cleo"], second)
    vote(group, users["Ada"], users["Dora"], second)
    vote(group, users["Bo"], users["Dora"], first)
    clock.set(WEEK_CLOSES)
    tick()
    group.is_anonymous = False
    clock.set(IN_WEEK_WINDOW + timedelta(days=7))
    tick()
    # The running period gets swapped votes too, with a reason, though not anonymous (VOT-07).
    vote(group, users["Ada"], users["Cleo"], first)
    vote(group, users["Bo"], users["Cleo"], second)
    voting.set_reason(group, users["Ada"], users["Cleo"].id, "Die Ente")
    ids = [user.id for user in users.values()]
    return users, all_member_pages(app, group.id, ids, [1, 2])


def fresh_database(clock) -> None:
    """Starts over with the same ids, so two worlds can be compared page by page."""
    start = clock.now()
    db.session.remove()
    db.drop_all()
    db.create_all()
    clock.set(start)


@pytest.mark.parametrize("viewer", ["Eli", "Cleo", "Dora"])
def test_closed_anonymous_period_does_not_tell_who_voted_how(app, clock, login_as, viewer):
    """Swapping who gave which vote changes nothing for a watcher or for the rated people."""
    start = clock.now()
    seen = []
    for swap in (False, True):
        clock.set(start)
        if swap:
            fresh_database(clock)
        users, urls = closed_anonymous_world(app, clock, swap)
        assert any("/members/" in url for url in urls) and any("/overview/1" in url for url in urls)
        seen.append(snapshot(login_as(users[viewer]), urls))
    assert seen[0] == seen[1]


def test_voters_see_their_own_anonymous_votes_and_only_they(app, clock, login_as):
    """OVW-07: Ada's down for Dora shows on Ada's overview, nowhere for anyone else."""
    users, urls = closed_anonymous_world(app, clock, swap=False)
    overview_url = next(url for url in urls if url.endswith("/overview/1"))
    ada_detail = next(url for url in urls if url.endswith(f"/members/{users['Ada'].id}"))
    own = login_as(users["Ada"]).get(overview_url).get_data(as_text=True)
    assert "Nur für dich sichtbar" in own
    assert 'vote-chip-down">Dora' in own
    for name in NAMES[1:]:
        page = login_as(users[name]).get(ada_detail).get_data(as_text=True)
        assert "Abgegebene Votes" not in page and "Deine Votes" not in page
        assert 'vote-chip-down">Dora' not in login_as(users[name]).get(overview_url).get_data(True)


def test_votes_of_anonymous_or_running_periods_never_leave_vote_queries(app, clock):
    """The guard behind every page: no matrix or reasons for these periods (NFA-06, VOT-07)."""
    a, b = make_user(), make_user()
    group = make_group(a)
    add_member(group, b)
    group.is_anonymous = False
    clock.set(IN_WEEK_WINDOW)
    tick()
    vote(group, a, b, "up")
    with pytest.raises(AnonymityViolation):
        vote_queries.open_votes(periods.open_period(group.id))  # open, but running (VOT-07)
    assert vote_queries.open_votes_of(group.id, a.id) == []
    clock.set(WEEK_CLOSES)
    tick()
    assert len(vote_queries.open_votes(periods.latest_period(group.id))) == 1

    anonymous = make_group(a, "Anonym")
    add_member(anonymous, b)
    clock.set(IN_WEEK_WINDOW + timedelta(days=7))
    tick()
    vote(anonymous, a, b, "up")
    clock.set(WEEK_CLOSES + timedelta(days=7))
    tick()
    with pytest.raises(AnonymityViolation):
        vote_queries.open_votes(periods.latest_period(anonymous.id))
    anonymous.is_anonymous = False  # a later switch does not open the past (VOT-09)
    db.session.commit()
    assert vote_queries.open_votes_of(anonymous.id, a.id) == []
