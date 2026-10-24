"""Access checks for group routes (NFA-07). Every route under /g/<group_id> uses one of them."""

from collections.abc import Callable
from enum import StrEnum
from functools import wraps
from typing import Any

from flask import abort, g
from flask_login import current_user

from app.extensions import login_manager
from app.services import groups, membership

View = Callable[..., Any]


class Access(StrEnum):
    MEMBER = "member"
    ADMIN = "admin"


def member_required(view: View) -> View:
    """Loads the group and the active membership into g; non-members get 404 (A10)."""
    return _guard(view, Access.MEMBER)


def admin_required(view: View) -> View:
    """Like member_required; members without the admin role get 403."""
    return _guard(view, Access.ADMIN)


def access_of(view: View) -> Access | None:
    return getattr(view, "access", None)


def _guard(view: View, access: Access) -> View:
    @wraps(view)
    def wrapper(group_id: int, **kwargs: Any) -> Any:
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        group = groups.get_group(group_id)
        member = membership.active_membership(group_id, current_user.id) if group else None
        if group is None or member is None:
            abort(404)
        if access is Access.ADMIN and group.admin_user_id != current_user.id:
            abort(403)
        g.group = group
        g.membership = member
        return view(group_id=group_id, **kwargs)

    wrapper.access = access  # type: ignore[attr-defined]
    return wrapper
