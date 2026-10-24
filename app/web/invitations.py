from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_user
from werkzeug.wrappers import Response as BaseResponse

from app.clock import get_clock
from app.i18n import t
from app.models.user import EMAIL_MAX_LENGTH
from app.services import invitations
from app.services.errors import InvalidInput
from app.web.access import admin_required
from app.web.forms import ConfirmForm, EmailForm, LogoutForm

bp = Blueprint("invitations", __name__)

Page = tuple[str, int] | BaseResponse | str


@bp.get("/g/<int:group_id>/invitations")
@admin_required
def index(group_id: int) -> str:
    return _render_list(EmailForm())


@bp.post("/g/<int:group_id>/invitations")
@admin_required
def create(group_id: int) -> Page:
    form = EmailForm()
    if not form.validate_on_submit():
        return _respond(form, status=400)
    try:
        sent = invitations.invite(
            g.group, current_user._get_current_object(), form.email.data or ""
        )
    except InvalidInput as invalid:
        return _respond(form, error=invalid.message(), status=400)
    _flash_sent(sent)
    return _respond(EmailForm(formdata=None))


@bp.post("/g/<int:group_id>/invitations/<int:invitation_id>/resend")
@admin_required
def resend(group_id: int, invitation_id: int) -> Page:
    if ConfirmForm().validate_on_submit():
        try:
            _flash_sent(
                invitations.resend(g.group, current_user._get_current_object(), invitation_id)
            )
        except InvalidInput as invalid:
            flash(invalid.message(), "error")
    return _respond(EmailForm(formdata=None))


@bp.post("/g/<int:group_id>/invitations/<int:invitation_id>/revoke")
@admin_required
def revoke(group_id: int, invitation_id: int) -> Page:
    if ConfirmForm().validate_on_submit():
        try:
            invitations.revoke(g.group, current_user._get_current_object(), invitation_id)
        except InvalidInput as invalid:
            flash(invalid.message(), "error")
        else:
            flash(t("invitations.revoked"), "success")
    return _respond(EmailForm(formdata=None))


@bp.get("/invite/<token>")
def show(token: str) -> Page:
    invitation = invitations.find_open(token)
    if invitation is None:
        return _not_open(token)
    if current_user.is_authenticated and current_user.email != invitation.email:
        return _wrong_account(token)
    return render_template("invitations/accept.html", invitation=invitation, form=ConfirmForm())


@bp.post("/invite/<token>")
def accept(token: str) -> Page:
    if not ConfirmForm().validate_on_submit():
        return render_template("invitations/invalid.html"), 400
    current = current_user._get_current_object() if current_user.is_authenticated else None
    try:
        accepted = invitations.accept(token, current)
    except invitations.WrongAccount:
        return _wrong_account(token)
    if accepted is None:
        return _not_open(token)
    if current is None:
        # The invitation link proves the address, so it logs in like a login link.
        session.clear()
        login_user(accepted.user, remember=True)
    flash(t("invitations.joined", group=accepted.group.name), "success")
    return redirect(url_for("groups.home", group_id=accepted.group.id))


def _not_open(token: str) -> Page:
    """Members who open their used link again just land in the group."""
    if current_user.is_authenticated:
        group = invitations.joined_group(token, current_user._get_current_object())
        if group is not None:
            return redirect(url_for("groups.home", group_id=group.id))
    return render_template("invitations/invalid.html"), 400


def _wrong_account(token: str) -> tuple[str, int]:
    """INV-02. Logging out leads straight back to the invitation."""
    form = LogoutForm(next=url_for("invitations.show", token=token))
    return render_template("invitations/wrong_account.html", form=form), 409


def _flash_sent(sent: invitations.Sent) -> None:
    if sent.mail_sent:
        flash(t("invitations.sent", email=sent.invitation.email), "success")
    else:
        flash(t("invitations.mail_failed", email=sent.invitation.email), "error")


def _respond(form: EmailForm, error: str | None = None, status: int = 200) -> Page:
    """HTMX swaps in the updated list; without JavaScript the page is reloaded."""
    if request.headers.get("HX-Request"):
        return _render_list(form, error, partial=True), status
    if error:
        return _render_list(form, error), status
    return redirect(url_for("invitations.index", group_id=g.group.id))


def _render_list(form: EmailForm, error: str | None = None, partial: bool = False) -> str:
    template = "invitations/_list.html" if partial else "invitations/index.html"
    return render_template(
        template,
        group=g.group,
        invitations=invitations.invitations_of(g.group),
        now=get_clock().now(),
        form=form,
        error=error,
        max_length=EMAIL_MAX_LENGTH,
        action_form=ConfirmForm(),
        partial=partial,
    )
