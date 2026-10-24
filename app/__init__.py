from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask

from app import cli, i18n
from app.clock import Clock, SystemClock
from app.config import Config, config_from_env, env_overrides
from app.extensions import csrf, db, migrate
from app.services import mail


def create_app(config: type[Config] | None = None, clock: Clock | None = None) -> Flask:
    """Without an explicit config, APP_ENV selects one and the environment overrides it."""
    app = Flask(__name__, instance_relative_config=True)
    if config is None:
        load_dotenv()
        app.config.from_object(config_from_env())
        app.config.from_mapping(env_overrides())
    else:
        app.config.from_object(config)
    _require_secret_key(app)
    _require_base_url(app)
    _ensure_database_uri(app)

    app.extensions["clock"] = clock or SystemClock()

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    i18n.init_app(app)
    mail.init_app(app)
    cli.register(app)

    from app import models  # noqa: F401  (registers models for migrations)
    from app.web import auth, errors, main

    auth.register(app)
    app.register_blueprint(main.bp)
    errors.register(app)

    return app


def _require_secret_key(app: Flask) -> None:
    key = (app.config["SECRET_KEY"] or "").strip()
    if not key:
        raise RuntimeError("SECRET_KEY must be set (see .env.example)")
    if len(key) < app.config["MIN_SECRET_KEY_LENGTH"]:
        raise RuntimeError(
            f"SECRET_KEY must have at least {app.config['MIN_SECRET_KEY_LENGTH']} characters"
        )


def _require_base_url(app: Flask) -> None:
    """Login links point here, so a wrong value sends everyone to localhost."""
    base_url = (app.config["BASE_URL"] or "").strip()
    if not base_url:
        raise RuntimeError("BASE_URL must be set (see .env.example)")
    parts = urlsplit(base_url)
    schemes = {"https"} if app.config["REQUIRE_HTTPS_BASE_URL"] else {"https", "http"}
    if parts.scheme not in schemes or not parts.netloc:
        raise RuntimeError(f"BASE_URL must be an absolute {' or '.join(sorted(schemes))} URL")
    app.config["BASE_URL"] = base_url.rstrip("/")


def _ensure_database_uri(app: Flask) -> None:
    if app.config["SQLALCHEMY_DATABASE_URI"]:
        return
    if not app.config["ALLOW_SQLITE_FALLBACK"]:
        raise RuntimeError("DATABASE_URL must be set (see .env.example)")
    instance = Path(app.instance_path)
    instance.mkdir(parents=True, exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{instance / 'app.db'}"
