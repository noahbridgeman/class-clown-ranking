"""scripts/screenshots.py without Chrome: rendering the pages and comparing shots."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parent.parent
EXPECTED_ERRORS = {"not_found", "forbidden"}


@pytest.fixture(scope="module")
def script() -> ModuleType:
    path = ROOT / "scripts" / "screenshots.py"
    spec = importlib.util.spec_from_file_location("screenshots", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def pages(script) -> dict[str, str]:
    return script.render_pages()


def test_only_the_intended_pages_are_errors(pages):
    errors = {
        name
        for name, html in pages.items()
        if "Seite nicht gefunden" in html or "Kein Zugriff" in html
    }
    assert errors == EXPECTED_ERRORS


def test_states_are_visible(pages):
    assert "Du hast 1 von 2 bewertet" in pages["vote_open"]
    assert "Nächstes Voting in" in pages["vote_closed"]
    assert "<details open " in pages["settings_admin_open"]
    assert "ZURÜCKGEZOGEN" in pages["invitations"]


def test_localize_points_to_the_working_copy(script):
    html = script.localize(
        '<link href="/static/css/app.css"><meta name="csrf-token" content="abc">'
        '<script src="https://cdn.example/x.js" defer></script>'
    )
    assert (ROOT / "app" / "static").as_uri() + "/css/app.css" in html
    assert 'content="x"' in html
    assert "cdn.example" not in html


def test_compare(script, tmp_path, capsys):
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    for folder in (before, after):
        (folder / "same.png").write_bytes(b"a")
    (before / "changed.png").write_bytes(b"a")
    (after / "changed.png").write_bytes(b"b")
    (before / "gone.png").write_bytes(b"a")

    assert script.differences(before, after) == ["changed.png", "gone.png"]
    assert script.main(["compare", str(before), str(after)]) == 1
    assert "1 von 3 Screenshots gleich." in capsys.readouterr().out
    assert script.main(["compare", str(before), str(before)]) == 0


def test_design_check_renders_every_reference():
    """The design check seeds its own data and maps each page to a reference screen."""
    path = ROOT / "scripts" / "design_check.py"
    spec = importlib.util.spec_from_file_location("design_check", path)
    design_check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(design_check)
    pages = design_check.render()
    names = {page.name for page in pages}
    assert names == {
        "ranking",
        "ranking-neue-gruppe",
        "voting",
        "voting-geschlossen",
        "einstellungen",
    }
    for page in pages:
        assert (design_check.SCREENS / page.reference).exists()
        assert "<html" in page.html
    ranking = next(page for page in pages if page.name == "ranking")
    assert set(ranking.graph) == set(design_check.RANGES)
