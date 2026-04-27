"""Autonomous checklist driver — public API re-exports.

The original ``auto_driver.py`` was split into a package on 2026-04-27
to honor §FileSize (≤400 lines per file). External consumers continue
to import via ``bearings.agent.auto_driver``::

    from bearings.agent.auto_driver import Driver, DriverConfig, ...

Internal layout:

- ``contracts`` — :class:`DriverOutcome` / :class:`DriverResult` /
  :class:`DriverConfig` / :class:`DriverRuntime` and the internal
  ``_ItemOutcome`` enum.
- ``prompts`` — kickoff / continuation / nudge prompt builders (free
  functions; no driver state needed).
- ``persistence`` — ``_PersistenceMixin`` carrying ``_mark_done`` /
  ``_mark_blocked`` / ``_record_failure`` / ``_save_snapshot`` /
  ``_apply_restore`` and friends.
- ``sessions`` — ``_SessionsMixin`` for the visit-existing leg
  resolution and the silent-exit nudge.
- ``dispatch`` — ``_DispatchMixin`` carrying the per-item state
  machine and followup application.
- ``driver`` — the :class:`Driver` class itself, multi-inheriting the
  four mixins and owning ``__init__`` / ``stop`` / ``drive`` /
  ``_drive_loop`` / ``_result``.
"""

from __future__ import annotations

from bearings.agent.auto_driver.contracts import (
    DriverConfig,
    DriverOutcome,
    DriverResult,
    DriverRuntime,
)
from bearings.agent.auto_driver.driver import Driver

__all__ = [
    "Driver",
    "DriverConfig",
    "DriverOutcome",
    "DriverResult",
    "DriverRuntime",
]
