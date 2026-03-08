import tomllib
from pathlib import Path

import dmemfs


def test_dunder_version_matches_pyproject() -> None:
    root = Path(__file__).resolve().parents[2]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert dmemfs.__version__ == pyproject["project"]["version"]