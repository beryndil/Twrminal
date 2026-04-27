"""Visit-existing leg-resolution + silent-exit nudge mixin.

The methods in :class:`_SessionsMixin` decide which leg session to
use (spawn-fresh vs reuse the manually-linked session) and submit
the nudge turn that asks the agent to emit a missing sentinel.
Extracted from ``auto_driver.py`` (§FileSize); bodies unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

import aiosqlite

from bearings.agent.auto_driver import prompts
from bearings.agent.auto_driver.contracts import DriverConfig, DriverRuntime
from bearings.db import store

log = logging.getLogger(__name__)


class _SessionsMixin:
    """Driver methods for leg-session resolution and the silent-exit
    nudge."""

    # Type-only attribute declarations (populated by Driver.__init__).
    _conn: aiosqlite.Connection
    _runtime: DriverRuntime
    _config: DriverConfig

    async def _existing_open_session(self, item: dict[str, Any]) -> str | None:
        """Return the open chat session linked to ``item``, or None.

        Used in visit-existing mode to decide leg 1's session. The
        item dict already carries ``chat_session_id`` (set by the
        manual "Work on this" path or by ``PATCH /items/{id}`` in
        tour mode). We re-fetch the session row here to also gate on
        ``closed_at`` — a closed session would yield a runner the
        user can't see in the open sidebar list, and trying to drive
        an SDK turn against it is not useful.

        Returns the session id when there's an open chat session
        linked to this item; None when no link, the link is stale
        (session deleted), or the linked session is closed.

        Side effect (2026-04-25 fix for unattended-run permission
        gap): before returning the session id, force its
        ``permission_mode`` to the driver's ``leg_permission_mode``
        (default ``bypassPermissions``) and drop any cached runner
        so the next ``run_turn`` rebuilds with the new mode. Without
        this the existing session's pre-set ``permission_mode``
        (often ``default`` from manual interactive use) would carry
        into the autonomous run and the SDK's ``can_use_tool`` hook
        would park on every Edit/Bash, hanging the leg forever.
        Spawned legs get the same mode set in
        ``AgentRunnerDriverRuntime.spawn_leg``; this branch is the
        visit-existing equivalent.
        """
        existing_id = item.get("chat_session_id")
        if not existing_id:
            return None
        row = await store.get_session(self._conn, str(existing_id))
        if row is None:
            return None
        if row.get("closed_at") is not None:
            return None
        session_id = str(existing_id)
        # Force permission_mode on the row. Idempotent — if the row
        # already carries the same value the UPDATE is a no-op write.
        try:
            await store.set_session_permission_mode(
                self._conn, session_id, self._config.leg_permission_mode
            )
        except Exception:
            # A bad permission_mode value is a programming error
            # (DriverConfig validates at construction conceptually);
            # log + continue rather than halt the visit.
            log.exception(
                "autonomous driver: failed to force permission_mode on visit-existing session %s",
                session_id,
            )
        # Drop any cached runner for this session id. Required because
        # `RunnerRegistry.get_or_create` returns the cached runner if
        # one exists — and the cached runner was built with the OLD
        # permission_mode, so the freshly-persisted bypassPermissions
        # value wouldn't take effect this leg. teardown_leg is
        # idempotent, so a no-op when nothing is cached.
        await self._runtime.teardown_leg(session_id)
        return session_id

    async def _existing_session_still_open(self, session_id: str) -> bool:
        """True when the visit-existing original session is still
        valid for parent re-entry after a blocker resolution. Closed
        sessions, deleted rows, or anything else that would make a
        ``run_turn`` call useless return False so the caller falls
        back to spawning a fresh leg. Defensive: the parent's session
        normally stays open while children resolve (children's
        toggle-cascade close only touches the children's own legs,
        not the parent's), but a sibling-toggle race or manual close
        could land here."""
        row = await store.get_session(self._conn, session_id)
        if row is None:
            return False
        return row.get("closed_at") is None

    async def _request_completion_nudge(self, leg_session_id: str, *, under_pressure: bool) -> str:
        """Submit one extra turn asking the agent to emit a sentinel.

        Used whenever a leg's main turn ends without ``item_done``,
        ``handoff_plug``, or blocking followups. See
        :func:`prompts.build_nudge_prompt` for the two prompt
        variants (under-pressure vs below-threshold).

        Returns the assistant's response text for sentinel parsing.
        Exceptions propagate — the caller treats any error as
        silent-exit failure.

        Kept on the driver (not the runtime) so the prompt text is
        authoritative in one place and test stubs don't have to
        re-implement the nudge shape."""
        prompt = prompts.build_nudge_prompt(under_pressure=under_pressure)
        return await self._runtime.run_turn(
            session_id=leg_session_id,
            prompt=prompt,
        )
