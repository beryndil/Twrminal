"""Server-side user preferences (migration 0026).

The `preferences` table is a typed single-row store (id=1, enforced by
a CHECK constraint). The seed row lands at migration time so the API
handlers never have to consider the row-doesn't-exist case — every
read returns a row, every write upserts in place.

Two helpers:

* `get_preferences` — return the singleton row as a dict.
* `update_preferences` — partial update. Only the fields the caller
  passes are written; everything else is left untouched. `updated_at`
  is bumped on every successful write so the frontend's one-shot
  localStorage migrator can detect the seed-state baseline (where
  `updated_at` matches the seed timestamp from migration time).

Everything is best-effort from the API's perspective — wrap calls in
the route's normal HTTPException pattern. A missed write surfaces as
a 500; a stale read returns the prior value, which the frontend
rehydrates on next focus.
"""

from __future__ import annotations

from typing import Any

import aiosqlite

from bearings.db._common import _now

_PREFS_COLS = (
    "id, display_name, theme, default_model, default_working_dir, notify_on_complete, updated_at"
)


async def get_preferences(conn: aiosqlite.Connection) -> dict[str, Any]:
    """Return the singleton preferences row.

    The seed row is created at migration time, so the only way this
    can return None is a manually-wiped DB. We treat that as a
    programming error and let the assertion fire — callers who hit it
    have a corrupted install, not a shape they need to handle.
    """
    async with conn.execute(f"SELECT {_PREFS_COLS} FROM preferences WHERE id = 1") as cursor:
        row = await cursor.fetchone()
    assert row is not None, "preferences seed row is missing — DB corrupted"
    return _row_to_dict(row)


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    """Decode a `preferences` row into the caller-facing dict shape.

    SQLite stores `notify_on_complete` as INTEGER 0/1 (the convention
    Bearings uses everywhere); the frontend wants a plain bool, so we
    coerce here rather than make every consumer remember.
    """
    data = dict(row)
    data["notify_on_complete"] = bool(data["notify_on_complete"])
    return data


async def update_preferences(conn: aiosqlite.Connection, **fields: Any) -> dict[str, Any]:
    """Apply a partial update to the singleton row.

    Pass only the fields the caller supplied (the route layer derives
    this from `body.model_fields_set` so unset fields stay untouched
    and explicit `None` clears nullable columns). `updated_at` is
    always bumped — even on a no-op call — so the frontend's seed-
    timestamp detector flips off the moment any write lands.

    Unknown keys are rejected via an explicit allowlist; the route
    validator catches this first, but the store layer enforces it too
    so a misuse from internal callers can't write into arbitrary
    columns.
    """
    allowed = {
        "display_name",
        "theme",
        "default_model",
        "default_working_dir",
        "notify_on_complete",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"unknown preferences fields: {sorted(unknown)}")

    # Coerce bool → int for the SQLite boolean convention. The column
    # is `INTEGER NOT NULL DEFAULT 0`, so `None` here would violate the
    # NOT NULL constraint; the route validator rejects None for this
    # field upstream, but we belt-and-braces to a 0 if it ever slips
    # through (better than a 500).
    if "notify_on_complete" in fields:
        fields["notify_on_complete"] = int(bool(fields["notify_on_complete"]))

    # Build `SET col = ?, ... , updated_at = ?`. An empty `fields` dict
    # is legal — it lands as a pure timestamp bump, which is what an
    # empty PATCH payload should do.
    assignments_parts = [f"{k} = ?" for k in fields]
    assignments_parts.append("updated_at = ?")
    params: list[Any] = [fields[k] for k in fields]
    params.append(_now())
    await conn.execute(
        f"UPDATE preferences SET {', '.join(assignments_parts)} WHERE id = 1",
        params,
    )
    await conn.commit()
    return await get_preferences(conn)
