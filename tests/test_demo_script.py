import importlib.util
import sqlite3
from contextlib import closing
from pathlib import Path
from types import ModuleType

import pytest

from tests.factories import IN_WEEK_WINDOW

ROOT = Path(__file__).parent.parent


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("demo", ROOT / "scripts" / "demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("demo") / "demo.db"
    argv = ["--db", str(path), "--email", " Du@Example.org ", "--name", "Du"]
    assert _load().main(argv, now=IN_WEEK_WINDOW) == 0
    return path


def _rows(path: Path, sql: str) -> list[tuple]:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(sql).fetchall()


def test_groups_have_history_and_a_running_window(demo_db):
    rows = _rows(
        demo_db,
        "SELECT g.name, p.status, count(*) FROM periods p JOIN groups g ON g.id = p.group_id "
        "GROUP BY g.name, p.status ORDER BY g.name, p.status",
    )
    counts = {(name, status): n for name, status, n in rows}

    assert counts[("WG Hinterhof", "closed")] >= 8
    assert counts[("WG Hinterhof", "open")] == 1
    assert counts[("Büro", "closed")] >= 14
    assert counts[("Büro", "open")] == 1
    assert _rows(demo_db, "SELECT count(*) FROM period_results")[0][0] > 0


def test_own_account_leads_and_leaves_votes_open(demo_db):
    (viewer_id,) = _rows(demo_db, "SELECT id FROM users WHERE email = 'du@example.org'")[0]
    (admin_id,) = _rows(demo_db, "SELECT admin_user_id FROM groups WHERE name = 'WG Hinterhof'")[0]
    own_open_votes = _rows(
        demo_db,
        "SELECT count(*) FROM votes v JOIN periods p ON p.id = v.period_id "
        f"WHERE p.status = 'open' AND v.voter_user_id = {viewer_id}",
    )[0][0]

    assert admin_id == viewer_id
    assert own_open_votes <= 4  # two per group at most


def test_anonymous_periods_have_no_reasons(demo_db):
    rows = _rows(
        demo_db,
        "SELECT p.is_anonymous, count(v.reason) FROM votes v JOIN periods p "
        "ON p.id = v.period_id GROUP BY p.is_anonymous ORDER BY p.is_anonymous",
    )

    assert rows == [(0, rows[0][1]), (1, 0)]
    assert rows[0][1] > 0


def test_existing_file_needs_force(demo_db, capsys):
    demo = _load()

    assert demo.main(["--db", str(demo_db)], now=IN_WEEK_WINDOW) == 1
    assert "--force" in capsys.readouterr().out
