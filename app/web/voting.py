from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.wrappers import Response as BaseResponse

from app.i18n import t
from app.services import voting
from app.services.errors import InvalidInput
from app.web.access import member_required
from app.web.forms import ConfirmForm, VoteForm

bp = Blueprint("voting", __name__)

Page = tuple[str, int] | BaseResponse | str


@bp.get("/g/<int:group_id>/vote")
@member_required
def index(group_id: int) -> str:
    # The ballot polls this every minute to refresh the countdown and the voter count.
    if request.headers.get("HX-Request"):
        return _render(partial=True, show_flashes=False)
    return _render()


@bp.post("/g/<int:group_id>/vote/<int:user_id>")
@member_required
def cast(group_id: int, user_id: int) -> Page:
    form = VoteForm()
    status = 200
    if not form.validate_on_submit():
        flash(t("voting.invalid_choice"), "error")
        status = 400
    else:
        choice = voting.Choice(form.choice.data)
        try:
            voting.set_vote(g.group, current_user._get_current_object(), user_id, choice)
        except InvalidInput as invalid:
            flash(invalid.message(), "error")
            status = 400
    if request.headers.get("HX-Request"):
        return _render(partial=True), status
    return redirect(url_for("voting.index", group_id=group_id))


def _render(partial: bool = False, show_flashes: bool = True) -> str:
    template = "voting/_ballot.html" if partial else "voting/index.html"
    return render_template(
        template,
        group=g.group,
        ballot=voting.ballot(g.group, current_user._get_current_object()),
        form=ConfirmForm(),
        partial=partial,
        show_flashes=show_flashes,
    )
