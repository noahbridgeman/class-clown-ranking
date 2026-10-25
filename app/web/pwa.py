"""PWA and push (NFA-02, NOT-01, NOT-02, A24): manifest, service worker, subscriptions
and the occasions per group."""

from pathlib import Path

from flask import (
    Blueprint,
    Flask,
    Response,
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

from app.i18n import t
from app.models import NotificationKind
from app.services import push
from app.services.errors import InvalidInput
from app.web.access import member_required
from app.web.forms import ConfirmForm

bp = Blueprint("pwa", __name__)

# The manifest cannot read CSS variables; tests/invariants/test_frontend.py keeps it
# equal to --color-bg.
THEME_COLOR = "#f5f4ef"

KIND_LABELS = {kind: f"push.kind_{kind.value}" for kind in NotificationKind}


def register(app: Flask) -> None:
    app.add_template_global(push.public_key, "push_public_key")
    app.add_template_global(push_texts)
    app.add_template_global(KIND_LABELS, "notification_kinds")
    app.register_blueprint(bp)


def push_texts() -> dict[str, str]:
    """The texts of ui.push_control, by state."""
    return {
        "title": t("push.offer_title"),
        "text": t("push.offer_text"),
        "noscript": t("push.no_script"),
        "on": t("push.enabled"),
        "denied": t("push.denied"),
        "unsupported": t("push.unsupported"),
        "ios": t("push.ios_hint"),
        "missing": t("push.not_configured"),
        "failed": t("push.failed"),
        "enable": t("push.enable"),
        "disable": t("push.disable"),
    }


@bp.get("/manifest.webmanifest")
def manifest() -> BaseResponse:
    """NFA-02: installable, starts like an app of its own."""

    def icon(name: str) -> str:
        return url_for("static", filename=f"icons/{name}")

    response = jsonify(
        {
            "name": t("app.name"),
            "short_name": t("app.short_name"),
            "lang": "de",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": THEME_COLOR,
            "theme_color": THEME_COLOR,
            "icons": [
                {"src": icon("icon-192.png"), "sizes": "192x192", "type": "image/png"},
                {"src": icon("icon-512.png"), "sizes": "512x512", "type": "image/png"},
                {
                    "src": icon("icon-maskable-512.png"),
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "maskable",
                },
            ],
        }
    )
    response.mimetype = "application/manifest+json"
    return response


@bp.get("/sw.js")
def service_worker() -> BaseResponse:
    """Served from the root, so its scope covers the whole app."""
    source = Path(current_app.static_folder or "", "js", "sw.js").read_text()
    return Response(source, mimetype="text/javascript", headers={"Cache-Control": "no-cache"})


@bp.post("/push/subscription")
@login_required
def subscribe() -> tuple[BaseResponse, int] | BaseResponse:
    """NOT-01: called by push.js only after the user switched push on and the browser allowed it."""
    data = request.get_json(silent=True) or {}
    keys = data.get("keys") if isinstance(data.get("keys"), dict) else {}
    try:
        push.subscribe(
            current_user._get_current_object(),
            _text(data.get("endpoint")),
            _text(keys.get("p256dh")),
            _text(keys.get("auth")),
        )
    except InvalidInput as invalid:
        return jsonify(error=invalid.message()), 400
    return jsonify(ok=True)


@bp.post("/push/subscription/delete")
@login_required
def unsubscribe() -> BaseResponse:
    data = request.get_json(silent=True) or {}
    push.unsubscribe(current_user._get_current_object(), _text(data.get("endpoint")))
    return jsonify(ok=True)


@bp.post("/g/<int:group_id>/notifications")
@member_required
def preferences(group_id: int) -> tuple[str, int] | str | BaseResponse:
    """NOT-02: the occasions for this group, checked boxes are on."""
    if not ConfirmForm().validate_on_submit():
        abort(400)
    chosen = set(request.form.getlist("kind"))
    enabled = {kind for kind in NotificationKind if kind.value in chosen}
    push.set_preferences(current_user._get_current_object(), group_id, enabled)
    if request.headers.get("HX-Request"):
        return render_template(
            "push/_preferences.html",
            group=g.group,
            preferences=push.preferences(current_user.id, group_id),
            form=ConfirmForm(),
            saved=True,
        )
    flash(t("push.saved"), "success")
    return redirect(url_for("settings.index", group_id=group_id, _anchor="benachrichtigungen"))


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""
