import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parent.parent


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("simulate", ROOT / "scripts" / "simulate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_prints_curves(capsys):
    assert _load().main(["--k", "0.5", "--d", "0.95", "--periods", "6"]) == 0

    out = capsys.readouterr().out
    assert "K = 0.5, d = 0.95, Takt = weekly" in out
    assert "immer top" in out


def test_script_warns_about_invalid_params(capsys):
    _load().main(["--k", "5", "--periods", "2"])

    assert "außerhalb der Grenzen: k" in capsys.readouterr().out


def test_script_shows_last_period(capsys):
    _load().main(["--periods", "1"])

    rows = capsys.readouterr().out.splitlines()
    assert rows[1].split() == ["1"]
    assert rows[2].split()[-1] == "6,2"


def test_script_rejects_zero_periods():
    with pytest.raises(SystemExit):
        _load().main(["--periods", "0"])
