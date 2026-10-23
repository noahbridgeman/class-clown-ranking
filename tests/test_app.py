import json
import re

import pytest
from flask import Flask, abort

from app import create_app
from app.config import TestConfig

STRONG_KEY = "k" * 32
PROD_ENV = {"APP_ENV": "production", "SECRET_KEY": STRONG_KEY, "DATABASE_URL": "sqlite://"}


@pytest.fixture
def env(monkeypatch):
    """Isolates create_app() from the developer's shell and .env file."""
    monkeypatch.setattr("app.load_dotenv", lambda: None)
    for var in ("APP_ENV", "SECRET_KEY", "DATABASE_URL", "BASE_URL", "FLASK_DEBUG"):
        monkeypatch.delenv(var, raising=False)

    def set_env(**values: str) -> None:
        for name, value in values.items():
            monkeypatch.setenv(name, value)

    return set_env


def test_index_renders_german_ui(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<html lang="de">' in html
    assert "Spaßvogel-Ranking" in html


def test_base_template_exposes_csrf_token_for_htmx(client):
    html = client.get("/").get_data(as_text=True)
    assert '<meta name="csrf-token" content="' in html
    assert "X-CSRFToken" in html


class TestErrorPages:
    def test_unknown_route_renders_german_404(self, client):
        response = client.get("/gibt-es-nicht")
        assert response.status_code == 404
        assert "Seite nicht gefunden" in response.get_data(as_text=True)

    def test_server_error_renders_german_500(self, app):
        app.config["PROPAGATE_EXCEPTIONS"] = False

        @app.get("/boom")
        def boom():
            raise RuntimeError("boom")

        response = app.test_client().get("/boom")
        assert response.status_code == 500
        assert "Etwas ist schiefgelaufen" in response.get_data(as_text=True)

    def test_other_http_errors_render_german_page(self, client):
        response = client.post("/")
        assert response.status_code == 405
        html = response.get_data(as_text=True)
        assert "Fehler 405" in html
        assert "Method Not Allowed" not in html
        assert set(response.headers["Allow"].split(", ")) == {"GET", "HEAD", "OPTIONS"}
        assert response.content_type.startswith("text/html")

    def test_error_responses_vary_on_htmx_header(self, client):
        vary = client.get("/gibt-es-nicht").headers["Vary"]
        assert "HX-Request" in vary.split(", ")

    def test_boosted_htmx_navigation_gets_the_full_page(self, client):
        headers = {"HX-Request": "true", "HX-Boosted": "true"}
        html = client.get("/gibt-es-nicht", headers=headers).get_data(as_text=True)
        assert "<html" in html

    def test_htmx_is_configured_to_swap_error_responses(self, client):
        html = client.get("/").get_data(as_text=True)
        raw = re.search(r"<meta name=\"htmx-config\" content='([^']+)'>", html).group(1)
        rules = {rule["code"]: rule for rule in json.loads(raw)["responseHandling"]}
        assert rules["[45].."]["swap"] is True
        assert rules["[45].."]["error"] is True

    def test_htmx_requests_get_only_the_message_fragment(self, client):
        response = client.get("/gibt-es-nicht", headers={"HX-Request": "true"})
        html = response.get_data(as_text=True)
        assert response.status_code == 404
        assert "Seite nicht gefunden" in html
        assert "<html" not in html

    def test_http_error_keeps_its_status(self, app):
        @app.get("/teapot")
        def teapot():
            abort(418)

        response = app.test_client().get("/teapot")
        assert response.status_code == 418
        assert "Fehler 418" in response.get_data(as_text=True)


class TestCsrf:
    @pytest.fixture
    def csrf_client(self):
        class WithCsrf(TestConfig):
            WTF_CSRF_ENABLED = True

        app = create_app(WithCsrf)

        @app.post("/echo")
        def echo():
            return "ok"

        return app.test_client()

    def test_post_without_token_is_rejected_in_german(self, csrf_client):
        response = csrf_client.post("/echo")
        assert response.status_code == 400
        assert "Sitzung abgelaufen" in response.get_data(as_text=True)

    def test_post_with_token_from_page_is_accepted(self, csrf_client):
        html = csrf_client.get("/").get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
        response = csrf_client.post("/echo", headers={"X-CSRFToken": token})
        assert response.status_code == 200


class TestConfigSelection:
    def test_defaults_to_production(self, env):
        env(SECRET_KEY=STRONG_KEY, DATABASE_URL="sqlite://")
        assert create_app().config["SESSION_COOKIE_SECURE"] is True

    def test_production_requires_secret_key(self, env):
        env(APP_ENV="production", DATABASE_URL="sqlite://")
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            create_app()

    def test_flask_debug_does_not_weaken_production(self, env):
        env(APP_ENV="production", DATABASE_URL="sqlite://", FLASK_DEBUG="1")
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            create_app()

    def test_production_requires_database_url(self, env):
        env(APP_ENV="production", SECRET_KEY=STRONG_KEY)
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            create_app()

    def test_production_cookies_are_hardened(self, env):
        env(**PROD_ENV)
        config = create_app().config
        assert config["SESSION_COOKIE_SECURE"] is True
        assert config["SESSION_COOKIE_HTTPONLY"] is True
        assert config["SESSION_COOKIE_SAMESITE"] == "Lax"

    def test_environment_overrides_config(self, env):
        env(**PROD_ENV, BASE_URL="https://example.org")
        config = create_app().config
        assert config["SECRET_KEY"] == STRONG_KEY
        assert config["SQLALCHEMY_DATABASE_URI"] == "sqlite://"
        assert config["BASE_URL"] == "https://example.org"

    @pytest.mark.parametrize("key", ["", "   "])
    def test_production_rejects_empty_secret_key(self, env, key):
        env(APP_ENV="production", SECRET_KEY=key, DATABASE_URL="sqlite://")
        with pytest.raises(RuntimeError, match="SECRET_KEY must be set"):
            create_app()

    @pytest.mark.parametrize("key", ["dev-insecure-key", "k" * 31])
    def test_production_rejects_short_secret_key(self, env, key):
        env(APP_ENV="production", SECRET_KEY=key, DATABASE_URL="sqlite://")
        with pytest.raises(RuntimeError, match="at least 32"):
            create_app()

    def test_development_falls_back_to_sqlite_in_instance_dir(self, env, monkeypatch, tmp_path):
        monkeypatch.setattr(Flask, "auto_find_instance_path", lambda _self: str(tmp_path / "inst"))
        env(APP_ENV="development")
        app = create_app()
        assert app.config["SQLALCHEMY_DATABASE_URI"] == f"sqlite:///{tmp_path / 'inst' / 'app.db'}"
        assert (tmp_path / "inst").is_dir()
        assert app.config["SESSION_COOKIE_SECURE"] is False
        assert app.config["SECRET_KEY"]

    def test_unknown_app_env_fails(self, env):
        env(APP_ENV="staging")
        with pytest.raises(RuntimeError, match="APP_ENV"):
            create_app()

    def test_explicit_config_ignores_environment(self, env):
        env(DATABASE_URL="postgresql://real/db")
        app = create_app(TestConfig)
        assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///:memory:"
