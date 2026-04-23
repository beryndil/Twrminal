"""Bearings — localhost web UI for Claude Code agent sessions.

Exports ``__version__`` resolved at import time from the installed package
metadata (``pyproject.toml`` via hatch). Keeping it derived rather than
hardcoded means version bumps in ``pyproject.toml`` automatically flow
through to ``/api/health`` and ``bearings --version``; prior releases
silently reported ``0.6.0`` through the entire v0.7.x–v0.9.x line because
the literal here was forgotten on every bump, misleading diagnostics.

Falls back to ``"0+unknown"`` when the package isn't installed (e.g.
running directly from the source tree with ``PYTHONPATH`` pointing at
``src/`` and no editable install). The fallback is only visible in
contributor workflows; any real install path has the metadata present.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("bearings")
except PackageNotFoundError:  # pragma: no cover — only hit in raw-source runs
    __version__ = "0+unknown"

__all__ = ["__version__"]
