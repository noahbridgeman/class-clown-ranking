"""NFA-07: every route of a group checks membership, admin routes also the admin role.

Walks app.url_map, so new routes are covered automatically: a route either declares its
access level or is listed in PUBLIC_ENDPOINTS below.
"""

from typing import TypedDict

import pytest
from flask import Flask
from flask.testing import FlaskClient
from werkzeug.routing import Rule
from werkzeug.test import TestResponse

from app.extensions import db
from app.models import Group, User
from app.services import groups, invitations, membership
from app.web.access import Access, access_of
from tests.factories import IN_WEEK_WINDOW, add_member, make_group, make_user, tick

METHODS_SKIPPED = {"HEAD", "OPTIONS"}
# Routes without a group. Each one is reviewed by hand when added here.
PUBLIC_ENDPOINTS = {
    "static",
    "main.index",
    "auth.login",
    "auth.sent",
    "auth.confirm",
    "auth.redeem",
    "auth.logout",
    "auth.name",
    "groups.create",
    "invitations.show",
    "invitations.accept",
    # PWA (A24): manifest and service worker are static; the subscription routes need a
    # login and only touch the user's own devices.
    "pwa.manifest",
    "pwa.service_worker",
    "pwa.subscribe",
    "pwa.unsubscribe",
}


class World(TypedDict):
    group: Group
    admin: User
    member: User
    outsider: User
    values: dict[str, int]


Request = tuple[str, str, Access | None]


def group_rules(app: Flask) -> list[Rule]:
    rules = [rule for rule in app.url_map.iter_rules() if "group_id" in rule.arguments]
    assert rules, "no group routes found"
    return rules


@pytest.fixture
def world(app: Flask, clock) -> World:
    """A group with an admin, a member, an open invitation, a running period (seq 1),
    and an outsider."""
    admin = make_user("admin@example.org")
    group = make_group(admin, "Runde")
    member = add_member(group, make_user("member@example.org"))
    invitation = invitations.invite(group, admin, "neu@example.org").invitation
    clock.set(IN_WEEK_WINDOW)
    tick()
    return World(
        group=group,
        admin=admin,
        member=member,
        outsider=make_user("outsider@example.org"),
        values={
            "group_id": group.id,
            "user_id": member.id,
            "invitation_id": invitation.id,
            "seq": 1,
        },
    )


def requests(app: Flask, values: dict[str, int]) -> list[Request]:
    found = []
    for rule in group_rules(app):
        url = rule.build({name: values[name] for name in rule.arguments}, append_unknown=False)[1]
        access = access_of(app.view_functions[rule.endpoint])
        found.extend((method, url, access) for method in sorted(rule.methods - METHODS_SKIPPED))
    return found


def send(client: FlaskClient, method: str, url: str) -> TestResponse:
    return client.open(url, method=method)


def test_every_route_is_guarded_or_explicitly_public(app: Flask) -> None:
    unguarded = {
        rule.endpoint
        for rule in app.url_map.iter_rules()
        if access_of(app.view_functions[rule.endpoint]) is None
    }
    assert unguarded == PUBLIC_ENDPOINTS


def test_public_routes_have_no_group(app: Flask) -> None:
    for rule in app.url_map.iter_rules():
        if rule.endpoint in PUBLIC_ENDPOINTS:
            assert "group_id" not in rule.arguments, rule.rule


def test_object_ids_only_appear_under_a_group(app: Flask) -> None:
    """An id without its group would need its own, untested ownership check."""
    for rule in app.url_map.iter_rules():
        if any(name.endswith("_id") for name in rule.arguments):
            assert "group_id" in rule.arguments, rule.rule


def test_there_are_admin_and_member_routes(app: Flask) -> None:
    kinds = {access_of(app.view_functions[rule.endpoint]) for rule in group_rules(app)}
    assert kinds == {Access.MEMBER, Access.ADMIN}


def test_rules_use_only_known_arguments(app: Flask, world: World) -> None:
    for rule in group_rules(app):
        assert rule.arguments <= set(world["values"]), rule.rule


def test_outsiders_get_404_everywhere(app: Flask, world: World, login_as) -> None:
    client = login_as(world["outsider"])
    for method, url, _ in requests(app, world["values"]):
        assert send(client, method, url).status_code == 404, (method, url)


def test_former_members_get_404_everywhere(app: Flask, world: World, login_as) -> None:
    membership.leave(world["group"], world["member"])
    client = login_as(world["member"])
    for method, url, _ in requests(app, world["values"]):
        assert send(client, method, url).status_code == 404, (method, url)


def test_unknown_group_is_404_even_for_members_elsewhere(
    app: Flask, world: World, login_as
) -> None:
    client = login_as(world["member"])
    for method, url, _ in requests(app, {**world["values"], "group_id": 9999}):
        assert send(client, method, url).status_code == 404, (method, url)


def test_members_get_403_on_admin_routes_and_success_elsewhere(
    app: Flask, world: World, login_as
) -> None:
    client = login_as(world["member"])
    for method, url, access in requests(app, world["values"]):
        status = send(client, method, url).status_code
        if access is Access.ADMIN:
            assert status == 403, (method, url)
        else:
            assert status in (200, 302), (method, url, status)
        # Member routes such as leaving have effects; start each request from the same state.
        add_member(world["group"], world["member"])


def test_guests_are_sent_to_login(app: Flask, world: World, client: FlaskClient) -> None:
    for method, url, _ in requests(app, world["values"]):
        response = send(client, method, url)
        assert response.status_code == 302, (method, url)
        assert response.location == "/login"


def test_admin_reaches_every_page(app: Flask, world: World, login_as) -> None:
    client = login_as(world["admin"])
    for method, url, _ in requests(app, world["values"]):
        if method == "GET":
            assert send(client, method, url).status_code == 200, url


def test_former_admin_rights_end_with_the_role(app: Flask, world: World, login_as) -> None:
    groups.transfer_admin(world["group"], world["admin"], world["member"].id)
    client = login_as(db.session.get(User, world["admin"].id))
    for method, url, access in requests(app, world["values"]):
        if access is Access.ADMIN:
            assert send(client, method, url).status_code == 403, (method, url)
