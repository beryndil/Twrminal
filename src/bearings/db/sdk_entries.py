# mypy: disable-error-code=explicit-any
"""``sdk_session_entries`` table queries — SDK transcript JSONL mirror.

Per ``schema.sql`` the table is an opaque mirror of the Claude Code CLI's
per-session JSONL transcript. The SDK calls
:meth:`claude_agent_sdk.types.SessionStore.append` with batches of
transcript entries during turn execution; on respawn (model swap, idle
reap, server restart, recovery), the SDK calls
:meth:`claude_agent_sdk.types.SessionStore.load` and materialises the
returned entries into a temp ``CLAUDE_CONFIG_DIR/projects/.../<uuid>.jsonl``
that the new subprocess resumes from via ``--resume <uuid>``.

The :class:`bearings.agent.session_store.BearingsSessionStore` adapter
wraps these query helpers; the adapter is what
:mod:`bearings.agent.session_bootstrap` constructs and pins onto
``OptionsKwargs.session_store`` for every chat session.

Per the SDK contract (types.py docstring on :class:`SessionStoreEntry`):
"adapters should treat entries as pass-through blobs; round-tripping
``json.dumps``/``json.loads`` is the only required invariant." Bearings
does not parse the entry shape — it stores the JSON-encoded blob and
returns it verbatim on load.

Public surface:

* :func:`append` — bulk INSERT a batch of entries with monotonic per-
  session ``seq``. Idempotency on duplicate ``uuid`` fields inside
  entries is the SDK's responsibility (``append`` retries up to 3 times
  with backoff per the SDK contract); Bearings just appends.
* :func:`load` — SELECT all entries for a session, oldest-first, parsed
  back to dicts. Returns an empty list if the session has no entries
  yet (first spawn).
* :func:`count_for_session` — fast existence check without parsing the
  blobs. Used by :mod:`bearings.agent.session_bootstrap` to decide
  between ``session_id=<uuid>`` (first spawn) and ``resume=<uuid>``
  (subsequent spawns) on ``ClaudeAgentOptions``.
* :func:`delete_for_session` — explicit cleanup. The schema's
  ``ON DELETE CASCADE`` already drops mirror rows when the session row
  is deleted; this helper exists for the rare "discard SDK history but
  keep the Bearings session alive" path (e.g. a future "reset
  conversation" admin action).
"""

from __future__ import annotations

import json
from typing import Any

import aiosqlite

from bearings.db._id import now_iso


async def append(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    entries: list[dict[str, Any]],
) -> None:
    """INSERT a batch of SDK transcript entries with monotonic ``seq``.

    Per-session ``seq`` is computed as ``MAX(seq) + 1`` of existing rows
    (zero-based: the first entry gets ``seq=0``). All inserts share one
    timestamp so a turn's batch lands with a single sortable
    ``created_at`` even when the SDK emits dozens of partial-message
    entries in rapid succession.

    Args:
        connection: An open :class:`aiosqlite.Connection`. Foreign-key
            enforcement should already be ON (the bootstrap pragma in
            :mod:`bearings.db.connection` ensures this).
        session_id: The Bearings session id (``ses_<32hex>``) the
            entries belong to. The adapter is responsible for
            translating the SDK's UUID-form ``key.session_id`` back to
            this Bearings id via
            :func:`bearings.agent.sdk_session_id.sdk_uuid_to_bearings`.
        entries: A list of JSON-safe dicts as supplied by the SDK. Each
            is ``json.dumps``-ed verbatim; the structure is opaque to
            this module.

    Notes:
        * Empty batches are a no-op (no DB write, no commit). The SDK
          may call ``append([])`` in rare race conditions.
        * The function commits after the bulk INSERT so the entries are
          durable before the SDK's next ``append`` call (which arrives
          ~100ms later per the SDK adapter contract).
    """
    if not entries:
        return
    timestamp = now_iso()
    cursor = await connection.execute(
        "SELECT COALESCE(MAX(seq), -1) FROM sdk_session_entries WHERE session_id = ?",
        (session_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    next_seq = (0 if row is None else int(row[0])) + 1
    rows: list[tuple[str, int, str, str]] = []
    for offset, entry in enumerate(entries):
        rows.append(
            (
                session_id,
                next_seq + offset,
                json.dumps(entry, ensure_ascii=False),
                timestamp,
            )
        )
    await connection.executemany(
        "INSERT INTO sdk_session_entries (session_id, seq, entry_json, created_at) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    await connection.commit()


async def load(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
) -> list[dict[str, Any]]:
    """SELECT all SDK transcript entries for ``session_id``, oldest-first.

    Returns a list of parsed JSON dicts in original write order
    (``ORDER BY seq ASC``). Empty list when the session has no entries
    yet — the SDK's resume materializer treats ``None``/empty-list
    identically (both fall back to a fresh session), so an empty list
    is the right "no history" signal.
    """
    cursor = await connection.execute(
        "SELECT entry_json FROM sdk_session_entries WHERE session_id = ? ORDER BY seq ASC",
        (session_id,),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [json.loads(str(row[0])) for row in rows]


async def count_for_session(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
) -> int:
    """Number of mirror rows for ``session_id``. Cheap existence probe.

    Used by :mod:`bearings.agent.session_bootstrap` to choose between
    ``session_id=<uuid>`` on a first spawn (no entries yet) and
    ``resume=<uuid>`` on subsequent spawns (entries present). Avoiding
    the JSON parse cost of :func:`load` matters when the call happens
    on every supervisor materialisation.
    """
    cursor = await connection.execute(
        "SELECT COUNT(*) FROM sdk_session_entries WHERE session_id = ?",
        (session_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return 0 if row is None else int(row[0])


async def delete_for_session(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
) -> int:
    """Drop every mirror row for ``session_id``. Returns the row count deleted.

    The schema's ``ON DELETE CASCADE`` already runs this when the session
    row is deleted; this helper is for the "reset SDK conversation but
    keep the Bearings session alive" path. Currently unused by the
    runtime — exposed for future admin actions and for tests that need
    to simulate a fresh SDK spawn on a recycled session id.
    """
    cursor = await connection.execute(
        "DELETE FROM sdk_session_entries WHERE session_id = ?",
        (session_id,),
    )
    try:
        deleted = cursor.rowcount
    finally:
        await cursor.close()
    await connection.commit()
    return int(deleted) if deleted is not None else 0


__all__ = [
    "append",
    "count_for_session",
    "delete_for_session",
    "load",
]
