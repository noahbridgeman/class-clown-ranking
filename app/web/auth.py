from flask import (
    Blueprint,
    Flask,
    Response,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from werkzeug.wrappers import Response as BaseResponse
from wtforms import StringField

from app.extensions import db, login_manager
from app.models import User
from app.models.user import DISPLAY_NAME_MAX_LENGTH, EMAIL_MAX_LENGTH
from app.services import auth

bp = Blueprint("auth", __name__)

# Pages whose URL contains a login token.
TOKEN_ENDPOINTS = {"auth.confirm", "auth.redeem"}
# Reachable while the display name is still missing (AUTH-04). Login links stay usable
# so a nameless account can switch to another one (and, from M3 on, accept invitations).
NAME_GATE_EXEMPT = {"auth.name", "auth.logout", "static", *TOKEN_ENDPOINTS}


class EmailForm(FlaskForm):
    email = StringField()


class NameForm(FlaskForm):
    display_name = StringField()


class ConfirmForm(FlaskForm):
    pass


def register(app: Flask) -> None:
    login_manager.init_app(app)
    app.before_request(_name_gate)
    # Registered after Flask-Login, so it runs before Flask-Login writes the cookie.
    app.after_request(_slide_remember_cookie)
    app.register_blueprint(bp)


@login_manager.user_loader
def _load_user(session_id: str) -> User | None:
    user_id, _, version = session_id.partition(":")
    try:
        user = db.session.get(User, int(user_id))
        current = user is not None and user.session_version == int(version)
    except ValueError:
        return None
    return user if current and user.is_active else None


@login_manager.unauthorized_handler
def _unauthorized() -> BaseResponse:
    return _redirect(url_for("auth.login"))


@bp.after_request
def _protect_token_pages(response: Response) -> Response:
    """Keeps the token out of Referer headers and caches, also on error pages."""
    if request.endpoint in TOKEN_ENDPOINTS:
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
    return response


def _slide_remember_cookie(response: Response) -> Response:
    """Every visit renews the remember cookie, so only 30 days of absence end the session.

    Flask-Login's REMEMBER_COOKIE_REFRESH_EACH_REQUEST would also touch guests' sessions.
    """
    if current_user.is_authenticated and "_user_id" in session and "_remember" not in session:
        session["_remember"] = "set"
    return response


def _name_gate() -> BaseResponse | None:
    if not current_user.is_authenticated or not current_user.needs_display_name:
        return None
    if request.endpoint in NAME_GATE_EXEMPT:
        return None
    return _redirect(url_for("auth.name"))


@bp.route("/login", methods=["GET", "POST"])
def login() -> tuple[str, int] | BaseResponse:
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = EmailForm()
    error = None
    if form.validate_on_submit():
        try:
            auth.request_login(form.email.data or "")
        except auth.InvalidInput as invalid:
            error = invalid.message()
        else:
            return redirect(url_for("auth.sent"))
    return render_template(
        "auth/login.html", form=form, error=error, max_length=EMAIL_MAX_LENGTH
    ), 400 if error else 200


@bp.get("/login/sent")
def sent() -> str:
    return render_template("auth/sent.html", minutes=auth.token_minutes())


@bp.get("/login/<token>")
def confirm(token: str) -> str:
    # Mail scanners open links on their own, so only the POST below uses up the token.
    days = current_app.config["REMEMBER_COOKIE_DURATION"].days
    return render_template("auth/confirm.html", form=ConfirmForm(), days=days)


@bp.post("/login/<token>")
def redeem(token: str) -> tuple[str, int] | BaseResponse:
    if not ConfirmForm().validate_on_submit():
        return render_template("auth/invalid.html"), 400
    user = auth.redeem_login(token)
    if user is None:
        return render_template("auth/invalid.html"), 400
    # Nothing from a previous account's session may carry over.
    session.clear()
    login_user(user, remember=True)  # AUTH-06
    return redirect(url_for("main.index"))


@bp.post("/logout")
def logout() -> BaseResponse:
    logout_user()
    return _redirect(url_for("main.index"))


@bp.route("/account/name", methods=["GET", "POST"])
@login_required
def name() -> tuple[str, int] | BaseResponse:
    form = NameForm()
    error = None
    if form.validate_on_submit():
        try:
            auth.set_display_name(current_user._get_current_object(), form.display_name.data or "")
        except auth.InvalidInput as invalid:
            error = invalid.message()
        else:
            return redirect(url_for("main.index"))
    elif request.method == "GET":
        form.display_name.data = current_user.display_name
    return render_template(
        "account/name.html",
        form=form,
        error=error,
        first_time=current_user.needs_display_name,
        max_length=DISPLAY_NAME_MAX_LENGTH,
    ), 400 if error else 200


def _redirect(location: str) -> BaseResponse:
    """HTMX follows redirects inside the swap target, so it gets told to navigate instead."""
    if request.headers.get("HX-Request"):
        response = Response(status=204)
        response.headers["HX-Redirect"] = location
        return response
    return redirect(location)
