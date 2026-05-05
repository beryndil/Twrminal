"""SDK :class:`SessionStore` adapter backed by the Bearings DB.

The SDK's :class:`claude_agent_sdk.types.SessionStore` is the contract
that lets a host application mirror the Claude Code CLI's per-session
JSONL transcript to durable external storage. The adapter receives an
``append`` callback after every batch of transcript lines the
subprocess writes locally, and the adapter answers ``load`` calls when
the SDK materialises a resume session into a temp ``CLAUDE_CONFIG_DIR``.

Bearings persists those entries via :mod:`bearings.db.sdk_entries` so
the SDK supervisor's respawn path (model swap, idle reap, server
restart, recovery from ERROR) can hand the new subprocess full
conversation context. Without this adapter, every respawn would start
with empty context and the user observes "this is the start of the
session" on every model swap — the bug
:func:`bearings.agent.sdk_loop.run_session_loop` was diagnosed against
on 2026-05-05.

Design notes:

* **Per-session identity translation.** The SDK keys every operation by
  ``SessionKey({"project_key": …, "session_id": <uuid>})``. Bearings
  stores entries under the Bearings session id (``ses_<32hex>``), so
  the adapter's first job on every callback is to translate the
  incoming UUID back to the Bearings id via
  :func:`bearings.agent.sdk_session_id.sdk_uuid_to_bearings`.
* **Subagent transcripts deferred.** The SDK reserves ``key["subpath"]``
  for subagent JSONL files (e.g. ``"subagents/agent-{id}"``). v1 stores
  only the main transcript and silently drops subagent batches; the
  parent session's resume continues to work because the SDK's
  ``list_subkeys`` is optional (the SDK falls back to "main only" when
  unimplemented). Subagent persistence is logged in TODO.md for a
  future item that surfaces a UI consumer.
* **Append durability is at-least-once.** The SDK retries failed
  batches (3 attempts with backoff per the contract). Bearings inserts
  are atomic per ``append()`` call; same entry replaying across retries
  is harmless because the per-session ``seq`` advances monotonically
  and the SDK's resume materialiser de-duplicates by entry ``uuid`` at
  read time.

The adapter is instantiated by :mod:`bearings.agent.session_bootstrap`
once per session (closure-captured DB connection factory + Bearings
session id), and pinned onto :class:`bearings.agent.options.OptionsKwargs`
for SDK splat at client init.

References:

* SDK :class:`claude_agent_sdk.types.SessionStore` Protocol +
  :class:`SessionKey` / :class:`SessionStoreEntry` shapes.
* :mod:`bearings.db.sdk_entries` — the storage queries.
* :mod:`bearings.agent.sdk_session_id` — id translation.
"""
# mypy: disable-error-code=explicit-any

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiosqlite

from bearings.agent.sdk_session_id import sdk_uuid_to_bearings
from bearings.db import sdk_entries as sdk_entries_db

_log = logging.getLogger(__name__)

# Type alias for the DB factory signature the adapter takes — same shape
# the bearings_mcp module uses for its CloseSessionDeps so callers can
# share a single ``async def db_factory()`` closure.
type DbConnectionFactory = Callable[[], Awaitable[aiosqlite.Connection]]


class BearingsSessionStore:
    """Bridge :class:`claude_agent_sdk.types.SessionStore` ↔ Bearings DB.

    Implements the two required methods (``append`` + ``load``); the
    optional methods (``list_sessions`` / ``list_session_summaries`` /
    ``delete`` / ``list_subkeys``) are intentionally absent — Bearings
    owns its session listing surface (the sidebar) and never delegates
    to the SDK's listing primitives.

    The adapter is duck-typed against the SDK Protocol — no inheritance
    needed (per the SDK docstring: "a duck-typed adapter need not
    subclass ``SessionStore``").
    """

    def __init__(self, *, db_factory: DbConnectionFactory) -> None:
        """Construct the adapter bound to ``db_factory``.

        Args:
            db_factory: A no-argument async callable returning the
                shared :class:`aiosqlite.Connection`. Bearings v1 runs
                a single long-lived connection on
                ``app.state.db_connection``; the bootstrap closes over
                that connection and passes it through here.
        """
        self._db_factory = db_factory

    async def append(
        self,
        key: dict[str, Any],
        entries: list[dict[str, Any]],
    ) -> None:
        """Mirror a batch of transcript entries to ``sdk_session_entries``.

        Subagent batches (``key`` carries a ``subpath``) are dropped with
        a debug log — v1 doesn't persist subagent transcripts. The main
        transcript still resumes correctly because the SDK's
        ``list_subkeys`` is optional (absent → resume only materialises
        the main transcript per the SDK contract).
        """
        if key.get("subpath"):
            _log.debug(
                "BearingsSessionStore.append: dropping %d subagent entries "
                "for subpath %r (subagent persistence deferred)",
                len(entries),
                key["subpath"],
            )
            return
        if not entries:
            return
        bearings_session_id = sdk_uuid_to_bearings(str(key["session_id"]))
        connection = await self._db_factory()
        await sdk_entries_db.append(
            connection,
            session_id=bearings_session_id,
            entries=entries,
        )

    async def load(self, key: dict[str, Any]) -> list[dict[str, Any]] | None:
        """Return all main-transcript entries for the session, or ``None``.

        Returns ``None`` (not an empty list) when the session has no
        entries yet — the SDK's resume materialiser treats ``None`` as
        "the session was never written to this store" and falls through
        to a fresh-session spawn. An empty list would be ambiguous (the
        SDK contract permits adapters that "cannot distinguish 'never
        written' from 'emptied'" to return ``None`` for both, so v1
        chooses the simpler behaviour).
        """
        if key.get("subpath"):
            # Subagent transcripts not persisted in v1.
            return None
        bearings_session_id = sdk_uuid_to_bearings(str(key["session_id"]))
        connection = await self._db_factory()
        count = await sdk_entries_db.count_for_session(
            connection,
            session_id=bearings_session_id,
        )
        if count == 0:
            return None
        return await sdk_entries_db.load(
            connection,
            session_id=bearings_session_id,
        )


__all__ = [
    "BearingsSessionStore",
    "DbConnectionFactory",
]
