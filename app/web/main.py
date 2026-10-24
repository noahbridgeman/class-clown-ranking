from flask import Blueprint, render_template
from flask_login import current_user

from app.services import groups

bp = Blueprint("main", __name__)


@bp.get("/")
def index() -> str:
    """Landing page for guests, group selection for members."""
    user_groups = groups.groups_of(current_user) if current_user.is_authenticated else []
    return render_template("index.html", groups=user_groups)
