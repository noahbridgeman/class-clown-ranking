from dataclasses import replace

from flask import (
    Blueprint,
    Flask,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from werkzeug.wrappers import Response as BaseResponse

from app.clock import get_clock
from app.domain import scoring
from app.domain.types import Cadence
from app.i18n import t
from app.models import SettingField
from app.models.group import GROUP_NAME_MAX_LENGTH
from app.models.user import EMAIL_MAX_LENGTH
from app.services import invitations, membership, push, settings
from app.services.settings import GroupSettings, InvalidSettings, SettingValue
from app.web.access import admin_required, member_required
from app.web.forms import ConfirmForm, EmailForm

bp = Blueprint("settings", __name__)

Page = tuple[str, int] | BaseResponse

FIELD_LABELS = settings.FIELD_LABELS
CADENCE_LABELS = {Cadence.WEEKLY: "settings.weekly", Cadence.DAILY: "settings.daily"}
# What K and d mean, per cadence (docs/design/screens/einstellungen.html).
HINTS = {
    Cadence.WEEKLY: ("settings.k_hint_weekly", "settings.d_hint_weekly"),
    Cadence.DAILY: ("settings.k_hint_daily", "settings.d_hint_daily"),
}


# What members without the admin role read (SET-02); the timezone is not shown (SET-07).
READ_FIELDS = [
    SettingField.NAME,
    SettingField.CADENCE,
    SettingField.IS_ANONYMOUS,
    SettingField.K,
    SettingField.D,
]


def register(app: Flask) -> None:
    app.add_template_global(display_value, "setting_value")
    app.add_template_global(pending_value)
    app.add_template_global(FIELD_LABELS, "setting_labels")
    app.add_template_filter(settings.format_param, "param")
    app.register_blueprint(bp)


def display_value(field: SettingField, value: SettingValue | str) -> str:
    """A setting as people read it; stored text values are parsed first."""
    if isinstance(value, str) and field not in (SettingField.NAME, SettingField.TIMEZONE):
        value = settings.parse(field, value)
    if field is SettingField.CADENCE:
        return t(CADENCE_LABELS[Cadence(value)])
    if field is SettingField.IS_ANONYMOUS:
        return t("settings.anonymous" if value else "settings.open")
    if field in (SettingField.K, SettingField.D):
        return settings.format_param(float(value))
    return str(value)


def pending_value(field: SettingField, value: SettingValue) -> str:
    """In the pending block anonymity reads "an"/"aus" (docs/design/screens/einstellungen.html)."""
    if field is SettingField.IS_ANONYMOUS:
        return t("settings.on" if value else "settings.off")
    return display_value(field, value)


@bp.get("/g/<int:group_id>/settings")
@member_required
def index(group_id: int) -> str:
    return render_page()


@bp.post("/g/<int:group_id>/settings")
@admin_required
def save(group_id: int) -> Page:
    current = settings.upcoming(g.group)
    if not ConfirmForm().validate_on_submit():
        return render_page(current), 400
    read = settings.read_form(request.form, current)
    if request.form.get("action") == "restore":
        # Without JavaScript "restore defaults" only fills in the form; nothing is saved.
        return render_page(_with_defaults(read.values))
    try:
        wanted = settings.from_form(request.form, current)
        changes = settings.change(g.group, current_user._get_current_object(), wanted)
    except InvalidSettings as invalid:
        return render_page(read.values, invalid.errors, _param_texts(read)), 400
    flash(t("settings.saved" if changes else "settings.unchanged"), "success")
    return redirect(url_for("settings.index", group_id=group_id))


@bp.get("/g/<int:group_id>/settings/params")
@admin_required
def params(group_id: int) -> str:
    """HTMX: K and d for the chosen cadence, their bounds and the preview (SET-04, SET-05).

    A cadence change or "restore defaults" swaps the whole block, so K and d show the new
    values. While typing only #params-info is taken (hx-select), so the inputs stay as typed.
    """
    read = settings.read_form(request.args, settings.upcoming(g.group))
    if request.args.get("restore"):
        return render_template(
            "settings/_params.html",
            group=g.group,
            live=True,
            **_params_context(_with_defaults(read.values), {}, {}),
        )
    errors = {}
    try:
        settings.validate(read.values)
    except InvalidSettings as invalid:
        errors = {f: e for f, e in invalid.errors.items() if f in (SettingField.K, SettingField.D)}
    return render_template(
        "settings/_params.html",
        group=g.group,
        live=True,
        **_params_context(read.values, errors, _param_texts(read)),
    )


def _with_defaults(values: GroupSettings) -> GroupSettings:
    """SET-05: the standard K and d of the chosen cadence."""
    defaults = scoring.default_params(values.cadence)
    return replace(values, k=defaults.k, d=defaults.d)


def _param_texts(read: settings.FormInput) -> dict[str, str]:
    """What the K and d inputs show: the typed text, unless the values were converted."""
    texts = {}
    for name in ("k", "d"):
        typed = request.values.get(name)
        if typed is not None and not read.converted:
            texts[name] = typed
    return texts


def render_page(
    values: GroupSettings | None = None,
    errors: dict | None = None,
    texts: dict | None = None,
    invite_form: EmailForm | None = None,
    invite_error: str | None = None,
) -> str:
    """The settings page with members and invitations (docs/design/screens/einstellungen.html).

    The invitation routes render it too, when an invitation fails without JavaScript.
    """
    group = g.group
    now = get_clock().now()
    values = values or settings.upcoming(group)
    is_admin = group.admin_user_id == current_user.id
    pending = settings.pending_fields(group)
    effective = settings.effective(group)
    return render_template(
        "settings/index.html",
        group=group,
        is_admin=is_admin,
        effective=effective,
        read_fields=READ_FIELDS,
        pending=[(field, effective.value(field), value) for field, value in pending.items()],
        pending_from=settings.takes_effect_at(group, now) if pending else None,
        pending_timezone=settings.upcoming(group).timezone,
        next_from=settings.takes_effect_at(group, now),
        now=now,
        cadences=CADENCE_LABELS,
        name_max_length=GROUP_NAME_MAX_LENGTH,
        form=ConfirmForm(),
        members=membership.active_members(group.id),
        max_group_size=current_app.config["MAX_GROUP_SIZE"],
        invitations=invitations.invitations_of(group) if is_admin else [],
        invite_form=invite_form or EmailForm(formdata=None),
        invite_error=invite_error,
        email_max_length=EMAIL_MAX_LENGTH,
        live=False,
        notification_preferences=push.preferences(current_user.id, group.id),
        **_params_context(values, errors or {}, texts or {}),
    )


# The preview's drawing area (viewBox 0 0 320 124): x from week 0 to the end, y from 10 to 0.
PREVIEW_LEFT, PREVIEW_RIGHT, PREVIEW_TOP, PREVIEW_BOTTOM = 10, 310, 6, 112
PREVIEW_LABEL_Y = 122  # the week labels below the drawing area


def _preview_points(preview: settings.Preview) -> dict[str, object]:
    end = preview.weeks[-1]

    def x(week: float) -> float:
        return round(PREVIEW_LEFT + (PREVIEW_RIGHT - PREVIEW_LEFT) * week / end, 1)

    def y(score: float) -> float:
        span = PREVIEW_BOTTOM - PREVIEW_TOP
        return round(PREVIEW_BOTTOM - span * score / scoring.SCORE_MAX, 1)

    def line(scores: list[float]) -> str:
        return " ".join(f"{x(w)},{y(s)}" for w, s in zip(preview.weeks, scores, strict=True))

    return {
        "left": PREVIEW_LEFT,
        "right": PREVIEW_RIGHT,
        "label_y": PREVIEW_LABEL_Y,
        "up": line(preview.up),
        "down": line(preview.down),
        "pause_x": x(preview.pause_week),
        "start_y": y(5.0),
        "top_y": y(scoring.SCORE_MAX),
        "bottom_y": y(0.0),
        "weeks": round(end),
    }


def _params_context(values: GroupSettings, errors: dict, texts: dict[str, str]) -> dict:
    bounds = scoring.bounds(values.cadence, values.d)
    valid = not scoring.validate(values.params, values.cadence)
    preview = settings.preview(values.params, values.cadence) if valid else None
    decimals = settings.INPUT_DECIMALS
    return {
        "values": values,
        "errors": {field.value: error.message() for field, error in errors.items()},
        "k_text": texts.get("k", settings.format_param(values.k, decimals, min_decimals=2)),
        "d_text": texts.get("d", settings.format_param(values.d, decimals, min_decimals=2)),
        "k_hint": HINTS[values.cadence][0],
        "d_hint": HINTS[values.cadence][1],
        "k_bounds": settings.format_bounds(bounds.k_min, bounds.k_max),
        "d_bounds": settings.format_bounds(bounds.d_min, bounds.d_max),
        "preview": _preview_points(preview) if preview else None,
    }
