"""State-persistence and failure-recording mixin for ``Driver``.

The methods in :class:`_PersistenceMixin` mutate driver bookkeeping
counters and call into ``bearings.db.store`` to land item-level state
changes. They were extracted from the original ``auto_driver.py``
(§FileSize) but the bodies are unchanged — ``Driver`` inherits this
mixin alongside ``_DispatchMixin`` / ``_SessionsMixin`` so call sites
keep using ``self._mark_done(...)`` / ``self._save_snapshot(...)``.

The class-level type annotations declare the attributes that the
concrete :class:`Driver` populates in ``__init__``. They satisfy
mypy strict's ``self.X`` access checks at this module's scope while
the actual values come from the subclass.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

import aiosqlite

from bearings.agent.auto_driver.contracts import DriverConfig
from bearings.db import store

log = logging.getLogger(__name__)


class _PersistenceMixin:
    """Driver methods for state persistence and failure recording."""

    # Type-only attribute declarations (populated by Driver.__init__).
    _conn: aiosqlite.Connection
    _checklist_id: str
    _config: DriverConfig
    _items_completed: int
    _items_failed: int
    _items_skipped: int
    _items_blocked: int
    _legs_spawned: int
    _failed_item_id: int | None
    _failure_reason: str | None
    _attempted_failed: set[int]
    _restore: dict[str, Any] | None

    async def _mark_done(self, item_id: int) -> None:
        """Mark the item checked. The session-close cascade lives in
        ``store.toggle_item`` (since 2026-04-25) so both the autonomous
        driver and the manual UI toggle land the same end-state:
        every paired leg auto-closes when an item becomes checked,
        and the parent checklist session auto-closes when the whole
        list completes. This method stays as a one-liner so the
        driver's call sites read intent (``_mark_done``) rather than
        the storage primitive."""
        await store.toggle_item(self._conn, item_id, checked=True)

    async def _mark_blocked(
        self,
        item_id: int,
        *,
        category: str,
        reason: str,
        tried: tuple[str, ...],
    ) -> None:
        """Stamp the item as blocked-on-Dave and increment the counter.

        Crucially does NOT close the paired chat session — the whole
        point of blocked is that the session stays open for Dave to
        act on. This is the key behavioral departure from
        ``_mark_done``, which closes the leg via ``toggle_item``'s
        cascade.

        The agent's ``tried`` log is folded into ``blocked_reason_text``
        so the UI can render it without a separate column. Rendering
        format mirrors what the agent emitted::

            <reason>

            TRIED:
            - <attempt 1>
            - <attempt 2>

        Joined this way so a future parser (or the human reading the
        tooltip) can reverse it back into structured fields. The
        category enum is the source of truth for "what kind of
        blocker"; the text body is the human-facing detail.
        """
        body = reason
        if tried:
            bullets = "\n".join(f"- {t}" for t in tried)
            body = f"{reason}\n\nTRIED:\n{bullets}"
        await store.set_item_blocked(
            self._conn,
            item_id,
            category=category,
            reason=body,
        )
        self._items_blocked += 1
        log.info(
            "autonomous driver blocked item %s (category=%s)",
            item_id,
            category,
        )

    async def _record_failure(self, item_id: int, reason: str) -> None:
        self._items_failed += 1
        # First failure wins — the driver halts on first failure by
        # design, so capturing subsequent ones would be dead code.
        if self._failed_item_id is None:
            self._failed_item_id = item_id
            self._failure_reason = reason
        log.warning("autonomous driver failure on item %s: %s", item_id, reason)
        # Persist the reason into the item's `notes` column so the
        # ChecklistView can render it beside the item without any new
        # UI wiring — existing notes rendering already surfaces
        # whatever's here. Prepend with a `[auto-run]` marker so a
        # re-run can find and replace the prior failure entry
        # without clobbering user-authored notes above it.
        await self._persist_failure_note(item_id, reason)

    async def _persist_failure_note(self, item_id: int, reason: str) -> None:
        """Write the failure reason into ``checklist_items.notes``.

        If the item already carries user-authored notes, the failure
        line is appended after a blank line so the agent's original
        instruction stays at the top. If a prior ``[auto-run]`` line
        exists (from an earlier run), it's stripped before the new
        one is added — we only keep the most recent failure to avoid
        notes growing unbounded across retries.

        Best-effort: persistence failures are logged and swallowed.
        The driver's in-memory ``failure_reason`` is the source of
        truth for the HTTP status endpoint; the note is a UI
        convenience."""
        try:
            item = await store.get_item(self._conn, item_id)
            if item is None:
                return
            existing = item.get("notes") or ""
            # Strip any prior auto-run line (from a previous halted
            # run on the same item).
            cleaned = "\n".join(
                line for line in existing.splitlines() if not line.startswith("[auto-run]")
            ).rstrip()
            note_line = f"[auto-run] {reason}"
            new_notes = f"{cleaned}\n\n{note_line}" if cleaned else note_line
            await store.update_item(self._conn, item_id, fields={"notes": new_notes})
        except Exception:
            log.exception(
                "autonomous driver: failed to persist failure note for item %s",
                item_id,
            )

    def _apply_restore(self) -> None:
        """Seed in-memory state from a persisted ``auto_run_state`` row.

        Called once from ``drive()`` before the main loop when the
        registry rebuilt the driver from a rehydrate scan. The DB-
        backed ``checked_at`` column is the source of truth for which
        items are done, so we DON'T re-mark anything; we just restore
        the bookkeeping the outer loop needs to behave the same way it
        would have if the original driver had kept running:
        counters (so the status endpoint shows the running totals),
        failure detail (so a halt-failure run that crashed mid-write
        doesn't lose its reason), and ``_attempted_failed`` (so
        skip-mode runs don't loop on items already failed in the
        prior life of this run).
        """
        snap = self._restore
        if snap is None:
            return
        self._items_completed = int(snap.get("items_completed") or 0)
        self._items_failed = int(snap.get("items_failed") or 0)
        self._items_skipped = int(snap.get("items_skipped") or 0)
        self._items_blocked = int(snap.get("items_blocked") or 0)
        self._legs_spawned = int(snap.get("legs_spawned") or 0)
        failed_id = snap.get("failed_item_id")
        self._failed_item_id = int(failed_id) if failed_id is not None else None
        self._failure_reason = snap.get("failure_reason")
        attempted_raw = snap.get("attempted_failed_json") or "[]"
        try:
            attempted = json.loads(attempted_raw)
            if isinstance(attempted, list):
                self._attempted_failed = {int(x) for x in attempted}
        except (ValueError, TypeError):
            log.warning(
                "autonomous driver: malformed attempted_failed_json on restore "
                "for checklist %s — discarding exclusion set",
                self._checklist_id,
            )
            self._attempted_failed = set()

    async def _save_snapshot(self, state: str) -> None:
        """Persist the current in-memory bookkeeping into
        ``auto_run_state``. Best-effort — exceptions are logged and
        swallowed so a write failure (locked DB, disk full, schema
        drift) never crashes the running driver. The in-memory state
        stays authoritative for the live status endpoint; this row
        exists strictly so a fresh-boot lifespan can rehydrate.

        See migration 0031 for the table contract; ``state`` must be
        one of 'running', 'finished', 'errored'.
        """
        try:
            await store.upsert_auto_run_state(
                self._conn,
                checklist_session_id=self._checklist_id,
                state=state,
                items_completed=self._items_completed,
                items_failed=self._items_failed,
                items_skipped=self._items_skipped,
                items_blocked=self._items_blocked,
                legs_spawned=self._legs_spawned,
                failed_item_id=self._failed_item_id,
                failure_reason=self._failure_reason,
                config_json=json.dumps(asdict(self._config)),
                attempted_failed_json=json.dumps(sorted(self._attempted_failed)),
            )
        except Exception:
            log.exception(
                "autonomous driver: failed to persist run-state snapshot "
                "for checklist %s (state=%s)",
                self._checklist_id,
                state,
            )
