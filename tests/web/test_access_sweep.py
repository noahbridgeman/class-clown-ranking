"""NFA-07: every route of a group checks membership, admin routes also the admin role.

Walks app.url_map, so new routes are covered automatically.
"""

import pytest
from flask import Flask
from werkzeug.routing import Rule

from app.extensions import db
from app.models import User
from app.services import invitations
from app.web.access import Access, access_of
from tests.factories import add_member, make_group, make_user

METHODS_SKIPPED = {"HEAD", "OPTIONS"}


def group_rules(app: Flask) -> list[Rule]:
    rules = [rule for rule in app.url_map.iter_rules() if "group_id" in rule.arguments]
    assert rules, "no group routes found"
    return rules


@pytest.fixture
def world(app):
    """A group with an admin, a member, an open invitation, and an outsider."""
    admin = make_user("admin@example.org")
    group = make_group(admin, "Runde")
    member = add_member(group, make_user("member@example.org"))
    invitation = invitations.invite(group, admin, "neu@example.org").invitation
    outsider = make_user("outsider@example.org")
    return {
        "group": group,
        "admin": admin,
        "member": member,
        "outsider": outsider,
        "values": {"group_id": group.id, "user_id": member.id, "invitation_id": invitation.id},
    }


def urls(app: Flask, world: dict) -> list[tuple[str, str, Access | None]]:
    found = []
    for rule in group_rules(app):
        url = rule.build({k: world["values"][k] for k in rule.arguments}, append_unknown=False)[1]
        access = access_of(app.view_functions[rule.endpoint])
        for method in sorted(rule.methods - METHODS_SKIPPED):
            found.append((method, url, access))
    return found


def request(client, method: str, url: str):
    return client.open(url, method=method)


def test_every_group_route_declares_its_access(app):
    missing = [
        rule.endpoint
        for rule in group_rules(app)
        if access_of(app.view_functions[rule.endpoint]) is None
    ]
    assert missing == []


def test_there_are_admin_and_member_routes(app):
    kinds = {access_of(app.view_functions[rule.endpoint]) for rule in group_rules(app)}
    assert kinds == {Access.MEMBER, Access.ADMIN}


def test_outsiders_get_404_everywhere(app, world, login_as):
    client = login_as(world["outsider"])
    for method, url, _ in urls(app, world):
        assert request(client, method, url).status_code == 404, (method, url)


def test_former_members_get_404_everywhere(app, world, login_as):
    from app.services import membership

    membership.leave(world["group"], world["member"])
    client = login_as(world["member"])
    for method, url, _ in urls(app, world):
        assert request(client, method, url).status_code == 404, (method, url)


def test_unknown_group_is_404_even_for_members_elsewhere(app, world, login_as):
    client = login_as(world["member"])
    for method, url, _ in urls(app, {**world, "values": {**world["values"], "group_id": 9999}}):
        assert request(client, method, url).status_code == 404, (method, url)


def test_members_get_403_on_admin_routes_only(app, world, login_as):
    client = login_as(world["member"])
    for method, url, access in urls(app, world):
        status = request(client, method, url).status_code
        if access is Access.ADMIN:
            assert status == 403, (method, url)
        else:
            assert status not in (403, 404), (method, url)
        # Member routes such as leaving have effects; start each request from the same state.
        add_member(world["group"], world["member"])


def test_guests_are_sent_to_login(app, world, client):
    for method, url, _ in urls(app, world):
        response = request(client, method, url)
        assert response.status_code == 302, (method, url)
        assert response.location == "/login"


def test_admin_reaches_every_route(app, world, login_as):
    client = login_as(world["admin"])
    for method, url, _ in urls(app, world):
        if method == "GET":
            assert request(client, method, url).status_code == 200, url


def test_rules_use_only_known_arguments(app, world):
    for rule in group_rules(app):
        assert rule.arguments <= set(world["values"]), rule.rule


def test_former_admin_rights_end_with_the_role(app, world, login_as):
    from app.services import groups

    groups.transfer_admin(world["group"], world["admin"], world["member"].id)
    client = login_as(db.session.get(User, world["admin"].id))
    for method, url, access in urls(app, world):
        if access is Access.ADMIN:
            assert request(client, method, url).status_code == 403, (method, url)
