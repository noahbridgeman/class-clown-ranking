from dataclasses import asdict

from flask import Blueprint, Flask, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.wrappers import Response as BaseResponse

from app.clock import get_clock
from app.domain import scoring
from app.domain.types import Cadence
from app.i18n import t
from app.models import SettingField
from app.models.group import GROUP_NAME_MAX_LENGTH
from app.services import settings
from app.services.settings import GroupSettings, InvalidSettings, SettingValue
from app.web.access import admin_required, member_required
from app.web.forms import ConfirmForm

bp = Blueprint("settings", __name__)

Page = tuple[str, int] | BaseResponse

FIELD_LABELS = {
    SettingField.NAME: "settings.field_name",
    SettingField.CADENCE: "settings.field_cadence",
    SettingField.IS_ANONYMOUS: "settings.field_anonymity",
    SettingField.TIMEZONE: "settings.field_timezone",
    SettingField.K: "settings.field_k",
    SettingField.D: "settings.field_d",
}
CADENCE_LABELS = {Cadence.WEEKLY: "settings.weekly", Cadence.DAILY: "settings.daily"}


def register(app: Flask) -> None:
    app.add_template_global(display_value, "setting_value")
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


@bp.get("/g/<int:group_id>/settings")
@member_required
def index(group_id: int) -> str:
    return _render(settings.upcoming(g.group))


@bp.post("/g/<int:group_id>/settings")
@admin_required
def save(group_id: int) -> Page:
    current = settings.upcoming(g.group)
    if not ConfirmForm().validate_on_submit():
        return _render(current), 400
    try:
        wanted = settings.from_form(request.form, current)
        changes = settings.change(g.group, current_user._get_current_object(), wanted)
    except InvalidSettings as invalid:
        read = settings.read_form(request.form, current)
        return _render(read.values, invalid.errors, _param_texts(read)), 400
    flash(t("settings.saved" if changes else "settings.unchanged"), "success")
    return redirect(url_for("settings.index", group_id=group_id))


@bp.get("/g/<int:group_id>/settings/params")
@admin_required
def params(group_id: int) -> str:
    """HTMX: K and d for the chosen cadence, their bounds and the preview (SET-04, SET-05).

    On a cadence change the whole block is swapped, so K and d show the converted values.
    While typing only #params-info is taken (hx-select), so the inputs stay as typed.
    """
    read = settings.read_form(request.args, settings.upcoming(g.group))
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


def _param_texts(read: settings.FormInput) -> dict[str, str]:
    """What the K and d inputs show: the typed text, unless the values were converted."""
    texts = {}
    for name in ("k", "d"):
        typed = request.values.get(name)
        if typed is not None and not read.converted:
            texts[name] = typed
    return texts


def _render(values: GroupSettings, errors: dict | None = None, texts: dict | None = None) -> str:
    group = g.group
    pending = settings.pending_fields(group)
    zones = sorted(settings.timezones() | {values.timezone})  # keeps an invalid entry visible
    upcoming = settings.upcoming(group)
    return render_template(
        "settings/index.html",
        group=group,
        is_admin=group.admin_user_id == current_user.id,
        effective=settings.effective(group),
        pending=pending,
        pending_from=settings.takes_effect_at(group, get_clock().now()) if pending else None,
        pending_timezone=upcoming.timezone,
        now=get_clock().now(),
        log=settings.log(group.id),
        fields=settings.FIELDS,
        timezones={zone: zone for zone in zones},
        cadences=CADENCE_LABELS,
        name_max_length=GROUP_NAME_MAX_LENGTH,
        form=ConfirmForm(),
        live=False,
        **_params_context(values, errors or {}, texts or {}),
    )


def _params_context(values: GroupSettings, errors: dict, texts: dict[str, str]) -> dict:
    bounds = scoring.bounds(values.cadence, values.d)
    valid = not scoring.validate(values.params, values.cadence)
    preview = settings.preview(values.params, values.cadence) if valid else None
    decimals = settings.INPUT_DECIMALS
    return {
        "values": values,
        "errors": {field.value: error.message() for field, error in errors.items()},
        "k_text": texts.get("k", settings.format_param(values.k, decimals)),
        "d_text": texts.get("d", settings.format_param(values.d, decimals)),
        "k_bounds": settings.format_bounds(bounds.k_min, bounds.k_max),
        "d_bounds": settings.format_bounds(bounds.d_min, bounds.d_max),
        "preview": preview,
        "preview_data": asdict(preview) if preview else None,
    }
