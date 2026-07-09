"""Resolve ROBIN_HOME for standalone skill scripts.

Skill scripts may run outside the Robin process (e.g. system Python,
nix env, CI) where ``robin_constants`` is not importable.  This module
provides the same ``get_robin_home()`` and ``display_robin_home()``
contracts as ``robin_constants`` without requiring it on ``sys.path``.

When ``robin_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``robin_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating the ``ROBIN_HOME = Path(os.getenv(...))`` pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from robin_constants import display_robin_home as display_robin_home
    from robin_constants import get_robin_home as get_robin_home
except (ModuleNotFoundError, ImportError):

    def get_robin_home() -> Path:
        """Return the Robin home directory (default: ~/.robin).

        Mirrors ``robin_constants.get_robin_home()``."""
        val = os.environ.get("ROBIN_HOME", "").strip()
        return Path(val) if val else Path.home() / ".robin"

    def display_robin_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``robin_constants.display_robin_home()``."""
        home = get_robin_home()
        try:
            return "~/" + str(home.relative_to(Path.home()))
        except ValueError:
            return str(home)
