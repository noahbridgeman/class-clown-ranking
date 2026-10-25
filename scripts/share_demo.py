"""Serves the demo so friends can look at it through a tunnel, logged in as the viewer.

python scripts/demo.py --force       # fresh demo data, up to now
python scripts/share_demo.py         # serves it on 127.0.0.1:5050
ngrok http 127.0.0.1:5050            # second terminal, gives the public https link

Every visitor is the demo's main person (Jonas), without a login mail, so the link alone
is enough. Only for the demo database: no debugger, a random secret key per start, no
mails or pushes leave the machine, and the period update runs every minute in the
background. Stop with Ctrl+C; a visitor's changes stay until `demo.py --force`.
"""

import argparse
import secrets
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask  # noqa: E402
from flask_login import current_user, login_user  # noqa: E402
from sqlalchemy import select  # noqa: E402
from werkzeug.serving import run_simple  # noqa: E402

from app import create_app  # noqa: E402
from app.config import DevConfig  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import User  # noqa: E402
from app.services import periods  # noqa: E402

DEFAULT_DB = ROOT / "instance" / "demo.db"
TICK_SECONDS = 60


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"{db_path} fehlt. Erst python scripts/demo.py ausführen.")
        return 1
    app = shared_app(db_path, args.email)
    _start_ticker(app)
    address = f"127.0.0.1:{args.port}"
    print(f"Demo auf http://{address}, öffentlich mit: ngrok http {address}")
    run_simple("127.0.0.1", args.port, app, threaded=True)
    return 0


def shared_app(db_path: Path, email: str) -> Flask:
    config = type(
        "Config",
        (DevConfig,),
        {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            # The dev key is public; with it anyone could forge a session cookie.
            "SECRET_KEY": secrets.token_urlsafe(48),
            "MAIL_BACKEND": "memory",
            "PUSH_BACKEND": "memory",
        },
    )
    app = create_app(config)
    with app.app_context():
        viewer_id = db.session.scalar(select(User.id).where(User.email == email))
        db.session.remove()
        db.engine.dispose()  # the server threads open their own connections
    if viewer_id is None:
        raise SystemExit(f"Kein Konto {email} in {db_path}.")

    @app.before_request
    def log_in_as_viewer() -> None:
        if not current_user.is_authenticated:
            login_user(db.session.get(User, viewer_id))

    return app


def _start_ticker(app: Flask) -> None:
    def run() -> None:
        while True:
            time.sleep(TICK_SECONDS)
            with app.app_context():
                try:
                    periods.tick()
                except Exception:
                    app.logger.exception("tick failed")

    threading.Thread(target=run, daemon=True).start()


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demo über einen Tunnel teilen.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite-Datei der Demo")
    parser.add_argument("--email", default="jonas@example.org", help="Hauptperson der Demo")
    parser.add_argument("--port", type=int, default=5050)  # 5000 is AirPlay on macOS
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
