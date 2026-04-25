"""Assistant-turn DB persistence for `SessionRunner`.

`persist_assistant_turn` lands the streamed assistant message body
(plus optional thinking trace), attaches its tool calls, accrues the
session cost, and stamps `last_completed_at` for the sidebar's amber
"finished but unviewed" dot. Lives outside `runner.py` so the runner
keeps its own surface focused on the worker loop and stream fan-out.

Called from both the normal `MessageComplete` arm of `_execute_turn`
and the stop-requested synthetic-completion path. The runner is the
sole caller — public name (no underscore prefix) just because it now
crosses a module boundary.
"""

from __future__ import annotations

import aiosqlite

from bearings import metrics
from bearings.db import store


async def persist_assistant_turn(
    conn: aiosqlite.Connection,
    *,
    session_id: str,
    message_id: str,
    content: str,
    thinking: str | None,
    tool_call_ids: list[str],
    cost_usd: float | None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    cache_creation_tokens: int | None = None,
) -> None:
    await store.insert_message(
        conn,
        session_id=session_id,
        id=message_id,
        role="assistant",
        content=content,
        thinking=thinking,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
    )
    metrics.messages_persisted.labels(role="assistant").inc()
    await store.attach_tool_calls_to_message(
        conn, message_id=message_id, tool_call_ids=tool_call_ids
    )
    if cost_usd is not None:
        await store.add_session_cost(conn, session_id, cost_usd)
    # Stamp last_completed_at for the sidebar's "finished but unviewed"
    # amber dot. Runs on every assistant turn persist including the
    # stop-requested synthetic, so an interrupted turn still counts as
    # completed output for the viewer to read.
    await store.mark_session_completed(conn, session_id)
