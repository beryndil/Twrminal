"""The :class:`Driver` class — the autonomous checklist driver itself.

Owns ``__init__`` / ``stop`` / ``drive`` / ``_drive_loop`` /
``_result``. All per-item behavior lives in the mixin modules; this
class composes them and adds the outer loop.

Multi-inheritance order matters at runtime: ``_PersistenceMixin`` and
``_SessionsMixin`` come BEFORE ``_DispatchMixin`` so the type-only
abstract stubs in ``_DispatchMixin`` (declared there to keep mypy
strict happy when its methods call ``self._mark_done`` etc.) are
shadowed by the real implementations during MRO lookup.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiosqlite

from bearings.agent.auto_driver.contracts import (
    DriverConfig,
    DriverOutcome,
    DriverResult,
    DriverRuntime,
    _ItemOutcome,
)
from bearings.agent.auto_driver.dispatch import _DispatchMixin
from bearings.agent.auto_driver.persistence import _PersistenceMixin
from bearings.agent.auto_driver.sessions import _SessionsMixin
from bearings.db import store

log = logging.getLogger(__name__)


class Driver(_PersistenceMixin, _SessionsMixin, _DispatchMixin):
    """Autonomous checklist driver. One per ``drive()`` invocation.

    Construct with a live DB connection, a runtime implementation,
    and the checklist session id. Call ``drive()`` to run to a
    terminal state. Call ``stop()`` from another task (a stop button,
    a signal handler) to cut the loop short — the driver finishes
    any in-flight runtime call, tears down the leg, and returns
    ``HALTED_STOP``.
    """

    def __init__(
        self,
        *,
        conn: aiosqlite.Connection,
        runtime: DriverRuntime,
        checklist_session_id: str,
        config: DriverConfig | None = None,
        restore: dict[str, Any] | None = None,
    ) -> None:
        self._conn = conn
        self._runtime = runtime
        self._checklist_id = checklist_session_id
        self._config = config or DriverConfig()
        self._stop = asyncio.Event()
        self._items_completed = 0
        self._items_failed = 0
        self._items_skipped = 0
        self._items_blocked = 0
        self._legs_spawned = 0
        self._failed_item_id: int | None = None
        self._failure_reason: str | None = None
        # Set of item ids that the driver has already attempted and
        # failed under skip-failure mode. They stay unchecked in the
        # DB (per the "leave it open" request), but the outer loop
        # must not re-pick them, or the run would loop forever on
        # the same uncompleted item. Excluded from
        # `next_unchecked_top_level_item` lookups.
        self._attempted_failed: set[int] = set()
        # Rehydrate primer. When the registry rebuilds a driver from a
        # persisted `auto_run_state` row it passes the snapshot dict
        # here; `drive()` seeds counters + `_attempted_failed` from it
        # before entering the main loop. The DB-backed `checked_at`
        # column is the source of truth for which items finished —
        # we DON'T try to resume a leg mid-turn — so resume = restored
        # bookkeeping + outer loop picks up at the next unchecked item.
        self._restore: dict[str, Any] | None = restore

    # --- external control --------------------------------------------

    def stop(self) -> None:
        """Request the driver exit at the next iteration boundary.
        Idempotent — repeated calls are harmless."""
        self._stop.set()

    # --- main loop ---------------------------------------------------

    async def drive(self) -> DriverResult:
        """Run the autonomous loop to a terminal state and return.

        With ``failure_policy="halt"`` (default), the first item that
        fails to complete halts the run with ``HALTED_FAILURE``. With
        ``failure_policy="skip"``, the failure is recorded on the
        item but the outer loop advances — useful for tour-style
        runs where you want the driver to do everything it can and
        leave hard items for human review.

        Persistence: writes a ``state='running'`` row into
        ``auto_run_state`` on entry and re-snapshots after every
        per-item outcome so a lifespan teardown leaves the rehydrate
        path enough to rebuild. On terminal return the row is flipped
        to ``state='finished'``; on an unexpected exception it's
        flipped to ``state='errored'``. ``asyncio.CancelledError``
        does NOT flip the state — a cancel is almost always a
        shutdown, and we want the next boot to rehydrate. See
        migration 0031 for the table contract.
        """
        if self._restore is not None:
            self._apply_restore()
        await self._save_snapshot("running")
        try:
            result = await self._drive_loop()
        except asyncio.CancelledError:
            # Shutdown path. Leave the row at 'running' so the next
            # boot rehydrates this driver.
            raise
        except BaseException:
            await self._save_snapshot("errored")
            raise
        await self._save_snapshot("finished")
        return result

    async def _drive_loop(self) -> DriverResult:
        """Inner loop, separate from ``drive()`` so the outer wrapper
        can own the persistence finalize step without three return
        paths each duplicating the snapshot call."""
        items_seen = 0
        skip_failures = self._config.failure_policy == "skip"
        while True:
            if self._stop.is_set():
                return self._result(DriverOutcome.HALTED_STOP)
            if items_seen >= self._config.max_items_per_run:
                return self._result(DriverOutcome.HALTED_MAX_ITEMS)
            item = await store.next_unchecked_top_level_item(
                self._conn,
                self._checklist_id,
                exclude_ids=self._attempted_failed or None,
            )
            if item is None:
                # HALTED_EMPTY = the run started against a checklist
                # that had no unchecked items. After we've touched
                # ANYTHING (completed, skipped, or failed-and-recorded
                # in skip mode), the run made progress and the right
                # outcome is COMPLETED. Without this, a run that
                # records only failures would surprise the user with
                # "nothing was here" — wrong, plenty was there, the
                # agent just couldn't finish it.
                touched_any = (
                    self._items_completed > 0
                    or self._items_skipped > 0
                    or self._items_failed > 0
                    or self._items_blocked > 0
                )
                if not touched_any:
                    return self._result(DriverOutcome.HALTED_EMPTY)
                return self._result(DriverOutcome.COMPLETED)
            items_seen += 1
            outcome = await self._drive_item(item, depth=0)
            if outcome == _ItemOutcome.FAILED:
                if not skip_failures:
                    return self._result(DriverOutcome.HALTED_FAILURE)
                # Skip-mode failure: record the item id so the next
                # `next_unchecked_top_level_item` lookup excludes it
                # — without this guard the same uncompleted item gets
                # re-picked forever.
                self._attempted_failed.add(int(item["id"]))
            elif outcome == _ItemOutcome.SKIPPED:
                # Skip is unconditional advance (independent of
                # failure_policy) but the item still needs exclusion
                # to avoid re-pick.
                self._attempted_failed.add(int(item["id"]))
            elif outcome == _ItemOutcome.BLOCKED:
                # Blocked is unconditional advance, same as SKIPPED —
                # the item is set aside for Dave to act on, the run
                # keeps going. Exclude it from re-pick so the next
                # `next_unchecked_top_level_item` lookup doesn't loop
                # back here. The DB row carries `blocked_at` non-null
                # but `checked_at` IS NULL, so without the exclusion
                # the unchecked-only query would re-surface it.
                self._attempted_failed.add(int(item["id"]))
            # Snapshot once per outer iteration — captures every
            # counter mutation that just happened (item completion,
            # skip, failure record, attempted_failed add). Cheap on
            # SQLite WAL; keeps the rehydrate primer current to
            # within one item.
            await self._save_snapshot("running")

    # --- result assembly ---------------------------------------------

    def _result(self, outcome: DriverOutcome) -> DriverResult:
        return DriverResult(
            outcome=outcome,
            items_completed=self._items_completed,
            items_failed=self._items_failed,
            legs_spawned=self._legs_spawned,
            items_skipped=self._items_skipped,
            items_blocked=self._items_blocked,
            failed_item_id=self._failed_item_id,
            failure_reason=self._failure_reason,
        )
