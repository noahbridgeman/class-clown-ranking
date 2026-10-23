import os


class Config:
    """Production defaults. Secrets and the database URL must come from the environment."""

    SECRET_KEY: str | None = None
    SQLALCHEMY_DATABASE_URI: str | None = None
    BASE_URL = "http://localhost:5000"
    # Only development may fall back to a SQLite file in instance/.
    ALLOW_SQLITE_FALLBACK = False
    MIN_SECRET_KEY_LENGTH = 32

    DEFAULT_LOCALE = "de"
    # When True, missing translation keys raise; otherwise the key itself is shown.
    I18N_STRICT = False

    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"


class DevConfig(Config):
    SECRET_KEY = "dev-insecure-key"
    ALLOW_SQLITE_FALLBACK = True
    MIN_SECRET_KEY_LENGTH = 0
    I18N_STRICT = True
    # The dev server runs on plain http://localhost.
    SESSION_COOKIE_SECURE = False


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    MIN_SECRET_KEY_LENGTH = 0
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    I18N_STRICT = True
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = False


CONFIGS: dict[str, type[Config]] = {"production": Config, "development": DevConfig}

# Config key -> environment variable. Applied only to configs selected via APP_ENV.
ENV_OVERRIDES = {
    "SECRET_KEY": "SECRET_KEY",
    "SQLALCHEMY_DATABASE_URI": "DATABASE_URL",
    "BASE_URL": "BASE_URL",
}


def config_from_env() -> type[Config]:
    name = os.environ.get("APP_ENV", "production")
    try:
        return CONFIGS[name]
    except KeyError:
        raise RuntimeError(f"Unknown APP_ENV {name!r}, expected one of {sorted(CONFIGS)}") from None


def env_overrides() -> dict[str, str]:
    return {key: os.environ[var] for key, var in ENV_OVERRIDES.items() if os.environ.get(var)}
