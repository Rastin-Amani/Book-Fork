"""Release version declarations stay in step with each other."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from app.version import __version__

ROOT = Path(__file__).resolve().parents[2]


def test_version_declarations_agree() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert pyproject["project"]["version"] == __version__
    assert package["version"] == __version__
    assert re.search(rf"^## \[{re.escape(__version__)}\]", changelog, re.MULTILINE)
