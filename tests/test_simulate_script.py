import importlib.util
from pathlib import Path
from types import ModuleType

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
