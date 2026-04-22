"""Session table operations: CRUD, import, cost accumulation, and the
aggregate `list_all_sessions` used by the history export route. Owns
the `_SESSION_*` column constants that other modules may reference."""

from __future__ import annotations

from typing import Any

import aiosqlite

from bearings.db._common import _date_filter, _new_id, _now

SESSION_BASE_COLS = (
    "id, created_at, updated_at, working_dir, model, title, description, "
    "max_budget_usd, total_cost_usd, session_instructions, sdk_session_id, "
    "permission_mode, last_context_pct, last_context_tokens, last_context_max, "
    "closed_at, kind, checklist_item_id, last_completed_at, last_viewed_at, "
    "pinned"
)

# Valid values for sessions.kind. The column carries a CHECK constraint
# that enforces the same set at the SQLite layer; this module-level
# constant is the Python-side guard so `create_session` fails fast with
# a readable error instead of a bare IntegrityError.
_VALID_SESSION_KINDS = frozenset({"chat", "checklist"})

# claude-agent-sdk PermissionMode values. Kept as a module-level
# constant so `set_session_permission_mode` can reject typos before
# they hit the column — SQLite won't enforce the enum itself.
_VALID_PERMISSION_MODES = frozenset({"default", "plan", "acceptEdits", "bypassPermissions"})
SESSION_COUNT = "(SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count"
# Comma-separated tag ids attached to the session. Materialized as a
# string here because SQLite has no native array type; the Python layer
# splits it back into `list[int]` before handing the row to Pydantic.
# NULL when the session has zero tags — which should never happen after
# migration 0021 (ensure_default_severity lands Low on every session),
# but the split helper tolerates NULL / empty so older snapshots keep
# round-tripping. Drives the sidebar medallion row without an N+1 fetch.
SESSION_TAG_IDS = (
    "(SELECT GROUP_CONCAT(tag_id) FROM session_tags st WHERE st.session_id = s.id) AS tag_ids_csv"
)
SESSION_COLS_WITH_COUNT = (
    f"s.{SESSION_BASE_COLS.replace(', ', ', s.')}, {SESSION_COUNT}, {SESSION_TAG_IDS}"
)


def _parse_tag_ids_csv(row: dict[str, Any]) -> dict[str, Any]:
    """Mutate `row` to replace the raw `tag_ids_csv` string with a
    `tag_ids: list[int]` field. Safe on rows that don't carry the
    column (returns the row untouched) and on NULL / empty payloads
    (yields an empty list)."""
    csv = row.pop("tag_ids_csv", None)
    if csv is None or csv == "":
        row["tag_ids"] = []
    else:
        row["tag_ids"] = [int(x) for x in csv.split(",") if x]
    return row


async def create_session(
    conn: aiosqlite.Connection,
    *,
    working_dir: str,
    model: str,
    title: str | None = None,
    description: str | None = None,
    max_budget_usd: float | None = None,
    kind: str = "chat",
    checklist_item_id: int | None = None,
) -> dict[str, Any]:
    """Insert a new session row. `kind` defaults to `'chat'` so existing
    callers don't need to change; passing `'checklist'` is what the
    new checklist creation path sends. The companion `checklists` row
    is the caller's responsibility — this helper owns the `sessions`
    insert only, and rejects unknown kinds up front so bad input
    surfaces as a ValueError rather than a SQLite IntegrityError.

    `checklist_item_id` (migration 0017) pairs this chat session to a
    specific checklist item. The prompt assembler reads the pairing on
    every turn build so the agent sees the parent checklist / sibling
    items. Only meaningful when `kind='chat'` — it's a ValueError to
    pair a checklist-kind session to a checklist item."""
    if kind not in _VALID_SESSION_KINDS:
        raise ValueError(f"unknown session kind: {kind!r}")
    if checklist_item_id is not None and kind != "chat":
        raise ValueError(
            f"checklist_item_id only valid on kind='chat' sessions (got kind={kind!r})"
        )
    session_id = _new_id()
    now = _now()
    await conn.execute(
        "INSERT INTO sessions "
        "(id, created_at, updated_at, working_dir, model, title, description, "
        "max_budget_usd, kind, checklist_item_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            now,
            now,
            working_dir,
            model,
            title,
            description,
            max_budget_usd,
            kind,
            checklist_item_id,
        ),
    )
    await conn.commit()
    row = await get_session(conn, session_id)
    assert row is not None  # just inserted
    return row


async def list_sessions(
    conn: aiosqlite.Connection,
    *,
    tag_ids: list[int] | None = None,
    mode: str = "any",
    severity_tag_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """List sessions, newest-first. Two independent tag-filter axes,
    combined with AND (migration 0021 — severity group):

    - `tag_ids` / `mode`: the general-group filter. `mode='any'` =
      sessions carrying any listed tag; `mode='all'` = sessions
      carrying every listed tag. Empty / None = no general filter.
    - `severity_tag_ids`: the severity-group filter. Always OR
      within-group (a session can only carry one severity, so `all`
      is meaningless and the route hides the toggle). Empty / None =
      no severity filter.

    Both axes drop onto the same base query as EXISTS / IN
    subqueries, so composing them is just two `AND` clauses — no
    JOIN + GROUP BY gymnastics like the pre-0021 single-axis shape.
    Ordering stays `updated_at DESC, id DESC`.
    """
    where_clauses: list[str] = []
    params: list[Any] = []

    if tag_ids:
        tag_ph = ",".join("?" for _ in tag_ids)
        if mode == "all":
            # Every listed tag must be present on the session. Counting
            # DISTINCT tag_id in the subquery and requiring it to equal
            # the request's length is the idiomatic all-of check.
            where_clauses.append(
                f"s.id IN (SELECT session_id FROM session_tags "
                f"WHERE tag_id IN ({tag_ph}) "
                f"GROUP BY session_id HAVING COUNT(DISTINCT tag_id) = ?)"
            )
            params.extend(tag_ids)
            params.append(len(tag_ids))
        else:
            # mode == "any" — simple IN-subquery.
            where_clauses.append(
                f"s.id IN (SELECT session_id FROM session_tags WHERE tag_id IN ({tag_ph}))"
            )
            params.extend(tag_ids)

    if severity_tag_ids:
        # Sentinel `-1` represents "no severity attached" — surfaced in
        # the sidebar so the user can find sessions orphaned by a
        # deleted severity tag. Real tag ids are always positive, so
        # -1 is safe. Split real ids from the sentinel and combine
        # both via OR (a session matches if it carries any listed
        # severity OR has no severity at all).
        real_ids = [tid for tid in severity_tag_ids if tid > 0]
        want_none = any(tid == -1 for tid in severity_tag_ids)
        sev_or: list[str] = []
        if real_ids:
            sev_ph = ",".join("?" for _ in real_ids)
            sev_or.append(
                f"s.id IN (SELECT session_id FROM session_tags WHERE tag_id IN ({sev_ph}))"
            )
            params.extend(real_ids)
        if want_none:
            # NOT EXISTS any severity-group tag on this session. Joins
            # on tag_group = 'severity' to exclude sessions that
            # happen to carry general tags but no severity.
            sev_or.append(
                "NOT EXISTS (SELECT 1 FROM session_tags st "
                "JOIN tags t ON t.id = st.tag_id "
                "WHERE st.session_id = s.id AND t.tag_group = 'severity')"
            )
        # OR-within-group only: a session has exactly one severity, so
        # "sessions with any listed severity" is the only meaningful
        # combination rule here. Appended as a second AND clause so
        # the two axes narrow the result together.
        if sev_or:
            where_clauses.append("(" + " OR ".join(sev_or) + ")")

    where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = (
        f"SELECT {SESSION_COLS_WITH_COUNT} FROM sessions s"
        f"{where}"
        " ORDER BY s.updated_at DESC, s.id DESC"
    )
    async with conn.execute(sql, params) as cursor:
        return [_parse_tag_ids_csv(dict(row)) async for row in cursor]


async def get_session(conn: aiosqlite.Connection, session_id: str) -> dict[str, Any] | None:
    async with conn.execute(
        f"SELECT {SESSION_COLS_WITH_COUNT} FROM sessions s WHERE s.id = ?",
        (session_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return _parse_tag_ids_csv(dict(row)) if row is not None else None


async def update_session(
    conn: aiosqlite.Connection,
    session_id: str,
    *,
    fields: dict[str, Any],
) -> dict[str, Any] | None:
    """Apply a partial update. `fields` maps column name → new value;
    only `title`, `description`, `max_budget_usd`,
    `session_instructions`, `model`, and `pinned` are accepted. Bumps
    updated_at. Returns the refreshed row, or None if the session
    doesn't exist.

    `model` (Phase 4a.1 of the context-menu plan) lets "Change model
    for continuation" mutate the session in place per plan decision
    §2.1 — no fork, the runner drop in the route handler forces the
    next turn to spawn a fresh SDK subprocess on the new model.

    `pinned` is stored as 0/1 in SQLite; pass Python `True`/`False` and
    aiosqlite coerces. Pinning is a pure UX affordance — the sidebar
    floats pinned rows above recency within their tag group."""
    allowed = {
        "title",
        "description",
        "max_budget_usd",
        "session_instructions",
        "model",
        "pinned",
    }
    filtered = {k: v for k, v in fields.items() if k in allowed}
    if not filtered:
        return await get_session(conn, session_id)
    # Coerce bool → 0/1 for the SQLite INTEGER column, matching the
    # pattern already used by `_tags.update_tag`. Tolerates Python
    # True/False from Pydantic and the occasional int passed from
    # internal callers.
    if "pinned" in filtered:
        filtered["pinned"] = 1 if filtered["pinned"] else 0
    assignments = ", ".join(f"{col} = ?" for col in filtered)
    params = (*filtered.values(), _now(), session_id)
    cursor = await conn.execute(
        f"UPDATE sessions SET {assignments}, updated_at = ? WHERE id = ?",
        params,
    )
    await conn.commit()
    if cursor.rowcount == 0:
        return None
    return await get_session(conn, session_id)


async def delete_session(conn: aiosqlite.Connection, session_id: str) -> bool:
    cursor = await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    await conn.commit()
    return cursor.rowcount > 0


async def import_session(conn: aiosqlite.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    """Restore a session from the v0.1.30 export shape
    ({session, messages, tool_calls}). Generates fresh ids for the
    session, every message, and every tool call — preserves content,
    role, thinking, timestamps, and the message↔tool-call relationship
    through an id-remap table. Returns the new session row.

    Does not copy `total_cost_usd` forward — the new session starts at
    zero (restores don't count as spend). `updated_at` is stamped to
    the import time so the imported session lands at the top of the
    sidebar sort."""
    src_session = payload.get("session") or {}
    src_messages = payload.get("messages") or []
    src_tool_calls = payload.get("tool_calls") or []

    new_session_id = _new_id()
    now = _now()
    created_at = str(src_session.get("created_at") or now)
    # `closed_at` round-trips so an export of a closed session restores
    # closed; `None` on payloads predating the column is the open default.
    # `kind` defaults to 'chat' for payloads predating migration 0016;
    # a bogus value falls back to 'chat' rather than failing the whole
    # import (imports predate the feature for the vast majority of
    # backups). Checklist bodies aren't in the v0.1.30 export shape yet
    # — when they land, the importer will need a companion `checklists`
    # insert here.
    raw_kind = str(src_session.get("kind") or "chat")
    kind = raw_kind if raw_kind in _VALID_SESSION_KINDS else "chat"
    await conn.execute(
        "INSERT INTO sessions "
        "(id, created_at, updated_at, working_dir, model, title, description, "
        "max_budget_usd, closed_at, kind) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            new_session_id,
            created_at,
            now,
            str(src_session.get("working_dir") or "/tmp"),
            str(src_session.get("model") or "claude-opus-4-7"),
            src_session.get("title"),
            src_session.get("description"),
            src_session.get("max_budget_usd"),
            src_session.get("closed_at"),
            kind,
        ),
    )

    msg_id_map: dict[str, str] = {}
    for m in src_messages:
        old_id = str(m.get("id") or "")
        new_id = _new_id()
        if old_id:
            msg_id_map[old_id] = new_id
        await conn.execute(
            "INSERT INTO messages (id, session_id, role, content, thinking, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                new_id,
                new_session_id,
                str(m.get("role") or "user"),
                str(m.get("content") or ""),
                m.get("thinking"),
                str(m.get("created_at") or _now()),
            ),
        )

    for tc in src_tool_calls:
        old_msg_id = tc.get("message_id")
        new_msg_id = msg_id_map.get(str(old_msg_id)) if old_msg_id else None
        await conn.execute(
            "INSERT INTO tool_calls "
            "(id, session_id, message_id, name, input, output, error, "
            "started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _new_id(),
                new_session_id,
                new_msg_id,
                str(tc.get("name") or ""),
                str(tc.get("input") or "{}"),
                tc.get("output"),
                tc.get("error"),
                str(tc.get("started_at") or _now()),
                tc.get("finished_at"),
            ),
        )

    await conn.commit()
    row = await get_session(conn, new_session_id)
    assert row is not None
    return row


async def set_sdk_session_id(
    conn: aiosqlite.Connection,
    session_id: str,
    sdk_session_id: str,
) -> None:
    """Cache the claude-agent-sdk session id on the Bearings session so
    later turns can `resume=` it and inherit the SDK's conversation
    history. No-op if the row is gone."""
    await conn.execute(
        "UPDATE sessions SET sdk_session_id = ? WHERE id = ?",
        (sdk_session_id, session_id),
    )
    await conn.commit()


async def set_session_permission_mode(
    conn: aiosqlite.Connection,
    session_id: str,
    mode: str | None,
) -> None:
    """Persist the session's PermissionMode so a reconnect or browser
    reload restores the user's choice instead of silently dropping to
    'default'. `None` clears the column (== 'default' semantics). The
    runner calls this on every `set_permission_mode` wire frame; it's
    write-only — read via `get_session`. Raises ValueError on an
    unknown mode to keep bad values out of the column (SQLite won't
    enforce the enum itself)."""
    if mode is not None and mode not in _VALID_PERMISSION_MODES:
        raise ValueError(f"unknown permission mode: {mode!r}")
    await conn.execute(
        "UPDATE sessions SET permission_mode = ? WHERE id = ?",
        (mode, session_id),
    )
    await conn.commit()


async def set_session_context_usage(
    conn: aiosqlite.Connection,
    session_id: str,
    *,
    pct: float,
    tokens: int,
    max_tokens: int,
) -> None:
    """Cache the latest ContextUsage snapshot on the session row (see
    migration 0013). Called by the runner on every `ContextUsage` WS
    event so a fresh page load has a number to show before the next
    turn's live event arrives. Clamps the percentage to `[0, 100]` to
    keep downstream UI math simple; token counts are stored verbatim.
    No-op if the row is gone (UPDATE matches zero rows)."""
    safe_pct = max(0.0, min(100.0, float(pct)))
    await conn.execute(
        "UPDATE sessions SET last_context_pct = ?, last_context_tokens = ?, "
        "last_context_max = ? WHERE id = ?",
        (safe_pct, int(tokens), int(max_tokens), session_id),
    )
    await conn.commit()


async def close_session(
    conn: aiosqlite.Connection,
    session_id: str,
) -> dict[str, Any] | None:
    """Stamp `closed_at = now()` on the session. Idempotent: calling on
    an already-closed session refreshes the timestamp (cheap, no-op from
    the UI's view). Bumps `updated_at` so a re-sort after reopen pulls
    the session back to the top. Returns the refreshed row or `None` if
    the id is unknown.

    Slice 4.1 cascade: when the session being closed is a paired chat
    (`checklist_item_id IS NOT NULL`), also mark the linked checklist
    item checked and cascade-up through `toggle_item`; then, if the
    parent checklist is now complete, close the parent session too.
    The cascade is bounded: the parent checklist session has no
    `checklist_item_id` of its own so the second close can't re-enter
    this branch — no infinite recursion."""
    now = _now()
    cursor = await conn.execute(
        "UPDATE sessions SET closed_at = ?, updated_at = ? WHERE id = ?",
        (now, now, session_id),
    )
    await conn.commit()
    if cursor.rowcount == 0:
        return None
    row = await get_session(conn, session_id)
    if row is not None and row["checklist_item_id"] is not None:
        # Local import to avoid a static cycle with _checklists (which
        # itself needs to close the parent checklist session from its
        # auto-close path). Both directions are intentional; keeping
        # the imports local keeps the module graph acyclic at load
        # time.
        from bearings.db._checklists import (
            get_item,
            is_checklist_complete,
            toggle_item,
        )

        item = await toggle_item(conn, row["checklist_item_id"], checked=True)
        if item is not None:
            parent_checklist_id = item["checklist_id"]
            if await is_checklist_complete(conn, parent_checklist_id):
                # Recurse: close the checklist session. No further
                # cascade because the checklist row carries no
                # checklist_item_id (ValueError-guarded at create).
                await close_session(conn, parent_checklist_id)
        else:
            # Pointer dangled (item deleted mid-close). Refresh just
            # in case the SET NULL cascade left the session pointer
            # stale and swallow — the paired-chat close itself still
            # committed, which is the user's real intent.
            await get_item(conn, row["checklist_item_id"])
    return await get_session(conn, session_id)


async def reopen_session(
    conn: aiosqlite.Connection,
    session_id: str,
) -> dict[str, Any] | None:
    """Clear `closed_at`. Idempotent on already-open sessions (UPDATE
    matches but writes a no-op value). Bumps `updated_at` so the
    reopened session floats back to the top of the sidebar."""
    now = _now()
    cursor = await conn.execute(
        "UPDATE sessions SET closed_at = NULL, updated_at = ? WHERE id = ?",
        (now, session_id),
    )
    await conn.commit()
    if cursor.rowcount == 0:
        return None
    return await get_session(conn, session_id)


async def reopen_if_closed(
    conn: aiosqlite.Connection,
    *session_ids: str,
) -> None:
    """Clear `closed_at` on any listed session that carries it. Called
    from the reorg routes after a move/split/merge commits — if work
    resumed (messages moved in/out), the closed flag is stale. Silently
    skips open sessions (the WHERE clause matches zero rows) and
    unknown ids. Does not commit; the caller owns the transaction
    boundary so this composes with `move_messages_tx`'s own commit."""
    if not session_ids:
        return
    placeholders = ",".join("?" for _ in session_ids)
    now = _now()
    await conn.execute(
        f"UPDATE sessions SET closed_at = NULL, updated_at = ? "
        f"WHERE closed_at IS NOT NULL AND id IN ({placeholders})",
        (now, *session_ids),
    )
    await conn.commit()


async def add_session_cost(conn: aiosqlite.Connection, session_id: str, delta_usd: float) -> bool:
    """Accumulate SDK-reported cost onto the session row. Also bumps
    `updated_at` so a cost-only delta still re-sorts the sidebar — the
    current call path in `runner.py` pairs this with
    `mark_session_completed` (which bumps `updated_at` too), so the
    double-touch is a no-op there, but any future path that records
    cost without a MessageComplete stays sort-correct by default.

    Returns False if the session row is gone (e.g. deleted mid-stream)."""
    cursor = await conn.execute(
        "UPDATE sessions SET total_cost_usd = total_cost_usd + ?, updated_at = ? WHERE id = ?",
        (delta_usd, _now(), session_id),
    )
    await conn.commit()
    return cursor.rowcount > 0


async def list_all_sessions(
    conn: aiosqlite.Connection,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    where, params = _date_filter("s.created_at", date_from, date_to)
    sql = (
        f"SELECT {SESSION_COLS_WITH_COUNT} FROM sessions s{where} "
        "ORDER BY s.created_at ASC, s.id ASC"
    )
    async with conn.execute(sql, params) as cursor:
        return [_parse_tag_ids_csv(dict(row)) async for row in cursor]


async def touch_session(conn: aiosqlite.Connection, session_id: str) -> None:
    """Bump only `updated_at` so the session floats to the top of the
    sidebar sort. Called when a session starts working — runner goes
    idle → running — so the "active session" signal reaches every open
    client on the next poll, not just the one that submitted the
    prompt. `insert_message` already bumps on fresh prompts; this
    helper also covers the runner-boot replay path where the user row
    is already in the DB and wouldn't otherwise re-sort.

    No-op on unknown ids (UPDATE matches zero rows)."""
    await conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?",
        (_now(), session_id),
    )
    await conn.commit()


async def mark_session_completed(conn: aiosqlite.Connection, session_id: str) -> None:
    """Stamp `last_completed_at` (and `updated_at`) at the moment a
    MessageComplete lands. Drives the sidebar's "finished but unviewed"
    indicator — compared at render time against `last_viewed_at` to
    decide whether to paint the amber dot.

    No-op on unknown ids."""
    now = _now()
    await conn.execute(
        "UPDATE sessions SET last_completed_at = ?, updated_at = ? WHERE id = ?",
        (now, now, session_id),
    )
    await conn.commit()


async def mark_session_viewed(conn: aiosqlite.Connection, session_id: str) -> dict[str, Any] | None:
    """Stamp `last_viewed_at` so the sidebar can clear the "finished
    but unviewed" indicator. Does NOT bump `updated_at` — viewing a
    session shouldn't change its sort position. Returns the refreshed
    row, or None if the id is unknown."""
    cursor = await conn.execute(
        "UPDATE sessions SET last_viewed_at = ? WHERE id = ?",
        (_now(), session_id),
    )
    await conn.commit()
    if cursor.rowcount == 0:
        return None
    return await get_session(conn, session_id)
