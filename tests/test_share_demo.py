import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from app.config import DevConfig
from app.extensions import db
from tests.factories import IN_WEEK_WINDOW

ROOT = Path(__file__).parent.parent


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def shared(tmp_path_factory: pytest.TempPathFactory):
    path = tmp_path_factory.mktemp("share") / "demo.db"
    assert _load("demo").main(["--db", str(path)], now=IN_WEEK_WINDOW) == 0
    app = _load("share_demo").shared_app(path, "jonas@example.org")
    yield app
    with app.app_context():
        db.engine.dispose()


def test_visitors_see_the_demo_as_the_viewer_without_logging_in(shared):
    page = shared.test_client().get("/", follow_redirects=True)
    assert page.status_code == 200
    assert "WG Hinterhof" in page.text and "Büro" in page.text


def test_does_not_use_the_public_dev_key(shared):
    assert shared.config["SECRET_KEY"] != DevConfig.SECRET_KEY
    assert len(shared.config["SECRET_KEY"]) >= 32
    assert not shared.debug


def test_unknown_viewer_stops(shared):
    path = Path(shared.config["SQLALCHEMY_DATABASE_URI"].removeprefix("sqlite:///"))
    with pytest.raises(SystemExit):
        _load("share_demo").shared_app(path, "niemand@example.org")
