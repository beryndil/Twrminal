"""Checklists + checklist_items. A checklist is a 1:1 companion to
`sessions` rows whose `kind = 'checklist'` — the session row carries
the title, tags, and lifecycle flags; the checklist row carries the
structured body (notes + items). The runner never attaches to a
checklist session; these helpers are the entire mutation surface.

Public functions mirror the shape of `_tags.py`: each returns a
refreshed dict row or `None` when the target is missing. Timestamps
are ISO via `_common._now()` to match every other column. A
single-round-trip `get_checklist` includes the item list so the UI
can paint on one response rather than stitching two.
"""

from __future__ import annotations

from typing import Any

import aiosqlite

from bearings.db._common import _now

CHECKLIST_COLS = "session_id, notes, created_at, updated_at"
# `blocked_at` + reason fields land in migration 0033; included here so
# every read path surfaces the new tri-state. Existing rows read as
# (NULL, NULL, NULL) which serializes identically to pre-migration
# behavior. Driver-side stamping arrives in the auto_driver wiring
# commit; this commit is read-only on the new columns.
ITEM_COLS = (
    "id, checklist_id, parent_item_id, label, notes, checked_at, sort_order, "
    "created_at, updated_at, chat_session_id, "
    "blocked_at, blocked_reason_category, blocked_reason_text"
)
# Top-level items ordered by sort_order then id; nested children
# follow the same rule under their parent (resolved client-side for
# now — a single flat list is cheaper to ship than a recursive CTE
# and the nesting UI lands in a later slice anyway).
ITEM_ORDER = "sort_order ASC, id ASC"


async def create_checklist(
    conn: aiosqlite.Connection,
    session_id: str,
    *,
    notes: str | None = None,
) -> dict[str, Any]:
    """Insert the 1:1 checklist row for `session_id`. Caller is
    responsible for ensuring the session row exists and carries
    `kind = 'checklist'` — this helper doesn't validate the parent
    because the normal creation path is the `POST /sessions` handler
    doing both inserts inside one transaction."""
    now = _now()
    await conn.execute(
        "INSERT INTO checklists (session_id, notes, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, notes, now, now),
    )
    await conn.commit()
    row = await get_checklist(conn, session_id)
    assert row is not None  # just inserted
    return row


async def get_checklist(conn: aiosqlite.Connection, session_id: str) -> dict[str, Any] | None:
    """Return the checklist row for `session_id` with its items inline,
    or `None` when the row doesn't exist. Items come back flat in
    sort_order then id; nesting is recovered client-side via
    `parent_item_id`."""
    async with conn.execute(
        f"SELECT {CHECKLIST_COLS} FROM checklists WHERE session_id = ?",
        (session_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    out = dict(row)
    async with conn.execute(
        f"SELECT {ITEM_COLS} FROM checklist_items WHERE checklist_id = ? ORDER BY {ITEM_ORDER}",
        (session_id,),
    ) as cursor:
        out["items"] = [dict(r) async for r in cursor]
    return out


async def update_checklist(
    conn: aiosqlite.Connection,
    session_id: str,
    *,
    fields: dict[str, Any],
) -> dict[str, Any] | None:
    """Partial update. `fields` may carry `notes`; unknown keys are
    ignored so the HTTP layer can pass a permissive dict. Bumps
    `updated_at`. Returns the refreshed row (with items) or `None`
    when the checklist doesn't exist."""
    allowed = {"notes"}
    filtered = {k: v for k, v in fields.items() if k in allowed}
    if not filtered:
        return await get_checklist(conn, session_id)
    assignments = ", ".join(f"{col} = ?" for col in filtered)
    params = (*filtered.values(), _now(), session_id)
    cursor = await conn.execute(
        f"UPDATE checklists SET {assignments}, updated_at = ? WHERE session_id = ?",
        params,
    )
    await conn.commit()
    if cursor.rowcount == 0:
        return None
    return await get_checklist(conn, session_id)


async def get_item(conn: aiosqlite.Connection, item_id: int) -> dict[str, Any] | None:
    async with conn.execute(
        f"SELECT {ITEM_COLS} FROM checklist_items WHERE id = ?",
        (item_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def create_item(
    conn: aiosqlite.Connection,
    checklist_id: str,
    *,
    label: str,
    notes: str | None = None,
    parent_item_id: int | None = None,
    sort_order: int | None = None,
) -> dict[str, Any] | None:
    """Insert a new item. When `sort_order` is omitted, we append —
    `MAX(sort_order) + 1` among siblings so the new row lands at the
    bottom of its sibling list. Returns `None` if the parent
    checklist doesn't exist (FK would fail); otherwise the freshly
    inserted row."""
    parent_check = await conn.execute(
        "SELECT 1 FROM checklists WHERE session_id = ?", (checklist_id,)
    )
    if await parent_check.fetchone() is None:
        return None
    if sort_order is None:
        async with conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM checklist_items "
            "WHERE checklist_id = ? AND "
            "(parent_item_id IS ? OR parent_item_id = ?)",
            (checklist_id, parent_item_id, parent_item_id),
        ) as cursor:
            max_row = await cursor.fetchone()
            sort_order = int(max_row[0]) if max_row is not None else 0
    now = _now()
    cursor = await conn.execute(
        "INSERT INTO checklist_items "
        "(checklist_id, parent_item_id, label, notes, sort_order, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (checklist_id, parent_item_id, label, notes, sort_order, now, now),
    )
    # Touch the parent checklist so `updated_at` reflects the latest
    # mutation — mirrors how `insert_message` bumps the session row.
    await conn.execute(
        "UPDATE checklists SET updated_at = ? WHERE session_id = ?",
        (now, checklist_id),
    )
    await conn.commit()
    item_id = cursor.lastrowid
    assert item_id is not None
    inserted = await get_item(conn, item_id)
    assert inserted is not None
    return inserted


async def update_item(
    conn: aiosqlite.Connection,
    item_id: int,
    *,
    fields: dict[str, Any],
) -> dict[str, Any] | None:
    """Partial update. Accepts `label`, `notes`, `parent_item_id`,
    `sort_order`. Bumps `updated_at` on both the item and its parent
    checklist. Returns `None` if the item id is unknown."""
    allowed = {"label", "notes", "parent_item_id", "sort_order"}
    filtered = {k: v for k, v in fields.items() if k in allowed}
    if not filtered:
        return await get_item(conn, item_id)
    assignments = ", ".join(f"{col} = ?" for col in filtered)
    now = _now()
    params = (*filtered.values(), now, item_id)
    cursor = await conn.execute(
        f"UPDATE checklist_items SET {assignments}, updated_at = ? WHERE id = ?",
        params,
    )
    if cursor.rowcount == 0:
        await conn.commit()
        return None
    # Bump the parent checklist too — cheap JOIN to recover the id.
    await conn.execute(
        "UPDATE checklists SET updated_at = ? WHERE session_id = "
        "(SELECT checklist_id FROM checklist_items WHERE id = ?)",
        (now, item_id),
    )
    await conn.commit()
    return await get_item(conn, item_id)


async def toggle_item(
    conn: aiosqlite.Connection, item_id: int, *, checked: bool
) -> dict[str, Any] | None:
    """Set or clear `checked_at` with cascade-up on ancestor items.
    Passing `checked=True` stamps the current time on the leaf and,
    for every ancestor whose direct children are now all checked,
    also stamps the ancestor's `checked_at`. Passing `checked=False`
    clears the leaf and clears any auto-checked ancestor whose
    children no longer all carry `checked_at`. Returns the refreshed
    leaf row or `None` when the id is unknown.

    Cascade invariant: `parent.checked_at IS NOT NULL` iff every
    direct child has `checked_at IS NOT NULL`. The UI disables the
    parent's checkbox so parents are always derived — no manual
    override. Cascade runs inside the same transaction as the leaf
    write, so a concurrent reader never observes a partially-updated
    ancestor chain.

    Session-close cascade (added 2026-04-25). When `checked=True`,
    every item whose `checked_at` flips from NULL to a timestamp in
    this call — leaf + any newly-checked ancestor — has its paired
    chat sessions closed. The checklist itself stays open as the
    navigation index back into the closed chats; only the per-item
    legs are auto-closed. Lives here (vs the manual UI handler) so
    every caller of `toggle_item` (autonomous driver, manual UI
    toggle, future API paths) gets the cascade for free.

    Re-entry: closing a paired session calls back into `toggle_item`
    via the `_sessions.close_session` cascade. The skip-closed filter
    on `list_item_sessions` ensures each leg is closed exactly once
    even under recursive entry — close_session is idempotent on the
    closed_at column anyway, but the filter avoids unnecessary
    recursion through the cascade-up walk."""
    now = _now()
    checked_at = now if checked else None
    # Mutual-exclusion enforcement (migration 0033): when an item is
    # being checked off, ALSO clear `blocked_at` and the reason fields
    # in the same write. The resolution flow goes blocked → done in
    # one step (Dave returns to the still-open session, agent
    # re-engages and emits CHECKLIST_ITEM_DONE), so done must clear
    # the blocked stamp the same transaction it sets checked_at.
    # When unchecking we DON'T re-stamp blocked — uncheck is a
    # rollback to "open," not a transition to "blocked."
    if checked:
        cursor = await conn.execute(
            "UPDATE checklist_items "
            "SET checked_at = ?, blocked_at = NULL, "
            "    blocked_reason_category = NULL, blocked_reason_text = NULL, "
            "    updated_at = ? "
            "WHERE id = ?",
            (checked_at, now, item_id),
        )
    else:
        cursor = await conn.execute(
            "UPDATE checklist_items SET checked_at = ?, updated_at = ? WHERE id = ?",
            (checked_at, now, item_id),
        )
    if cursor.rowcount == 0:
        await conn.commit()
        return None
    leaf = await get_item(conn, item_id)
    if leaf is None:
        await conn.commit()
        return None
    checklist_id = leaf["checklist_id"]
    # Track every item that became newly-checked in this call so the
    # close cascade below knows which paired sessions to sweep. The
    # leaf is in the set whenever `checked=True`; ancestors are added
    # as the walk discovers them. Using a list to preserve leaf-first
    # order so the close cascade processes the deepest item first
    # (matches user intuition — the actual-work session closes before
    # any rollup-only ancestor session).
    newly_checked_ids: list[int] = [int(item_id)] if checked else []
    parent_id: int | None = leaf["parent_item_id"]
    while parent_id is not None:
        # Cascade-check applies ONLY to rollup-only parents (no paired
        # chat of their own). A parent with `chat_session_id` set has
        # its own work — its children are preconditions (CHECKLIST_BLOCKED
        # fix-it items the driver created) rather than the totality of
        # the parent's task. Auto-checking the parent there would close
        # its work session prematurely and break the fix-and-return
        # contract: the parent must be free to resume after the blocker
        # is fixed and explicitly emit CHECKLIST_ITEM_DONE. Walk stops
        # at a work-having parent — its grandparent doesn't get cascade-
        # checked either, since the work-having parent isn't done.
        async with conn.execute(
            "SELECT chat_session_id, checked_at FROM checklist_items WHERE id = ?",
            (parent_id,),
        ) as cursor_chat:
            parent_row = await cursor_chat.fetchone()
        if parent_row is None:
            break
        if parent_row["chat_session_id"] is not None:
            break
        async with conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN checked_at IS NULL THEN 1 ELSE 0 END) AS unchecked, "
            "SUM(CASE WHEN blocked_at IS NOT NULL THEN 1 ELSE 0 END) AS blocked "
            "FROM checklist_items WHERE parent_item_id = ?",
            (parent_id,),
        ) as cursor_stats:
            stats = await cursor_stats.fetchone()
        # A parent with zero children is theoretically possible if a
        # race deleted every child between the leaf write and the
        # walk — treat as "not checked" (no children → no derivation).
        # A blocked child also keeps the parent unchecked: a blocked
        # leaf has `checked_at IS NULL` so `unchecked > 0` already
        # gates correctly, but tracking blocked separately means the
        # condition is explicit and any future refactor (e.g. an
        # `unchecked_only_open` filter that excludes blocked) doesn't
        # silently lose the carve-out.
        total = stats["total"] if stats is not None else 0
        unchecked = (stats["unchecked"] or 0) if stats is not None else 1
        blocked = (stats["blocked"] or 0) if stats is not None else 0
        ancestor_checked_at = (
            now if total > 0 and unchecked == 0 and blocked == 0 else None
        )
        # Track the ancestor for the close cascade ONLY when this
        # call is what flipped it to checked. An ancestor that was
        # already checked before this call (UI bug, race, idempotent
        # re-toggle) doesn't get its sessions re-closed.
        if ancestor_checked_at is not None and parent_row["checked_at"] is None:
            newly_checked_ids.append(int(parent_id))
        await conn.execute(
            "UPDATE checklist_items SET checked_at = ?, updated_at = ? WHERE id = ?",
            (ancestor_checked_at, now, parent_id),
        )
        async with conn.execute(
            "SELECT parent_item_id FROM checklist_items WHERE id = ?",
            (parent_id,),
        ) as cursor_up:
            next_row = await cursor_up.fetchone()
        parent_id = next_row["parent_item_id"] if next_row is not None else None
    await conn.execute(
        "UPDATE checklists SET updated_at = ? WHERE session_id = ?",
        (now, checklist_id),
    )
    await conn.commit()
    # Auto-close paired sessions for every newly-checked item. Local
    # import to avoid a static cycle with `_sessions` (which already
    # imports from this module on its own close cascade). Each item's
    # `list_item_sessions` enumerates legs via the reverse pointer
    # `sessions.checklist_item_id`; we filter to open sessions to
    # bound the recursion when close_session re-enters this function.
    if newly_checked_ids:
        from bearings.db._sessions import close_session, get_session

        for nci in newly_checked_ids:
            legs = await list_item_sessions(conn, nci)
            for leg in legs:
                if leg.get("closed_at") is None:
                    await close_session(conn, leg["id"])
        # When the whole checklist becomes complete, close the parent
        # checklist session too. Manual toggles of an items-without-
        # legs list wouldn't otherwise close the parent — only the
        # `close_session` cascade fires that close, and that cascade
        # only runs when there's at least one paired chat to close.
        # Putting the auto-close here means every code path (manual
        # toggle, autonomous driver, future API) lands the same end-
        # state. Idempotent: closing an already-closed checklist is a
        # no-op write at the storage layer.
        if checked and await is_checklist_complete(conn, checklist_id):
            parent = await get_session(conn, checklist_id)
            if parent is not None and parent.get("closed_at") is None:
                await close_session(conn, checklist_id)
    return await get_item(conn, item_id)


async def set_item_blocked(
    conn: aiosqlite.Connection,
    item_id: int,
    *,
    category: str,
    reason: str,
) -> dict[str, Any] | None:
    """Stamp an item as blocked-on-Dave. Stores `blocked_at`,
    `blocked_reason_category`, and `blocked_reason_text` on the row;
    leaves `checked_at`, `chat_session_id`, and the paired session's
    `closed_at` alone. Returns the refreshed row, or None when the
    id is unknown.

    This is the autonomous-driver entry point for the
    `CHECKLIST_ITEM_BLOCKED` sentinel. Unlike `toggle_item(checked=True)`,
    it does NOT close the paired chat session — the whole point of
    blocked is that the session stays open for Dave to act on.

    Mutual-exclusion contract (`checked_at` IS NULL OR `blocked_at`
    IS NULL): caller is responsible for not invoking this on a row
    that already has `checked_at` set. The driver only stamps blocked
    on the way to advancing past an unchecked item, so the path
    naturally upholds it. The reverse direction (clearing
    `blocked_at` when an item gets checked) lives in `toggle_item`'s
    cascade — `toggle_item(checked=True)` sets `checked_at` and
    clears blocked fields in the same write.

    Cascade-up rollback: a previously rolled-up parent (every child
    was checked → parent.checked_at non-null) must lose that rollup
    when one of its children flips to blocked. Otherwise: A and B
    both done → parent rollup → A becomes blocked, parent stays
    checked despite an unfinished child. The walk here mirrors the
    one in `toggle_item`'s uncheck path: clear ancestors that no
    longer satisfy "every child checked AND zero blocked." Stops at
    a work-having parent (`chat_session_id` set) for the same
    reason `toggle_item` does — those parents own their own work
    and don't roll up.

    Caller is responsible for validating `category` against
    `bearings.agent.checklist_sentinels.ITEM_BLOCKED_CATEGORIES` —
    the SQLite CHECK constraint will refuse out-of-range values but
    raises a generic IntegrityError that the driver would have to
    translate; sentinel-layer validation is the cleaner gate."""
    now = _now()
    cursor = await conn.execute(
        "UPDATE checklist_items "
        "SET blocked_at = ?, blocked_reason_category = ?, blocked_reason_text = ?, "
        "    updated_at = ? "
        "WHERE id = ?",
        (now, category, reason, now, item_id),
    )
    if cursor.rowcount == 0:
        await conn.commit()
        return None
    row = await get_item(conn, item_id)
    if row is None:
        await conn.commit()
        return None
    # Cascade-up rollback. Walk ancestors and unset any rolled-up
    # checked_at that's now invalid because this child became blocked.
    parent_id: int | None = row["parent_item_id"]
    while parent_id is not None:
        async with conn.execute(
            "SELECT chat_session_id, checked_at FROM checklist_items WHERE id = ?",
            (parent_id,),
        ) as cursor_chat:
            parent_row = await cursor_chat.fetchone()
        if parent_row is None:
            break
        if parent_row["chat_session_id"] is not None:
            break
        if parent_row["checked_at"] is None:
            # Already not-checked — nothing to roll back, and any
            # further ancestors can't be checked either (cascade-up
            # invariant). Stop walking.
            break
        await conn.execute(
            "UPDATE checklist_items SET checked_at = NULL, updated_at = ? WHERE id = ?",
            (now, parent_id),
        )
        async with conn.execute(
            "SELECT parent_item_id FROM checklist_items WHERE id = ?",
            (parent_id,),
        ) as cursor_up:
            next_row = await cursor_up.fetchone()
        parent_id = next_row["parent_item_id"] if next_row is not None else None
    await conn.execute(
        "UPDATE checklists SET updated_at = ? WHERE session_id = ?",
        (now, row["checklist_id"]),
    )
    await conn.commit()
    return await get_item(conn, item_id)


async def is_checklist_complete(conn: aiosqlite.Connection, session_id: str) -> bool:
    """Return True when every root-level item in the given checklist
    has `checked_at` set AND no root-level item is blocked AND the
    checklist has at least one root item. An empty checklist is
    never "complete" — the auto-close rule would fire on a brand-new
    session otherwise. Used by the HTTP layer and the close-session
    cascade to decide whether to close the parent checklist session.

    Blocked items count as "not done" — a blocked leaf has
    `checked_at IS NULL` so `unchecked > 0` already gates correctly,
    but the explicit `blocked = 0` guard keeps the contract obvious
    and survives any future refactor that changes how unchecked is
    counted. A whole checklist with one blocked item must NOT
    auto-close the parent session — Dave needs the sidebar entry
    intact to navigate back to the still-open paired chat."""
    async with conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN checked_at IS NULL THEN 1 ELSE 0 END) AS unchecked, "
        "SUM(CASE WHEN blocked_at IS NOT NULL THEN 1 ELSE 0 END) AS blocked "
        "FROM checklist_items "
        "WHERE checklist_id = ? AND parent_item_id IS NULL",
        (session_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return False
    total = row["total"]
    unchecked = row["unchecked"] or 0
    blocked = row["blocked"] or 0
    return total > 0 and unchecked == 0 and blocked == 0


async def delete_item(conn: aiosqlite.Connection, item_id: int) -> bool:
    """Delete an item. Cascade-on-delete sweeps any nested children
    the same way. Returns True if a row was removed."""
    # Capture the parent checklist id so we can bump its updated_at
    # after the delete commits.
    parent_row = await conn.execute(
        "SELECT checklist_id FROM checklist_items WHERE id = ?", (item_id,)
    )
    parent = await parent_row.fetchone()
    cursor = await conn.execute("DELETE FROM checklist_items WHERE id = ?", (item_id,))
    deleted = cursor.rowcount > 0
    if deleted and parent is not None:
        await conn.execute(
            "UPDATE checklists SET updated_at = ? WHERE session_id = ?",
            (_now(), parent["checklist_id"]),
        )
    await conn.commit()
    return deleted


async def set_item_chat_session(
    conn: aiosqlite.Connection,
    item_id: int,
    chat_session_id: str | None,
) -> dict[str, Any] | None:
    """Pair (or unpair) a checklist item with a chat session. Passing
    `None` clears the pairing — used when the user detaches or the
    chat session is deleted elsewhere (the SET NULL cascade on the FK
    handles deletions automatically, so this helper is strictly for
    *intentional* unpair; the cascade saves us from needing an
    on-session-delete callback). Bumps `updated_at` on both item and
    checklist. Returns the refreshed item row or `None` if the id is
    unknown.

    Added in migration 0017 (Slice 4 of nimble-checking-heron)."""
    now = _now()
    cursor = await conn.execute(
        "UPDATE checklist_items SET chat_session_id = ?, updated_at = ? WHERE id = ?",
        (chat_session_id, now, item_id),
    )
    if cursor.rowcount == 0:
        await conn.commit()
        return None
    await conn.execute(
        "UPDATE checklists SET updated_at = ? WHERE session_id = "
        "(SELECT checklist_id FROM checklist_items WHERE id = ?)",
        (now, item_id),
    )
    await conn.commit()
    return await get_item(conn, item_id)


async def get_item_by_chat_session(
    conn: aiosqlite.Connection,
    chat_session_id: str,
) -> dict[str, Any] | None:
    """Reverse lookup: given a chat session id, return the checklist
    item it's paired to (if any). Used by the prompt assembler to
    build the checklist-context layer from the inverse side — the
    session row already carries `checklist_item_id`, but fetching the
    item via this helper keeps the SELECT local to this module and
    picks up every ITEM_COLS field in one call.

    Added in migration 0017."""
    async with conn.execute(
        f"SELECT {ITEM_COLS} FROM checklist_items WHERE chat_session_id = ?",
        (chat_session_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def list_item_sessions(
    conn: aiosqlite.Connection,
    item_id: int,
) -> list[dict[str, Any]]:
    """Return every chat session that was ever paired to `item_id`,
    oldest first. Used by the autonomous driver to enumerate the
    "legs" of an item's work — when context fills up, the driver
    spawns a successor paired chat for the same item and the list
    here grows by one. Each row carries the session columns the
    caller is likely to render in a legs expander: `id`, `title`,
    `created_at`, `last_completed_at`, `closed_at`, and
    `total_cost_usd`. Returns an empty list when the item has never
    been paired.

    Uses the reverse pointer (`sessions.checklist_item_id`) rather
    than `checklist_items.chat_session_id`, because the forward
    pointer only remembers the most recent leg. See TODO.md
    "Autonomous checklist execution" for the legs-chain design.
    """
    async with conn.execute(
        "SELECT id, title, created_at, last_completed_at, closed_at, "
        "total_cost_usd FROM sessions WHERE checklist_item_id = ? "
        "ORDER BY created_at ASC, id ASC",
        (item_id,),
    ) as cursor:
        return [dict(row) async for row in cursor]


async def next_unchecked_top_level_item(
    conn: aiosqlite.Connection,
    checklist_id: str,
    *,
    exclude_ids: set[int] | None = None,
) -> dict[str, Any] | None:
    """Return the first top-level item in `checklist_id` that still
    carries `checked_at IS NULL`, ordered by `sort_order` then `id`.
    "Top-level" means `parent_item_id IS NULL` — nested children are
    handled by the driver's recursion layer, not this helper.
    Returns `None` when every top-level item is checked (which is
    also the condition `is_checklist_complete` reports `True`).

    `exclude_ids` lets the autonomous driver skip past items it has
    already tried and failed in a `failure_policy="skip"` run — those
    items stay unchecked (per the user's request) but must not be
    re-picked, or the loop would never advance. Defaults to None for
    callers that don't need exclusion (the common case).

    Used by the autonomous driver's outer loop to pick the next
    item to work on. Order-of-attack matches what the UI shows so
    an observer sees the driver stepping top-to-bottom."""
    excluded = exclude_ids or set()
    if not excluded:
        async with conn.execute(
            f"SELECT {ITEM_COLS} FROM checklist_items "
            "WHERE checklist_id = ? AND parent_item_id IS NULL "
            "AND checked_at IS NULL "
            f"ORDER BY {ITEM_ORDER} LIMIT 1",
            (checklist_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row is not None else None
    # NOT IN (...) requires a placeholder per id since SQLite doesn't
    # bind sequences. Build the placeholder list inline; the values
    # come from a Python set we control, so injection isn't a risk.
    placeholders = ", ".join("?" * len(excluded))
    async with conn.execute(
        f"SELECT {ITEM_COLS} FROM checklist_items "
        "WHERE checklist_id = ? AND parent_item_id IS NULL "
        "AND checked_at IS NULL "
        f"AND id NOT IN ({placeholders}) "
        f"ORDER BY {ITEM_ORDER} LIMIT 1",
        (checklist_id, *sorted(excluded)),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def list_unchecked_children(
    conn: aiosqlite.Connection,
    parent_item_id: int,
) -> list[dict[str, Any]]:
    """Return every direct child of `parent_item_id` whose
    `checked_at IS NULL`, ordered by `sort_order` then `id`. Used by
    the autonomous driver when the parent spawned a blocking
    followup: drive the children before re-entering the parent.
    Does not recurse — a grandchild with an unchecked parent is the
    concern of whoever drives the intermediate level."""
    async with conn.execute(
        f"SELECT {ITEM_COLS} FROM checklist_items "
        "WHERE parent_item_id = ? AND checked_at IS NULL "
        f"ORDER BY {ITEM_ORDER}",
        (parent_item_id,),
    ) as cursor:
        return [dict(row) async for row in cursor]


async def reorder_items(
    conn: aiosqlite.Connection,
    checklist_id: str,
    ordered_ids: list[int],
) -> int:
    """Bulk sort_order rewrite. Items not in `ordered_ids` keep their
    existing `sort_order`. Foreign items (ids belonging to another
    checklist) are silently skipped so a malicious client can't
    reorder a list it doesn't own. Returns the number of rows
    actually rewritten."""
    if not ordered_ids:
        return 0
    now = _now()
    written = 0
    for i, item_id in enumerate(ordered_ids):
        cursor = await conn.execute(
            "UPDATE checklist_items SET sort_order = ?, updated_at = ? "
            "WHERE id = ? AND checklist_id = ?",
            (i, now, item_id, checklist_id),
        )
        written += cursor.rowcount
    if written > 0:
        await conn.execute(
            "UPDATE checklists SET updated_at = ? WHERE session_id = ?",
            (now, checklist_id),
        )
    await conn.commit()
    return written
