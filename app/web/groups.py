from flask import (
    Blueprint,
    Flask,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from werkzeug.wrappers import Response as BaseResponse

from app.clock import get_clock
from app.domain.formatting import DECIMAL_SEPARATOR, format_change, format_score
from app.domain.ranking import Label
from app.domain.types import Cadence
from app.i18n import day_month, iso_week, short_date, short_datetime, t
from app.models import Group
from app.models.group import GROUP_NAME_MAX_LENGTH
from app.services import graph, groups, leaderboard, membership, ticker, voting
from app.services.errors import InvalidInput
from app.services.text import member_name
from app.web.access import admin_required, member_required
from app.web.forms import ConfirmForm, ConfirmNameForm, GroupNameForm

bp = Blueprint("groups", __name__)

Page = tuple[str, int] | BaseResponse


def register(app: Flask) -> None:
    app.add_template_global(member_name)
    app.add_template_global(ticker_data)
    # Display rounding lives in domain.formatting only (A13).
    app.add_template_filter(format_score, "score")
    app.add_template_global(DECIMAL_SEPARATOR, "decimal_separator")
    app.add_template_filter(format_change, "change")
    app.add_template_global(RANK_LABELS, "rank_labels")
    app.register_blueprint(bp)


RANK_LABELS = {
    Label.BEST: "ranking.label_best",
    Label.GAIN: "ranking.label_gain",
    Label.DROP: "ranking.label_drop",
    Label.STEADY: "ranking.label_steady",
    Label.RECOVERING: "ranking.label_recovering",
    Label.BELOW_START: "ranking.label_below_start",
    Label.NEW: "ranking.label_new",
}


def current_board() -> leaderboard.Leaderboard:
    """The leaderboard of g.group, computed once per request for page and ticker."""
    if "board" not in g:
        g.board = leaderboard.leaderboard(g.group.id)
    return g.board


def ticker_data() -> ticker.Ticker:
    return ticker.ticker(current_board())


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
    # Without JavaScript the range links reload the page; graph.js picks the range up.
    selected_range = graph.parse_range(request.args.get("range")) or graph.DEFAULT_RANGE
    group = g.group
    board = current_board()
    return render_template(
        "groups/home.html",
        group=group,
        board=board,
        ballot=voting.ballot(group, current_user._get_current_object()),
        heading=_heading(group, board),
        sub=_sub(group, board),
        ranges=graph.RANGE_LABELS,
        selected_range=selected_range,
        is_admin=group.admin_user_id == current_user.id,
        max_group_size=current_app.config["MAX_GROUP_SIZE"],
    )


def _heading(group: Group, board: leaderboard.Leaderboard) -> str:
    """ "Ranking KW 43" (weekly), "Ranking 25.10." (daily), "Ranking" before any result."""
    if board.as_of is None or board.cadence is None:
        return t("ranking.title")
    # The cadence of the period shown, not a changed setting (SET-01).
    if board.cadence == Cadence.WEEKLY:
        return t("ranking.title_week", week=iso_week(board.as_of, group.timezone))
    return t("ranking.title_day", date=day_month(board.as_of, group.timezone))


def _sub(group: Group, board: leaderboard.Leaderboard) -> str:
    if board.as_of is None:
        return t("ranking.founded", date=short_date(group.created_at, group.timezone))
    return t("ranking.as_of", at=short_datetime(board.as_of, group.timezone))


@bp.get("/g/<int:group_id>/graph.json")
@member_required
def graph_json(group_id: int) -> BaseResponse:
    range_ = graph.parse_range(request.args.get("range"))
    if range_ is None:
        abort(400, t("graph.invalid_range"))
    data = graph.graph_data(
        g.group, current_user.id, range_, get_clock().now(), graph.roles(current_board())
    )
    return jsonify(data)


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
    return redirect(url_for("settings.index", group_id=group_id))


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
    return redirect(url_for("settings.index", group_id=group_id))


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
