"""Autonomous-driver run-state persistence (migration 0031).

The `AutoDriverRegistry` was originally an in-memory dict — a systemd
restart or crash silently dropped every running driver. The table this
module owns survives that teardown so a fresh-boot lifespan can
rehydrate any non-terminal driver and re-spawn its asyncio.Task.

Contract:
- `upsert_running` writes a `state='running'` snapshot. Idempotent;
  the registry calls it on every counter mutation so a crash mid-run
  loses at most one item's worth of progress.
- `mark_finished` / `mark_errored` are the terminal-state writes. They
  preserve the existing snapshot's counters and only flip `state` (and
  optionally append failure detail) so the audit row reflects the last
  observed counters.
- `list_running` is the rehydrate scan source: every row with
  `state='running'` represents a driver that was alive at last write.
- `get` returns one row by checklist session id, used by tests and by
  the rehydrate path's per-row reconstruction.

These helpers are best-effort from the driver's perspective — wrap
calls in try/except and log on failure (see `Driver._save_snapshot`).
A missed write degrades to "older snapshot rehydrates"; never crash
the driver on a persistence error.
"""

from __future__ import annotations

from typing import Any

import aiosqlite

from bearings.db._common import _now

_AUTO_RUN_COLS = (
    "checklist_session_id, state, items_completed, items_failed, "
    "items_skipped, legs_spawned, failed_item_id, failure_reason, "
    "config_json, attempted_failed_json, created_at, updated_at"
)


async def upsert_auto_run_state(
    conn: aiosqlite.Connection,
    *,
    checklist_session_id: str,
    state: str,
    items_completed: int,
    items_failed: int,
    items_skipped: int,
    legs_spawned: int,
    failed_item_id: int | None,
    failure_reason: str | None,
    config_json: str,
    attempted_failed_json: str,
) -> None:
    """Insert or update the auto_run_state row for `checklist_session_id`.

    `state` must be one of 'running', 'finished', 'errored' (enforced by
    a CHECK constraint at the SQL layer). Counters and failure detail
    overwrite the prior row's values verbatim — the driver passes its
    full in-memory state on every write, so partial-update semantics
    aren't needed.

    `created_at` is set on first insert and preserved on update so the
    audit trail keeps the original start time. `updated_at` bumps on
    every write.
    """
    now = _now()
    await conn.execute(
        f"INSERT INTO auto_run_state ({_AUTO_RUN_COLS}) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(checklist_session_id) DO UPDATE SET "
        "state = excluded.state, "
        "items_completed = excluded.items_completed, "
        "items_failed = excluded.items_failed, "
        "items_skipped = excluded.items_skipped, "
        "legs_spawned = excluded.legs_spawned, "
        "failed_item_id = excluded.failed_item_id, "
        "failure_reason = excluded.failure_reason, "
        "config_json = excluded.config_json, "
        "attempted_failed_json = excluded.attempted_failed_json, "
        "updated_at = excluded.updated_at",
        (
            checklist_session_id,
            state,
            items_completed,
            items_failed,
            items_skipped,
            legs_spawned,
            failed_item_id,
            failure_reason,
            config_json,
            attempted_failed_json,
            now,
            now,
        ),
    )
    await conn.commit()


async def get_auto_run_state(
    conn: aiosqlite.Connection,
    checklist_session_id: str,
) -> dict[str, Any] | None:
    """Return the single auto_run_state row for `checklist_session_id`,
    or `None` if no run has ever been started for this checklist."""
    async with conn.execute(
        f"SELECT {_AUTO_RUN_COLS} FROM auto_run_state WHERE checklist_session_id = ?",
        (checklist_session_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def list_running_auto_runs(
    conn: aiosqlite.Connection,
) -> list[dict[str, Any]]:
    """Return every auto_run_state row whose `state='running'`. The
    lifespan rehydrate path scans these and re-creates a Driver task
    per row. Order is `updated_at ASC` so the oldest unfinished run
    rehydrates first — not strictly required (each row is independent)
    but it keeps log output deterministic across restarts."""
    async with conn.execute(
        f"SELECT {_AUTO_RUN_COLS} FROM auto_run_state "
        "WHERE state = 'running' ORDER BY updated_at ASC",
    ) as cursor:
        return [dict(r) async for r in cursor]


async def delete_auto_run_state(
    conn: aiosqlite.Connection,
    checklist_session_id: str,
) -> bool:
    """Remove the auto_run_state row. Used by tests; the production
    lifecycle keeps terminal rows on disk for audit. Returns True
    when a row was deleted."""
    cursor = await conn.execute(
        "DELETE FROM auto_run_state WHERE checklist_session_id = ?",
        (checklist_session_id,),
    )
    await conn.commit()
    return cursor.rowcount > 0
