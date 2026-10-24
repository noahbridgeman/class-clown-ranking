import os
from collections.abc import Callable
from datetime import timedelta


class Config:
    """Production defaults. Secrets and the database URL must come from the environment."""

    SECRET_KEY: str | None = None
    SQLALCHEMY_DATABASE_URI: str | None = None
    # Login links are built from this, never from the request's Host header.
    BASE_URL: str | None = None
    # Login tokens travel in the link and the cookies are Secure, so production needs https.
    REQUIRE_HTTPS_BASE_URL = True
    # Only development may fall back to a SQLite file in instance/.
    ALLOW_SQLITE_FALLBACK = False
    MIN_SECRET_KEY_LENGTH = 32

    DEFAULT_LOCALE = "de"
    # When True, missing translation keys raise; otherwise the key itself is shown.
    I18N_STRICT = False

    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # AUTH-06: sliding, every visit renews it (see web.auth._slide_remember_cookie).
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"

    LOGIN_TOKEN_LIFETIME = timedelta(minutes=15)  # AUTH-02
    LOGIN_MAILS_PER_HOUR = 5  # NFA-09

    # smtp | console (prints mails) | memory (collects mails for tests)
    MAIL_BACKEND = "smtp"
    MAIL_HOST: str | None = None
    MAIL_PORT = 587
    MAIL_USERNAME: str | None = None
    MAIL_PASSWORD: str | None = None
    MAIL_STARTTLS = True
    MAIL_FROM: str | None = None


class DevConfig(Config):
    SECRET_KEY = "dev-insecure-key"
    # Not localhost: on macOS it resolves to ::1 first, where the AirPlay receiver
    # holds port 5000, while the dev server only listens on 127.0.0.1.
    BASE_URL = "http://127.0.0.1:5000"
    REQUIRE_HTTPS_BASE_URL = False
    ALLOW_SQLITE_FALLBACK = True
    MIN_SECRET_KEY_LENGTH = 0
    I18N_STRICT = True
    # The dev server runs on plain http://localhost.
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    MAIL_BACKEND = "console"


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    MIN_SECRET_KEY_LENGTH = 0
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    BASE_URL = "http://localhost:5000"
    REQUIRE_HTTPS_BASE_URL = False
    I18N_STRICT = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = False
    MAIL_BACKEND = "memory"


CONFIGS: dict[str, type[Config]] = {"production": Config, "development": DevConfig}

# Config key -> environment variable. Applied only to configs selected via APP_ENV.
ENV_OVERRIDES = {
    "SECRET_KEY": "SECRET_KEY",
    "SQLALCHEMY_DATABASE_URI": "DATABASE_URL",
    "BASE_URL": "BASE_URL",
    "MAIL_BACKEND": "MAIL_BACKEND",
    "MAIL_HOST": "MAIL_HOST",
    "MAIL_PORT": "MAIL_PORT",
    "MAIL_USERNAME": "MAIL_USERNAME",
    "MAIL_PASSWORD": "MAIL_PASSWORD",
    "MAIL_STARTTLS": "MAIL_STARTTLS",
    "MAIL_FROM": "MAIL_FROM",
}


def config_from_env() -> type[Config]:
    name = os.environ.get("APP_ENV", "production")
    try:
        return CONFIGS[name]
    except KeyError:
        raise RuntimeError(f"Unknown APP_ENV {name!r}, expected one of {sorted(CONFIGS)}") from None


def env_overrides() -> dict[str, object]:
    return {
        key: _CONVERTERS.get(key, str)(os.environ[var])
        for key, var in ENV_OVERRIDES.items()
        if os.environ.get(var)
    }


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"Expected a boolean, got {value!r}")


_CONVERTERS: dict[str, Callable[[str], object]] = {"MAIL_PORT": int, "MAIL_STARTTLS": _parse_bool}
