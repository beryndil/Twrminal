"""Worker-loop and per-turn execution for `SessionRunner`.

Lives outside `runner.py` so the runner module keeps to the public
surface (lifecycle, queue, subscribers, approvals, reaper hook) while
the bulkier streaming/persistence path moves here. Every function in
this module takes a `SessionRunner` reference and reads/mutates it
directly — they ARE the runner's worker behavior, just split out of
the class body for size. No locking concerns: the worker task is the
sole driver.

Public names (no underscore prefix) just because they now cross a
module boundary; nothing outside `runner.py` should be calling them.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import aiosqlite
from claude_agent_sdk import ClaudeSDKError

from bearings import metrics
from bearings.agent._attachments import prune_and_serialize, substitute_tokens
from bearings.agent.events import (
    ContextUsage,
    ErrorEvent,
    MessageComplete,
    MessageStart,
    Thinking,
    TodoWriteUpdate,
    Token,
    ToolCallEnd,
    ToolCallStart,
    ToolOutputDelta,
    TurnReplayed,
)
from bearings.agent.persist import persist_assistant_turn
from bearings.agent.runner_types import _Replay, _Shutdown, _Submit
from bearings.agent.sessions_broker import publish_session_upsert
from bearings.db import store

if TYPE_CHECKING:
    from bearings.agent.runner import SessionRunner

log = logging.getLogger(__name__)


async def maybe_replay_orphaned_prompt(runner: SessionRunner) -> None:
    """If the DB shows a user message with no assistant reply and no
    prior replay attempt, re-queue it as this runner's first turn and
    emit a `TurnReplayed` event for any subscriber to notice.

    The failure mode this recovers from: the service was stopped
    (SIGTERM, OOM, crash) after persisting the user's prompt but
    before the SDK produced an assistant reply. Without this hook the
    orphaned prompt sits in history forever with no follow-up unless
    the user types it again — and the original ask loses its
    wall-clock urgency ("I came back and nothing happened").

    Best-effort: any DB failure is logged and swallowed. A broken
    replay scan must never block a fresh runner from accepting new
    user prompts.
    """
    try:
        orphan = await store.find_replayable_prompt(runner.db, runner.session_id)
    except aiosqlite.Error:
        log.exception(
            "runner %s: replay scan failed; continuing without replay",
            runner.session_id,
        )
        return
    if orphan is None:
        return
    try:
        marked = await store.mark_replay_attempted(runner.db, orphan["id"])
    except aiosqlite.Error:
        log.exception(
            "runner %s: replay mark failed; skipping replay to avoid loop",
            runner.session_id,
        )
        return
    if not marked:
        # Row vanished or another actor marked it first — treat as
        # "handled elsewhere" and do nothing.
        return
    await runner._emit_event(TurnReplayed(session_id=runner.session_id, message_id=orphan["id"]))
    # `attachments` is a JSON string (or None) from the DB column;
    # parse eagerly so the worker can feed it straight into the
    # substitute_tokens helper without a second decode path.
    raw_attachments = orphan.get("attachments")
    parsed_attachments: list[dict[str, Any]] | None = None
    if raw_attachments:
        try:
            parsed = json.loads(raw_attachments)
            if isinstance(parsed, list):
                parsed_attachments = parsed
        except (json.JSONDecodeError, TypeError):
            # A malformed JSON row is a surprise but not a show-stopper
            # — fall through and replay without substitution (the text
            # still carries `[File N]` tokens, which Claude will just
            # see as literal).
            log.warning(
                "runner %s: orphan %s has unparseable attachments JSON",
                runner.session_id,
                orphan["id"],
            )
    await runner._prompts.put(_Replay(orphan["content"], parsed_attachments))
    log.info(
        "runner %s: replayed orphaned user prompt id=%s",
        runner.session_id,
        orphan["id"],
    )


async def run_worker(runner: SessionRunner) -> None:
    """Main worker loop: replay any orphaned prompt, then drain the
    queue one turn at a time until `_Shutdown` arrives."""
    # Recover orphaned prompts from prior-crash / prior-restart. Must
    # run before the first `get()` so the replayed prompt is the first
    # turn this worker executes — any real user prompt submitted after
    # reconnect naturally queues behind it.
    await maybe_replay_orphaned_prompt(runner)
    while True:
        item = await runner._prompts.get()
        if isinstance(item, _Shutdown):
            return
        attachments: list[dict[str, Any]] | None
        if isinstance(item, _Replay):
            prompt = item.prompt
            attachments = item.attachments
            persist_user = False
        elif isinstance(item, _Submit):
            prompt = item.prompt
            attachments = item.attachments
            persist_user = True
        else:
            prompt = item
            attachments = None
            persist_user = True
        runner._status = "running"
        # A turn is live — not quiet regardless of subscriber count.
        # Clear here rather than spread the condition through every
        # status mutation site.
        runner._quiet_since = None
        runner._stop_requested = False
        # Bump updated_at the moment the runner starts work so the
        # sidebar floats this session to the top immediately — not
        # after MessageComplete lands. Covers the replay-path too:
        # `_Replay` skips `insert_message`, so without this touch the
        # sort wouldn't move on a resumed orphan prompt. DB hiccup
        # here must not abort the turn — swallow.
        try:
            await store.touch_session(runner.db, runner.session_id)
        except aiosqlite.Error:
            log.exception(
                "runner %s: touch_session on turn-start failed",
                runner.session_id,
            )
        # Phase-2 broadcast: every connected sidebar sees the
        # updated_at bump + the running badge without waiting for the
        # poll tick. Publish AFTER touch_session so the upsert payload
        # carries the bumped timestamp.
        await publish_session_upsert(runner._sessions_broker, runner.db, runner.session_id)
        runner._publish_runner_state()
        turn_ok = False
        try:
            await execute_turn(
                runner,
                prompt,
                persist_user=persist_user,
                attachments=attachments,
            )
            turn_ok = True
        except Exception as exc:
            log.exception("runner %s: turn failed", runner.session_id)
            await runner._emit_event(ErrorEvent(session_id=runner.session_id, message=str(exc)))
            # Latch the red-flashing error state onto the session row
            # so the sidebar surfaces the crash without the user
            # having to open the conversation to find it. Cleared on
            # the next successful MessageComplete by the `execute_turn`
            # path below, or implicitly by a subsequent successful
            # turn in this same loop. Swallow DB errors — missing the
            # latch just means the sidebar indicator doesn't light,
            # which is a worse UX than the current (non-existent)
            # state but not a data loss.
            try:
                await store.set_session_error_pending(runner.db, runner.session_id, pending=True)
            except aiosqlite.Error:
                log.exception(
                    "runner %s: failed to latch error_pending",
                    runner.session_id,
                )
        finally:
            runner._status = "idle"
            # If nobody's watching, start the reaper clock. A connected
            # subscriber keeps the clock off until it unsubscribes.
            if not runner._subscribers:
                runner._quiet_since = time.monotonic()
            # A clean turn clears any stale error_pending latched by an
            # earlier crash on this session — the red dot disappears
            # the moment the user's retry lands a successful reply.
            # Kept inside the finally so an exception-free turn still
            # gets the clear before we broadcast the idle upsert.
            if turn_ok:
                try:
                    await store.set_session_error_pending(
                        runner.db, runner.session_id, pending=False
                    )
                except aiosqlite.Error:
                    log.exception(
                        "runner %s: failed to clear error_pending",
                        runner.session_id,
                    )
            # Broadcast idle so the sidebar clears the running ping
            # and picks up any cost / message_count / completed bumps
            # (plus the error_pending transition above) from
            # `persist_assistant_turn` in one upsert.
            await publish_session_upsert(runner._sessions_broker, runner.db, runner.session_id)
            runner._publish_runner_state()


async def execute_turn(  # noqa: C901
    runner: SessionRunner,
    prompt: str,
    *,
    persist_user: bool = True,
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    """Run one agent turn end-to-end. Mirrors the pre-runner ws_agent
    loop: persist user message, stream agent events, persist assistant
    turn + tool calls as they complete. Events are fanned out to
    subscribers via `runner._emit_event`.

    `persist_user=False` is used by the runner-boot replay path when
    recovering an orphaned prompt: the user row is already in
    `messages` from the original (interrupted) turn, so inserting
    again would duplicate history.

    `attachments` carries the composer's `[File N]` sidecar (parsed
    list or None). When present, the SDK receives the same prompt
    with tokens replaced by absolute paths; the persisted user row
    keeps the tokenised form so the transcript renders chips on
    reload. Replay path sends the same list through so the recovered
    turn hits the SDK identically to its original.
    """
    pruned_attachments, attachments_json = prune_and_serialize(prompt, attachments or [])
    # The SDK only ever sees the substituted text; we don't substitute
    # in-place on `prompt` because we want to persist the tokenised
    # form (and we need `prompt` unchanged for the replay-row content
    # column, which is already tokenised).
    agent_prompt = substitute_tokens(prompt, pruned_attachments)
    if persist_user:
        await store.insert_message(
            runner.db,
            session_id=runner.session_id,
            role="user",
            content=prompt,
            attachments=attachments_json,
        )
        metrics.messages_persisted.labels(role="user").inc()
    # Intentionally not emitting a `user_message` event here. The
    # frontend pushes the user message optimistically on submit, and a
    # second client that subscribes while the turn is in flight will
    # catch up via `GET /messages` on session load — the ring buffer
    # only needs to carry *streamed* output.

    buf: list[str] = []
    thinking_buf: list[str] = []
    tool_call_ids: list[str] = []
    current_message_id: str | None = None
    persisted = False
    stopped = False

    try:
        async for event in runner.agent.stream(agent_prompt):
            await runner._emit_event(event)
            if isinstance(event, MessageStart):
                current_message_id = event.message_id
            elif isinstance(event, Token):
                buf.append(event.text)
            elif isinstance(event, Thinking):
                thinking_buf.append(event.text)
            elif isinstance(event, ToolCallStart):
                await store.insert_tool_call_start(
                    runner.db,
                    session_id=runner.session_id,
                    tool_call_id=event.tool_call_id,
                    name=event.name,
                    input_json=json.dumps(event.input),
                )
                tool_call_ids.append(event.tool_call_id)
                metrics.tool_calls_started.inc()
                # Start the keepalive ticker for this call. See
                # `progress_ticker.ProgressTickerManager._ticker` for
                # the fan-out contract; the ticker is torn down in the
                # `ToolCallEnd` arm or by `stop_all` on turn teardown.
                runner._progress.start(event.tool_call_id)
                # TodoWrite is a first-class UI signal, not just a
                # generic tool call: fire a higher-level
                # `TodoWriteUpdate` so the frontend sticky widget
                # updates without hand-parsing `tool_calls[*].input`.
                # The raw `ToolCallStart` already went out above, so
                # Inspector / audit paths keep seeing it verbatim.
                if event.name == "TodoWrite":
                    await _emit_todo_write_update(runner, event.input)
            elif isinstance(event, ToolOutputDelta):
                # Buffer the chunk instead of writing immediately. The
                # coalescer flushes on count/time thresholds so a
                # chatty tool doesn't cost one UPDATE + commit per
                # delta. History endpoint + reconnecting WebSocket
                # see cumulative output within one flush window of
                # the live stream. `finish_tool_call` later overwrites
                # with the canonical final string, so a dropped flush
                # can't leave a permanent gap.
                await runner._coalescer.buffer(event.tool_call_id, event.delta)
            elif isinstance(event, ToolCallEnd):
                # Stop the keepalive ticker first so a stray tick
                # can't race the canonical end frame onto the wire.
                runner._progress.stop(event.tool_call_id)
                # Drop any buffered deltas before writing the
                # canonical output — `finish_tool_call` fully
                # overwrites `output` so the buffered chunks would be
                # clobbered anyway. Doing it in this order also
                # prevents a late timer from racing past the canonical
                # write.
                runner._coalescer.drop(event.tool_call_id)
                await store.finish_tool_call(
                    runner.db,
                    tool_call_id=event.tool_call_id,
                    output=event.output,
                    error=event.error,
                )
                metrics.tool_calls_finished.labels(ok=str(event.ok).lower()).inc()
            elif isinstance(event, ContextUsage):
                # Persist the latest snapshot on the session row so a
                # fresh page load / reconnect has a number to paint
                # before the next turn's live event arrives. Failure
                # here must not drop the event for live subscribers —
                # the fan-out to `_emit_event` already happened at the
                # top of the loop. Swallow DB errors quietly.
                try:
                    await store.set_session_context_usage(
                        runner.db,
                        runner.session_id,
                        pct=event.percentage,
                        tokens=event.total_tokens,
                        max_tokens=event.max_tokens,
                    )
                except aiosqlite.Error:
                    log.exception(
                        "runner %s: failed to persist context usage",
                        runner.session_id,
                    )
            elif isinstance(event, MessageComplete):
                await persist_assistant_turn(
                    runner.db,
                    session_id=runner.session_id,
                    message_id=event.message_id,
                    content="".join(buf),
                    thinking="".join(thinking_buf) or None,
                    tool_call_ids=tool_call_ids,
                    cost_usd=event.cost_usd,
                    input_tokens=event.input_tokens,
                    output_tokens=event.output_tokens,
                    cache_read_tokens=event.cache_read_tokens,
                    cache_creation_tokens=event.cache_creation_tokens,
                )
                if runner.agent.sdk_session_id is not None:
                    await store.set_sdk_session_id(
                        runner.db, runner.session_id, runner.agent.sdk_session_id
                    )
                persisted = True
                break

            if runner._stop_requested:
                stopped = True
                try:
                    await runner.agent.interrupt()
                except (ClaudeSDKError, OSError):
                    pass
                break
    finally:
        # Flush any buffered tool-output deltas on every exit path
        # (normal completion, stop-requested break, or an exception
        # bubbling out of the stream). If a `ToolCallEnd` arrives
        # later — e.g. after a reconnecting turn — the canonical
        # output still overwrites; this just keeps mid-stream
        # progress visible for the interrupted case.
        await runner._coalescer.flush_all()
        # Cancel any in-flight progress tickers. Normal completion
        # cancels each one in the `ToolCallEnd` arm; this guards the
        # stop / exception paths where tools were still running when
        # the turn exited.
        await runner._progress.stop_all()

    if stopped and not persisted:
        msg_id = current_message_id or uuid4().hex
        synthetic = MessageComplete(session_id=runner.session_id, message_id=msg_id, cost_usd=None)
        await runner._emit_event(synthetic)
        await persist_assistant_turn(
            runner.db,
            session_id=runner.session_id,
            message_id=msg_id,
            content="".join(buf),
            thinking="".join(thinking_buf) or None,
            tool_call_ids=tool_call_ids,
            cost_usd=None,
        )


async def _emit_todo_write_update(runner: SessionRunner, tool_input: dict[str, Any]) -> None:
    """Translate a raw `TodoWrite` tool input into a `TodoWriteUpdate`
    event and fan it out through `runner._emit_event`.

    Tolerant of malformed payloads: if the SDK (or a future schema
    bump) sends something we can't parse, we log at warning and skip
    the emit rather than fail the turn. The underlying
    `tool_call_start` already landed — subscribers still have the raw
    version via the Inspector pane, so "live widget doesn't update"
    is recoverable; "turn crashes on unexpected shape" is not."""
    try:
        update = TodoWriteUpdate.model_validate({"session_id": runner.session_id, **tool_input})
    except Exception as exc:  # noqa: BLE001 — intentional broad catch
        log.warning(
            "todo_write_update parse failed for session %s: %s",
            runner.session_id,
            exc,
        )
        return
    await runner._emit_event(update)
