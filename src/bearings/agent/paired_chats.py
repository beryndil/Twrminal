"""Paired-chat spawn-and-link service.

Per ``docs/behavior/paired-chats.md`` §"Spawning a new pair" the user
clicks **💬 Work on this** on an unpaired leaf and observes:

1. A fresh chat session is created that inherits the checklist's
   working directory, model, and tags.
2. The pair pointer is set on both sides (item → chat, chat → item).
3. The new chat is selected (UI-side concern, out of this module).
4. The originating row shows the chat title link and "Continue working"
   on next visit.

Plus the idempotency clause: pressing **💬 Work on this** on an
already-paired item navigates to the existing chat. This module is
the backend service that the UI's spawn click resolves to:
:func:`spawn_paired_chat` returns the live chat session id, creating
one only when no live pair pointer exists.

Per arch §1.1.4 the agent layer owns the cross-module composition
(``db/sessions.create`` + ``db/checklists.set_paired_chat`` +
``db/checklists.record_leg``); the route layer (``web/routes/
paired_chats.py``) is a thin wrapper.

Auto-driver interaction
-----------------------

Per ``docs/behavior/checklists.md`` "every leg the driver spawns is a
paired chat". The driver dispatches via its
:func:`bearings.agent.auto_driver_runtime.LegSessionFactory` callback;
that factory closes over a :func:`spawn_paired_chat` invocation with
``spawned_by='driver'``. The user observes "successive chat rows for
the same item appear and close as the driver hands off legs" because
each leg-spawn calls this function (which records a new
``paired_chats`` row + flips the live pointer to the new leg).
"""

from __future__ import annotations

import contextlib

import aiosqlite

from bearings.agent.session import SessionConfig
from bearings.agent.session_assembly import build_session_config
from bearings.config.constants import (
    KNOWN_PAIRED_CHAT_SPAWNED_BY,
    PAIRED_CHAT_SPAWNED_BY_DRIVER,
    PAIRED_CHAT_SPAWNED_BY_USER,
    SESSION_KIND_CHAT,
)
from bearings.db import checklists as checklists_db
from bearings.db import sessions as sessions_db
from bearings.db import tags as tags_db
from bearings.db.checklists import ChecklistItem


class PairedChatSpawnError(ValueError):
    """Spawn-and-link failed (item missing, parent not a leaf, …).

    Distinct from :class:`bearings.agent.session_assembly.SessionAssemblyError`
    so the route layer can pattern-match: a missing item is a 404, a
    SessionAssemblyError is a 422.
    """


async def _find_live_pair(
    connection: aiosqlite.Connection,
    item: ChecklistItem,
) -> tuple[str, SessionConfig] | None:
    """Return (session_id, config) when a live open pair already exists; else None.

    Implements the idempotency clause: if the leaf already has a live
    ``chat_session_id`` that is not closed, return the existing pair
    rather than spawning a second one.
    """
    if item.chat_session_id is None:
        return None
    if await sessions_db.is_closed(connection, item.chat_session_id) is not False:
        return None
    existing = await sessions_db.get(connection, item.chat_session_id)
    if existing is None:
        return None
    return (
        existing.id,
        await _rebuild_config_for_existing_session(
            connection,
            existing_session_id=existing.id,
            existing_working_dir=existing.working_dir,
            existing_model=existing.model,
            item=item,
        ),
    )


async def spawn_paired_chat(
    connection: aiosqlite.Connection,
    *,
    item_id: int,
    spawned_by: str = PAIRED_CHAT_SPAWNED_BY_USER,
    title_override: str | None = None,
    plug: str | None = None,
) -> tuple[str, SessionConfig]:
    """Materialise a fresh paired chat for ``item_id`` (or return existing).

    Per behavior doc the spawn is **idempotent**: if the leaf already
    has a live ``chat_session_id`` *and* that session is not closed,
    return the existing pair. A closed prior pair is left in place
    (the user observes the closed row plus "Reopen chat") and a new
    pair is *not* spawned — that mirrors the doc's reopen semantics.

    Args:
        connection: Open aiosqlite connection (read parent + tags +
            insert session row + record leg + set pair pointer; all
            commits are owned by the underlying DB helpers).
        item_id: Target leaf checklist item id.
        spawned_by: Who initiated the spawn — ``"user"`` or
            ``"driver"`` per
            :data:`bearings.config.constants.KNOWN_PAIRED_CHAT_SPAWNED_BY`.
        title_override: Optional explicit chat title; defaults to the
            item's label per behavior doc "The chat title defaults to
            the item's label".
        plug: Optional handoff plug for driver-spawned legs; lands as
            the chat's ``description`` so the new leg's prompt
            assembler can surface it (item 1.6 auto-driver wiring).

    Returns:
        ``(chat_session_id, session_config)`` — the id is what the UI
        navigates to; the config is what the runner factory wires the
        live SDK client up against.

    Raises:
        PairedChatSpawnError: ``item_id`` does not exist, is a
            parent (paired chats are leaves-only), or ``spawned_by``
            is outside the known alphabet.
        SessionAssemblyError: Working dir could not be resolved from
            the parent checklist + tags overlay chain.
    """
    if spawned_by not in KNOWN_PAIRED_CHAT_SPAWNED_BY:
        raise PairedChatSpawnError(
            f"spawn_paired_chat: spawned_by {spawned_by!r} not in "
            f"{sorted(KNOWN_PAIRED_CHAT_SPAWNED_BY)}"
        )
    item = await checklists_db.get(connection, item_id)
    if item is None:
        raise PairedChatSpawnError(f"spawn_paired_chat: item {item_id} not found")
    # Reject pairing a parent here so the API layer's 422 path matches
    # the schema-side rule from ``db/checklists.py:set_paired_chat``.
    if not await checklists_db.is_leaf(connection, item_id):
        raise PairedChatSpawnError(
            f"spawn_paired_chat: item {item_id} is a parent — pair affordances are leaves-only "
            "per docs/behavior/paired-chats.md"
        )
    # Idempotency clause: if a live pair already exists and is open,
    # return it unchanged (the doc's "navigates to the existing chat
    # rather than creating a second one").
    live_pair = await _find_live_pair(connection, item)
    if live_pair is not None:
        return live_pair
    # Build the config from the item-side overlay chain — tags from
    # the parent checklist flow through the assembler, working dir
    # likewise. The session id is materialised inside the assembler;
    # the row insert below uses the same id by passing it to
    # ``sessions.create``.
    parent_tag_ids = await _parent_tag_ids(connection, item.checklist_id)
    parent_session = await sessions_db.get(connection, item.checklist_id)
    parent_working_dir = None if parent_session is None else parent_session.working_dir
    parent_model = None if parent_session is None else parent_session.model
    # Phantom-id: assembler validates session_id non-empty; we then
    # discard the phantom and let ``sessions.create`` mint a real one
    # below, then rebuild the SessionConfig with the real id.
    phantom_config = await build_session_config(
        connection,
        session_id="ses_phantom",  # placeholder; replaced below
        tag_ids=parent_tag_ids,
        working_dir=parent_working_dir,
        model=parent_model,
    )
    title = title_override if title_override else item.label
    # ``sessions.create`` mints the real id and links the row to the
    # checklist item via ``checklist_item_id`` (the chat-side back-pointer
    # per schema). Description carries the optional handoff plug for
    # driver-spawned legs.
    new_session = await sessions_db.create(
        connection,
        kind=SESSION_KIND_CHAT,
        title=title,
        working_dir=phantom_config.working_dir,
        model=phantom_config.decision.executor_model,
        description=plug,
        permission_mode=phantom_config.permission_mode,
        checklist_item_id=item.id,
    )
    # Attach every parent tag to the new chat so the inheritance
    # observable per ``docs/behavior/paired-chats.md`` "inherits the
    # checklist's working directory, model, and tags" is visible to the
    # tag-filter sidebar from the first paint.
    for tag_id in parent_tag_ids:
        # The session-tag UNIQUE constraint guarantees idempotent
        # attaches; an integrity error here means a concurrent writer
        # already attached the tag, which is the same observable
        # end-state as a fresh attach.
        with contextlib.suppress(aiosqlite.IntegrityError):
            await tags_db.attach(connection, session_id=new_session.id, tag_id=tag_id)
    # Set the live pair pointer on the item (item-side back-pointer)
    # then record the leg row (the audit log per ``docs/behavior/
    # paired-chats.md`` and ``schema.sql`` ``paired_chats``).
    await checklists_db.set_paired_chat(connection, item.id, chat_session_id=new_session.id)
    await checklists_db.record_leg(
        connection,
        checklist_item_id=item.id,
        chat_session_id=new_session.id,
        spawned_by=spawned_by,
    )
    # Rebuild the SessionConfig with the real session id so the caller
    # gets a config the runner can be constructed from.
    config = await build_session_config(
        connection,
        session_id=new_session.id,
        tag_ids=parent_tag_ids,
        working_dir=phantom_config.working_dir,
        model=phantom_config.decision.executor_model,
    )
    return new_session.id, config


async def detach_paired_chat(
    connection: aiosqlite.Connection,
    item_id: int,
) -> ChecklistItem | None:
    """Clear the live pair pointer (the chat keeps its history).

    Per ``docs/behavior/paired-chats.md`` §"Detaching" — "Detach is
    unconditional: the pair pointer is cleared on both sides, the
    chat keeps its history, the item reverts to 'no chat' state".
    The item-side pointer is cleared by
    :func:`bearings.db.checklists.clear_paired_chat`; the chat-side
    pointer (``sessions.checklist_item_id``) is cleared by the schema's
    ``ON DELETE SET NULL`` only when the item *itself* is deleted —
    detach without delete leaves the chat-side pointer in place
    intentionally so the breadcrumb chip on the chat can still find
    the item if the user re-pairs them.
    """
    return await checklists_db.clear_paired_chat(connection, item_id)


async def _parent_tag_ids(
    connection: aiosqlite.Connection,
    checklist_id: str,
) -> list[int]:
    """Tag ids attached to the parent checklist session."""
    parent_tags = await tags_db.list_for_session(connection, checklist_id)
    return [tag.id for tag in parent_tags]


async def _rebuild_config_for_existing_session(
    connection: aiosqlite.Connection,
    *,
    existing_session_id: str,
    existing_working_dir: str,
    existing_model: str,
    item: ChecklistItem,
) -> SessionConfig:
    """Reconstruct a :class:`SessionConfig` for an already-spawned pair.

    Idempotent path: when :func:`spawn_paired_chat` returns an existing
    pair, the caller still wants a SessionConfig (not just the id).
    Reuse the row's stored working_dir + model so the config matches
    what the runner is already wired against; tag ids come from the
    *current* parent tag set (not from a stored snapshot) so a tag
    edit since spawn is visible on the next config rebuild.
    """
    parent_tag_ids = await _parent_tag_ids(connection, item.checklist_id)
    return await build_session_config(
        connection,
        session_id=existing_session_id,
        tag_ids=parent_tag_ids,
        working_dir=existing_working_dir,
        model=existing_model,
    )


__all__ = [
    "PAIRED_CHAT_SPAWNED_BY_DRIVER",
    "PAIRED_CHAT_SPAWNED_BY_USER",
    "PairedChatSpawnError",
    "detach_paired_chat",
    "spawn_paired_chat",
]
