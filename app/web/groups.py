from flask import Blueprint, Flask, flash, g, redirect, render_template, url_for
from flask_login import current_user, login_required
from werkzeug.wrappers import Response as BaseResponse

from app.domain.colors import color_for
from app.i18n import t
from app.models.group import GROUP_NAME_MAX_LENGTH
from app.services import groups, membership
from app.services.errors import InvalidInput
from app.services.text import member_name
from app.web.access import admin_required, member_required
from app.web.forms import ConfirmForm, ConfirmNameForm, GroupNameForm

bp = Blueprint("groups", __name__)

Page = tuple[str, int] | BaseResponse


def register(app: Flask) -> None:
    app.add_template_global(color_for, "member_color")
    app.add_template_global(member_name)
    app.register_blueprint(bp)


@bp.route("/groups/new", methods=["GET", "POST"])
@login_required
def create() -> Page:
    form = GroupNameForm()
    error = None
    if form.validate_on_submit():
        try:
            group = groups.create_group(current_user._get_current_object(), form.name.data or "")
        except InvalidInput as invalid:
            error = invalid.message()
        else:
            flash(t("groups.created", group=group.name), "success")
            return redirect(url_for("groups.home", group_id=group.id))
    return render_template(
        "groups/new.html", form=form, error=error, max_length=GROUP_NAME_MAX_LENGTH
    ), 400 if error else 200


@bp.get("/g/<int:group_id>/")
@member_required
def home(group_id: int) -> str:
    return render_template(
        "groups/home.html",
        group=g.group,
        members=membership.active_members(group_id),
        is_admin=g.group.admin_user_id == current_user.id,
        form=ConfirmForm(),
    )


@bp.post("/g/<int:group_id>/members/<int:user_id>/remove")
@admin_required
def remove_member(group_id: int, user_id: int) -> BaseResponse:
    if ConfirmForm().validate_on_submit():
        name = member_name(membership.require_active(group_id, user_id).user)
        try:
            membership.remove(g.group, current_user._get_current_object(), user_id)
        except InvalidInput as invalid:
            flash(invalid.message(), "error")
        else:
            flash(t("groups.removed", name=name), "success")
    return redirect(url_for("groups.home", group_id=group_id))


@bp.post("/g/<int:group_id>/members/<int:user_id>/admin")
@admin_required
def transfer_admin(group_id: int, user_id: int) -> BaseResponse:
    if ConfirmForm().validate_on_submit():
        name = member_name(membership.require_active(group_id, user_id).user)
        try:
            groups.transfer_admin(g.group, current_user._get_current_object(), user_id)
        except InvalidInput as invalid:
            flash(invalid.message(), "error")
        else:
            flash(t("groups.admin_transferred", name=name), "success")
    return redirect(url_for("groups.home", group_id=group_id))


@bp.route("/g/<int:group_id>/leave", methods=["GET", "POST"])
@member_required
def leave(group_id: int) -> Page:
    form = ConfirmNameForm()
    group = g.group
    error = None
    if form.validate_on_submit():
        name = group.name
        try:
            result = groups.leave_group(
                group, current_user._get_current_object(), form.confirmation.data
            )
        except InvalidInput as invalid:
            error = invalid.message()
        else:
            key = "groups.deleted" if result is groups.LeaveResult.GROUP_DELETED else "groups.left"
            flash(t(key, group=name), "success")
            return redirect(url_for("main.index"))
    successor = membership.successor(group_id, current_user.id)
    return render_template(
        "groups/leave.html",
        form=form,
        group=group,
        error=error,
        successor=successor,
        is_admin=group.admin_user_id == current_user.id,
    ), 400 if error else 200


@bp.route("/g/<int:group_id>/delete", methods=["GET", "POST"])
@admin_required
def delete(group_id: int) -> Page:
    form = ConfirmNameForm()
    group = g.group
    error = None
    if form.validate_on_submit():
        name = group.name
        try:
            groups.delete_group(group, current_user._get_current_object(), form.confirmation.data)
        except InvalidInput as invalid:
            error = invalid.message()
        else:
            flash(t("groups.deleted", group=name), "success")
            return redirect(url_for("main.index"))
    return render_template(
        "groups/delete.html", form=form, group=group, error=error
    ), 400 if error else 200
