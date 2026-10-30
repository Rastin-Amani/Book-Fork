"""Application release version.

This is the runtime source of truth. Keep it in step with ``pyproject.toml``,
``package.json`` and the newest entry in ``CHANGELOG.md``;
``tests/unit/test_version.py`` fails when they drift.
"""

from __future__ import annotations

__version__ = "0.5.1"
