import math

from flask import Blueprint, Flask, g, render_template
from flask_login import current_user

from app.domain import scoring
from app.domain.formatting import format_net
from app.domain.types import Cadence
from app.i18n import iso_week, t, window_dates
from app.models import Group, Period
from app.services import overview
from app.web.access import member_required

bp = Blueprint("overview", __name__)


def register(app: Flask) -> None:
    app.add_template_filter(format_net, "net")
    app.register_blueprint(bp)


@bp.get("/g/<int:group_id>/overview")
@bp.get("/g/<int:group_id>/overview/<int:seq>")
@member_required
def index(group_id: int, seq: int | None = None) -> str:
    """OVW-01…04, OVW-06, OVW-07: one period per page, the newest by default (A23)."""
    page = overview.period_page(g.group, current_user._get_current_object(), seq)
    return render_template(
        "overview/index.html",
        group=g.group,
        page=page,
        period_label=period_label(g.group, page.period) if page else None,
        max_volume=max((max(e.ups, e.downs) for e in page.entries), default=0) if page else 0,
    )


@bp.get("/g/<int:group_id>/members/<int:user_id>")
@member_required
def member(group_id: int, user_id: int) -> str:
    """OVW-05: a member's results and, where not anonymous, votes over all periods."""
    history = overview.member_history(g.group, current_user._get_current_object(), user_id)
    return render_template(
        "overview/member.html",
        group=g.group,
        history=history,
        labels={item.period.id: period_label(g.group, item.period) for item in history.items},
        chart=score_chart(history.scores),
    )


def period_label(group: Group, period: Period) -> str:
    """ "KW 43 · 18./19.10." for weekly periods, "26.10." for daily ones (by the snapshot)."""
    dates = window_dates(period.opens_at, period.closes_at, group.timezone)
    if period.cadence == Cadence.WEEKLY:
        return t("overview.week", week=iso_week(period.closes_at, group.timezone), dates=dates)
    return dates


# The chart's drawing area (viewBox 0 0 320 110): x over the periods, y over the range.
CHART_LEFT, CHART_RIGHT, CHART_TOP, CHART_BOTTOM = 26, 314, 6, 104
START_SCORE = 5.0
LABEL_GAP = 24  # viewBox units between two axis labels


def score_chart(scores: list[float]) -> dict[str, object] | None:
    """A server-drawn line of the scores, oldest first; None below two points.

    Like the graph, the y axis zooms to the data in whole numbers within 0…10
    (docs/design.md, section 4); the start line shows when it is in range.
    """
    if len(scores) < 2:
        return None
    low = max(0, math.floor(min(scores) - 0.5))
    high = min(int(scoring.SCORE_MAX), math.ceil(max(scores) + 0.5))

    def x(i: int) -> float:
        return round(CHART_LEFT + (CHART_RIGHT - CHART_LEFT) * i / (len(scores) - 1), 1)

    def y(score: float) -> float:
        return round(CHART_BOTTOM - (CHART_BOTTOM - CHART_TOP) * (score - low) / (high - low), 1)

    start_y = y(START_SCORE) if low < START_SCORE < high else None
    return {
        "points": " ".join(f"{x(i)},{y(s)}" for i, s in enumerate(scores)),
        "left": CHART_LEFT,
        "right": CHART_RIGHT,
        "low": low,
        "high": high,
        "top_y": CHART_TOP,
        "bottom_y": CHART_BOTTOM,
        "start_y": start_y,
        # Edge labels give way to the start label when it is close.
        "show_high": start_y is None or start_y - CHART_TOP >= LABEL_GAP,
        "show_low": start_y is None or CHART_BOTTOM - start_y >= LABEL_GAP,
        "end_x": x(len(scores) - 1),
        "end_y": y(scores[-1]),
    }
