"""Structural rules from CLAUDE.md that are easy to break by accident."""

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
APP_DIR = ROOT / "app"
DOMAIN_DIR = APP_DIR / "domain"
CLOCK_MODULE = APP_DIR / "clock.py"

# Fully qualified names that read the system time, in Python or in SQL.
PYTHON_TIME = {
    "datetime.datetime.now",
    "datetime.datetime.utcnow",
    "datetime.datetime.today",
    "datetime.date.today",
    *(
        f"time.{name}"
        for name in (
            "time",
            "time_ns",
            "monotonic",
            "monotonic_ns",
            "perf_counter",
            "perf_counter_ns",
            "localtime",
            "gmtime",
            "ctime",
            "asctime",
            "strftime",
        )
    ),
}
SQL_FUNC_MODULES = (
    "sqlalchemy.func",
    "sqlalchemy.sql.func",
    "sqlalchemy.sql.expression.func",
    "app.extensions.db.func",
)
SQL_TIME_FUNCS = (
    "now",
    "current_timestamp",
    "current_date",
    "current_time",
    "localtimestamp",
    "localtime",
    "sysdate",
)
SYSTEM_TIME = PYTHON_TIME | {f"{m}.{f}" for m in SQL_FUNC_MODULES for f in SQL_TIME_FUNCS}
# SQL text such as text("CURRENT_TIMESTAMP") or func.datetime("now").
SQL_TIME_LITERALS = {
    "now",
    "now()",
    "current_timestamp",
    "current_date",
    "current_time",
    "localtimestamp",
}

# Standard library modules that would make the domain impure or non-deterministic (SCO-09).
DOMAIN_FORBIDDEN_STDLIB = {
    "os",
    "sys",
    "time",
    "random",
    "secrets",
    "uuid",
    "sqlite3",
    "dbm",
    "shelve",
    "socket",
    "subprocess",
    "threading",
    "multiprocessing",
    "asyncio",
    "urllib",
    "http",
    "logging",
}


def _python_files(root: Path) -> list[Path]:
    files = sorted(root.rglob("*.py"))
    assert files, f"no Python files found in {root}"
    return files


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _package(path: Path) -> str:
    module = _module_name(path)
    return module if path.name == "__init__.py" else module.rpartition(".")[0]


def _resolve_from(node: ast.ImportFrom, package: str) -> str:
    if node.level == 0:
        return node.module or ""
    base = package.split(".")
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def _imported_modules(tree: ast.AST, package: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            source = _resolve_from(node, package)
            # "from pkg import name" may import a submodule, so count both.
            modules.add(source)
            modules.update(f"{source}.{alias.name}" for alias in node.names)
    return modules


def _is_allowed_in_domain(module: str) -> bool:
    top = module.split(".")[0]
    return (
        module == "app.domain"
        or module.startswith("app.domain.")
        or (top in sys.stdlib_module_names and top not in DOMAIN_FORBIDDEN_STDLIB)
    )


def _aliases(tree: ast.AST, package: str) -> dict[str, str]:
    """Maps local names to the fully qualified object they are bound to."""
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    names[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    names[top] = top
        elif isinstance(node, ast.ImportFrom):
            source = _resolve_from(node, package)
            for alias in node.names:
                names[alias.asname or alias.name] = f"{source}.{alias.name}"
    return names


def _qualified(node: ast.expr, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    if isinstance(node, ast.Attribute):
        base = _qualified(node.value, aliases)
        return f"{base}.{node.attr}" if base else None
    return None


def _system_time_uses(source: str, package: str = "app") -> list[int]:
    """Lines that reference a system time function, called or not (e.g. default=datetime.now)."""
    tree = ast.parse(source)
    aliases = _aliases(tree, package)
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if (isinstance(node, ast.Name | ast.Attribute) and _qualified(node, aliases) in SYSTEM_TIME)
        or (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.strip().lower() in SQL_TIME_LITERALS
        )
    )


def test_domain_imports_only_stdlib_and_domain():
    violations = []
    for path in _python_files(DOMAIN_DIR):
        tree = ast.parse(path.read_text())
        for module in _imported_modules(tree, _package(path)):
            if not _is_allowed_in_domain(module):
                violations.append(f"{path.relative_to(ROOT)}: {module}")
    assert not violations


def test_system_time_is_only_read_by_the_clock():
    violations = []
    for path in _python_files(APP_DIR):
        if path == CLOCK_MODULE:
            continue
        for line in _system_time_uses(path.read_text(), _package(path)):
            violations.append(f"{path.relative_to(ROOT)}:{line}")
    assert not violations


@pytest.mark.parametrize(
    "source",
    [
        "from datetime import datetime\ndatetime.now(UTC)",
        "import datetime\ndatetime.datetime.now()",
        "from datetime import datetime\ndatetime.today()",
        "from datetime import date\ndate.today()",
        "import datetime as dt\ndt.datetime.utcnow()",
        "from datetime import datetime as D\nD.now()",
        "from datetime import datetime\nx = mapped_column(default=datetime.now)",
        "import time\ntime.time()",
        "from time import monotonic\nmonotonic()",
        "from sqlalchemy import func\nx = mapped_column(server_default=func.now())",
        "from app.extensions import db\ndb.func.now()",
        "from ..extensions import db\ndb.func.now()",
        "from sqlalchemy import func\nfunc.current_date()",
        "from sqlalchemy import func\nfunc.localtimestamp()",
        "from sqlalchemy import func\nfunc.datetime('now')",
        "from sqlalchemy import text\nx = mapped_column(server_default=text('CURRENT_TIMESTAMP'))",
        "import time\ntime.strftime('%Y')",
    ],
)
def test_detector_catches_system_time(source):
    assert _system_time_uses(source, package="app.models")


@pytest.mark.parametrize(
    "source",
    [
        "clock.now()",
        "from app.clock import get_clock\nget_clock().now()",
        "from datetime import time\ntime(13, 0)",
        "from datetime import datetime\nvalue: datetime\nvalue.time()",
    ],
)
def test_detector_allows_clock_and_time_values(source):
    assert not _system_time_uses(source)


@pytest.mark.parametrize(
    ("source", "allowed"),
    [
        ("import math", True),
        ("from zoneinfo import ZoneInfo", True),
        ("from .scoring import net", True),
        ("from app.domain.types import UserId", True),
        ("import flask", False),
        ("from sqlalchemy.orm import Session", False),
        ("from ..extensions import db", False),
        ("from .. import clock", False),
        ("from app.clock import get_clock", False),
        ("import werkzeug", False),
        ("import os", False),
        ("import random", False),
        ("import sqlite3", False),
        ("from time import monotonic", False),
        ("from datetime import datetime, time", True),
        ("from dataclasses import dataclass", True),
    ],
)
def test_domain_import_rules(source, allowed):
    modules = _imported_modules(ast.parse(source), "app.domain")
    assert all(map(_is_allowed_in_domain, modules)) is allowed
