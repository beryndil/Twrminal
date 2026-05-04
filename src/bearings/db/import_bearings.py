"""Database import from the original Bearings instance.

Migrates sessions, messages, tags, and related data from the main Bearings
database (~/.local/share/bearings/db.sqlite) into Bearings-v1's sessions.db.
Uses INSERT OR IGNORE to avoid overwriting existing records — only new rows
from the source are copied.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass
class ImportResult:
    """Result of an import operation."""

    tags_imported: int = 0
    sessions_imported: int = 0
    messages_imported: int = 0
    session_tags_imported: int = 0
    tag_memories_imported: int = 0
    checklist_items_imported: int = 0
    tags_skipped: int = 0
    sessions_skipped: int = 0
    messages_skipped: int = 0
    session_tags_skipped: int = 0
    tag_memories_skipped: int = 0
    checklist_items_skipped: int = 0
    errors: list[str] = field(default_factory=list)


async def import_from_bearings(
    *,
    dest: aiosqlite.Connection,
    source_path: Path,
    on_progress: Callable[[str, int, int], Awaitable[None]] | None = None,
) -> ImportResult:
    """Import all data from the original Bearings database into Bearings-v1.

    Args:
        dest: Target database connection (Bearings-v1's sessions.db)
        source_path: Path to source Bearings database (db.sqlite)
        on_progress: Optional async callback for progress updates.
                     Called with (table_name: str, imported: int, skipped: int)

    Returns:
        ImportResult with counts of imported/skipped rows per table.
        Rows with duplicate IDs are skipped (INSERT OR IGNORE).
        On error, the entire import rolls back (all-or-nothing).

    Raises:
        FileNotFoundError: if source_path does not exist
        aiosqlite.OperationalError: if any SQL operation fails (causes rollback)
    """
    if not os.path.exists(source_path):  # noqa: ASYNC240
        raise FileNotFoundError(f"Source database not found: {source_path}")

    result = ImportResult()

    async with aiosqlite.connect(source_path) as source:
        try:
            # Commit any implicit transaction aiosqlite may have opened so
            # that the explicit BEGIN below doesn't raise "cannot start a
            # transaction within a transaction".  This is safe: the caller
            # owns the connection and is not using it concurrently.
            await dest.commit()
            await dest.execute("BEGIN")

            # Tags: map default_working_dir → working_dir, synthesize updated_at
            tags_imported, tags_skipped = await _import_tags(source, dest, on_progress)
            result.tags_imported = tags_imported
            result.tags_skipped = tags_skipped

            # Sessions: drop sdk_session_id, default closing_summary to NULL
            sessions_imported, sessions_skipped = await _import_sessions(source, dest, on_progress)
            result.sessions_imported = sessions_imported
            result.sessions_skipped = sessions_skipped

            # Messages: direct copy
            messages_imported, messages_skipped = await _import_messages(source, dest, on_progress)
            result.messages_imported = messages_imported
            result.messages_skipped = messages_skipped

            # Session tags: direct copy
            st_imported, st_skipped = await _import_session_tags(source, dest, on_progress)
            result.session_tags_imported = st_imported
            result.session_tags_skipped = st_skipped

            # Tag memories: direct copy
            tm_imported, tm_skipped = await _import_tag_memories(source, dest, on_progress)
            result.tag_memories_imported = tm_imported
            result.tag_memories_skipped = tm_skipped

            # Checklist items: direct copy
            ci_imported, ci_skipped = await _import_checklist_items(source, dest, on_progress)
            result.checklist_items_imported = ci_imported
            result.checklist_items_skipped = ci_skipped

            await dest.execute("COMMIT")

        except Exception as e:
            # Best-effort rollback — silently ignore if no transaction is open.
            # contextlib.suppress() cannot await async calls, so try/except is
            # the only pattern available here.
            try:  # noqa: SIM105
                await dest.execute("ROLLBACK")
            except Exception:
                pass
            result.errors.append(f"Import failed and rolled back: {e}")

    return result


async def _import_tags(
    source: aiosqlite.Connection,
    dest: aiosqlite.Connection,
    on_progress: Callable[[str, int, int], Awaitable[None]] | None = None,
) -> tuple[int, int]:
    """Import tags table. Map default_working_dir → working_dir."""
    async with source.execute(
        """
        SELECT id, name, color, created_at, default_working_dir, default_model
        FROM tags
        """
    ) as cursor:
        source_rows = await cursor.fetchall()

    imported = 0
    skipped = 0

    for row in source_rows:
        tag_id, name, color, created_at, default_working_dir, default_model = row
        try:
            changes_before = dest.total_changes
            await dest.execute(
                """
                INSERT OR IGNORE INTO tags
                (id, name, color, created_at, updated_at, working_dir, default_model)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tag_id,
                    name,
                    color,
                    created_at,
                    created_at,  # synthesize updated_at = created_at
                    default_working_dir,
                    default_model,
                ),
            )
            # Check if row was inserted (rowcount > 0) or ignored (rowcount == 0)
            if dest.total_changes > changes_before:
                imported += 1
            else:
                skipped += 1
        except Exception:
            # Continue on individual row errors; they're captured at the ROLLBACK level
            pass

    if on_progress:
        await on_progress("tags", imported, skipped)

    return imported, skipped


async def _import_sessions(
    source: aiosqlite.Connection,
    dest: aiosqlite.Connection,
    on_progress: Callable[[str, int, int], Awaitable[None]] | None = None,
) -> tuple[int, int]:
    """Import sessions table. Drop sdk_session_id, set closing_summary to NULL."""
    async with source.execute(
        """
        SELECT id, created_at, updated_at, working_dir, model, title,
               max_budget_usd, total_cost_usd, description, session_instructions,
               permission_mode, last_context_pct, last_context_tokens,
               last_context_max, closed_at, kind, pinned, error_pending
        FROM sessions
        """
    ) as cursor:
        source_rows = await cursor.fetchall()

    imported = 0
    skipped = 0

    for row in source_rows:
        (
            session_id,
            created_at,
            updated_at,
            working_dir,
            model,
            title,
            max_budget_usd,
            total_cost_usd,
            description,
            session_instructions,
            permission_mode,
            last_context_pct,
            last_context_tokens,
            last_context_max,
            closed_at,
            kind,
            pinned,
            error_pending,
        ) = row

        try:
            # v1 title NOT NULL — coerce NULL/empty to sentinel (mirrors migration script)
            safe_title = title if title else "(untitled)"
            changes_before = dest.total_changes
            await dest.execute(
                """
                INSERT OR IGNORE INTO sessions
                (id, created_at, updated_at, working_dir, model, title,
                 max_budget_usd, total_cost_usd, description, session_instructions,
                 permission_mode, last_context_pct, last_context_tokens,
                 last_context_max, closed_at, kind, pinned, error_pending,
                 message_count, closing_summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
                """,
                (
                    session_id,
                    created_at,
                    updated_at,
                    working_dir or "",
                    model or "",
                    safe_title,
                    max_budget_usd or 0.0,
                    total_cost_usd or 0.0,
                    description,
                    session_instructions,
                    permission_mode,
                    last_context_pct,
                    last_context_tokens,
                    last_context_max,
                    closed_at,
                    kind or "chat",  # default to 'chat' if None
                    pinned if pinned is not None else 0,
                    error_pending if error_pending is not None else 0,
                ),
            )
            if dest.total_changes > changes_before:
                imported += 1
            else:
                skipped += 1
        except Exception:
            pass

    if on_progress:
        await on_progress("sessions", imported, skipped)

    return imported, skipped


async def _import_messages(
    source: aiosqlite.Connection,
    dest: aiosqlite.Connection,
    on_progress: Callable[[str, int, int], Awaitable[None]] | None = None,
) -> tuple[int, int]:
    """Import messages table.

    v0.17 columns not present in v1 (thinking, cache_creation_tokens,
    replay_attempted_at, pinned, hidden_from_context, attachments) are
    dropped.  v1-specific routing columns are NULL-filled except
    routing_source, which receives 'unknown_legacy' for assistant rows
    (per spec §5 "Backfill for legacy data").
    """
    async with source.execute(
        """
        SELECT id, session_id, role, content, created_at,
               input_tokens, output_tokens, cache_read_tokens
        FROM messages
        """
    ) as cursor:
        source_rows = await cursor.fetchall()

    imported = 0
    skipped = 0

    for row in source_rows:
        id_val, session_id, role, content, created_at, input_tokens, output_tokens, cache_read = row
        routing_source = "unknown_legacy" if role == "assistant" else None

        try:
            changes_before = dest.total_changes
            await dest.execute(
                """
                INSERT OR IGNORE INTO messages
                (id, session_id, role, content, created_at,
                 routing_source, cache_read_tokens, input_tokens, output_tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    id_val,
                    session_id,
                    role,
                    content or "",  # v1 content NOT NULL; coerce NULL to empty string
                    created_at,
                    routing_source,
                    cache_read,
                    input_tokens,
                    output_tokens,
                ),
            )
            if dest.total_changes > changes_before:
                imported += 1
            else:
                skipped += 1
        except Exception:
            pass

    if on_progress:
        await on_progress("messages", imported, skipped)

    return imported, skipped


async def _import_session_tags(
    source: aiosqlite.Connection,
    dest: aiosqlite.Connection,
    on_progress: Callable[[str, int, int], Awaitable[None]] | None = None,
) -> tuple[int, int]:
    """Import session_tags table. Direct copy."""
    async with source.execute(
        """
        SELECT session_id, tag_id, created_at FROM session_tags
        """
    ) as cursor:
        source_rows = await cursor.fetchall()

    imported = 0
    skipped = 0

    for row in source_rows:
        try:
            changes_before = dest.total_changes
            await dest.execute(
                """
                INSERT OR IGNORE INTO session_tags (session_id, tag_id, created_at)
                VALUES (?, ?, ?)
                """,
                row,
            )
            if dest.total_changes > changes_before:
                imported += 1
            else:
                skipped += 1
        except Exception:
            pass

    if on_progress:
        await on_progress("session_tags", imported, skipped)

    return imported, skipped


async def _import_tag_memories(
    source: aiosqlite.Connection,
    dest: aiosqlite.Connection,
    on_progress: Callable[[str, int, int], Awaitable[None]] | None = None,
) -> tuple[int, int]:
    """Import tag_memories table.

    v0.17 schema: (tag_id TEXT PK, content TEXT, updated_at TEXT).
    v1 schema: (id AUTOINCREMENT, tag_id INTEGER, title TEXT NOT NULL,
                body TEXT NOT NULL, enabled INTEGER, created_at TEXT, updated_at TEXT).

    Mapping: content → body, sentinel title "Imported from v0.17", enabled=1,
    created_at = updated_at.  Idempotency uses (tag_id, title) check (per the
    migration script's natural-key approach — v1 has no UNIQUE on the pair).
    """
    _sentinel_title = "Imported from v0.17"
    async with source.execute("SELECT tag_id, content, updated_at FROM tag_memories") as cursor:
        source_rows = await cursor.fetchall()

    imported = 0
    skipped = 0

    for row in source_rows:
        tag_id, content, updated_at = row
        try:
            # Check natural-key existence before insert (no stable PK to use with OR IGNORE)
            async with dest.execute(
                "SELECT 1 FROM tag_memories WHERE tag_id = ? AND title = ?",
                (tag_id, _sentinel_title),
            ) as cur:
                existing = await cur.fetchone()

            if existing is not None:
                skipped += 1
                continue

            changes_before = dest.total_changes
            await dest.execute(
                """
                INSERT INTO tag_memories
                (tag_id, title, body, enabled, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (tag_id, _sentinel_title, content or "", updated_at, updated_at),
            )
            if dest.total_changes > changes_before:
                imported += 1
        except Exception:
            pass

    if on_progress:
        await on_progress("tag_memories", imported, skipped)

    return imported, skipped


async def _import_checklist_items(
    source: aiosqlite.Connection,
    dest: aiosqlite.Connection,
    on_progress: Callable[[str, int, int], Awaitable[None]] | None = None,
) -> tuple[int, int]:
    """Import checklist_items table.

    v0.17 and v1 share the same column shape (per migration script).
    v0.17 uses INTEGER ids, matching v1's INTEGER PRIMARY KEY.
    """
    async with source.execute(
        """
        SELECT id, checklist_id, parent_item_id, label, notes, sort_order,
               checked_at, chat_session_id, blocked_at, blocked_reason_category,
               blocked_reason_text, created_at, updated_at
        FROM checklist_items
        """
    ) as cursor:
        source_rows = await cursor.fetchall()

    imported = 0
    skipped = 0

    for row in source_rows:
        try:
            changes_before = dest.total_changes
            await dest.execute(
                """
                INSERT OR IGNORE INTO checklist_items
                (id, checklist_id, parent_item_id, label, notes, sort_order,
                 checked_at, chat_session_id, blocked_at, blocked_reason_category,
                 blocked_reason_text, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
            if dest.total_changes > changes_before:
                imported += 1
            else:
                skipped += 1
        except Exception:
            pass

    if on_progress:
        await on_progress("checklist_items", imported, skipped)

    return imported, skipped


__all__ = ["ImportResult", "import_from_bearings"]
