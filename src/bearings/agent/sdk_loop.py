# mypy: disable-error-code=explicit-any
"""Per-session SDK worker loop — drains the prompt queue, runs the SDK
turn, translates SDK frames into wire-side AgentEvents.

Per Slice A1 of ``~/.claude/plans/wiring-agent-loop.md``: this is the
glue that bridges the prompt-queue surface (item 1.7) to a live
:class:`claude_agent_sdk.ClaudeSDKClient`. Per sign-off Q1 (accepted
2026-05-01) the SDK client is **persistent per session** — held open
across many turns via a single ``async with`` so the SDK doesn't
re-upload the system prompt + reseed context on every prompt.

Lifecycle (the supervisor in ``web/runner_factory.py``, item A1.3,
owns the asyncio.Task carrying this coroutine):

1. The runner-factory's first lookup for a session id materialises a
   :class:`SessionRunner` AND spawns
   ``asyncio.create_task(run_session_loop(...))``. The task captures
   the runner + session + composed options.
2. ``run_session_loop`` enters ``async with ClaudeSDKClient(options)``;
   the SDK spawns its CLI subprocess. Per sign-off Q2, one subprocess
   per session — the SDK default.
3. Inner loop: ``pop_next_prompt()`` → if ``None`` await
   ``runner.new_prompt_event``; else translate one full turn end-to-end.
4. Per turn: emit :class:`UserMessage` event (so subscribers see the
   bubble immediately), ``client.query(content)``, consume
   ``client.receive_response()``, translate each SDK message via
   :class:`SDKEventTranslator` and emit, persist the assistant row.
5. On any uncaught :class:`Exception`, transition the session to
   ``ERROR``, emit :class:`ErrorEvent(fatal=True)`, return cleanly
   (no auto-retry per sign-off Q7). The supervisor sees the task
   complete and updates its bookkeeping; the user clicks "Recover" to
   transition back to ``RUNNING``.

The worker does NOT own the prompt-row persistence (that's the route
handler's job in ``prompt_dispatch.py``). It owns the assistant-row
persistence at end-of-turn — calls
:func:`bearings.agent.persistence.persist_assistant_turn` with the
canonical body + ``ResultMessage.model_usage`` for the spec §5
columns.

References:

* ``docs/architecture-v1.md`` §1.1.4 — module home; arch §3.1 layer
  rules forbid imports from ``bearings.web``.
* ``docs/behavior/chat.md`` §"The agent loop start/stop semantics" —
  long-idle teardown is server-side transparent (the supervisor
  re-spawns on next prompt).
* ``docs/behavior/prompt-endpoint.md`` §"What the user sees in the
  UI when they POST during an in-flight turn" — FIFO per-session
  ordering; queue while turn is running.
"""

from __future__ import annotations

import contextlib
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage

from bearings.agent.events import ErrorEvent, UserMessage
from bearings.agent.options import OptionsKwargs
from bearings.agent.persistence import (
    MessagePersistence,
    persist_assistant_turn,
)
from bearings.agent.runner import (
    QueuedPrompt,
    RunnerStatus,
    SessionRunner,
)
from bearings.agent.session import (
    AgentSession,
    SessionState,
    SessionStateError,
)
from bearings.agent.translate import SDKEventTranslator


async def run_session_loop(
    runner: SessionRunner,
    session: AgentSession,
    options_kwargs: OptionsKwargs,
    *,
    persist: MessagePersistence | None = None,
    client_factory: Any = None,
) -> None:
    """Run the SDK worker loop until the supervisor cancels.

    Args:
        runner: The per-session :class:`SessionRunner` carrying the
            prompt queue + ring buffer + subscribers.
        session: The :class:`AgentSession` carrying the lifecycle
            state machine + SDK client attach point.
        options_kwargs: Fully-composed :class:`OptionsKwargs` from
            :func:`bearings.agent.options.compose_session_options`
            (system_prompt + cwd + mcp_servers + permission_mode + …).
        persist: Optional override for the assistant-row persistence
            callable. Defaults to
            :func:`bearings.agent.persistence.persist_assistant_turn`.
            Tests pass a fake to assert on the persistence call without
            a live DB.
        client_factory: Optional override for the
            :class:`ClaudeSDKClient` constructor. Tests pass a fake
            class implementing the same async-context-manager + query
            + receive_response surface; production uses the SDK default.
    """
    persist_fn: MessagePersistence = persist if persist is not None else persist_assistant_turn
    # ``client_factory`` is typed as ``Any`` because tests pass a duck-
    # typed FakeSDKClient that exposes the same async-cm + query +
    # receive_response surface but does not subclass ClaudeSDKClient.
    # The production default is the SDK class itself.
    factory = client_factory if client_factory is not None else ClaudeSDKClient
    sdk_options = _to_sdk_options(options_kwargs)
    decision = session.config.decision
    translator = SDKEventTranslator(session.config.session_id, decision)
    try:
        async with factory(options=sdk_options) as client:
            session.attach_sdk_client(client)
            try:
                if session.state is SessionState.INITIALIZING:
                    await session.start()
                await _drain_prompt_queue(runner, session, client, translator, persist_fn)
            finally:
                session.detach_sdk_client()
    except _CancelledLike:
        # Supervisor asked us to stop (idle-reap or app shutdown). Let
        # the cancellation propagate so the supervisor's await on the
        # task surfaces it normally; do not transition to ERROR.
        raise
    except Exception as exc:  # pragma: no cover — exercised by integration tests
        # Per sign-off Q7: ERROR + emit + stop, no auto-retry. The
        # supervisor sees the task end normally; the user clicks
        # "Recover" to call session.recover() and re-spawn the loop.
        await _enter_error_state(runner, session, exc)
        return


async def _drain_prompt_queue(
    runner: SessionRunner,
    session: AgentSession,
    client: ClaudeSDKClient,
    translator: SDKEventTranslator,
    persist_fn: MessagePersistence,
) -> None:
    """Inner pump: pop a prompt → run a turn → repeat. Awaits the
    new-prompt event when the queue is empty."""
    while True:
        prompt = runner.pop_next_prompt()
        if prompt is None:
            # Idle — surface as awaiting-user in the status snapshot so
            # the inspector pressure-bar shows the session at rest.
            runner.set_status(
                RunnerStatus(
                    is_running=False,
                    is_awaiting_user=True,
                    routing_decision=session.config.decision,
                )
            )
            await runner.new_prompt_event.wait()
            continue
        await _run_one_turn(runner, session, client, translator, persist_fn, prompt)


async def _run_one_turn(
    runner: SessionRunner,
    session: AgentSession,
    client: ClaudeSDKClient,
    translator: SDKEventTranslator,
    persist_fn: MessagePersistence,
    prompt: QueuedPrompt,
) -> None:
    """Drive one full SDK turn end-to-end."""
    translator.begin_turn()
    runner.set_status(
        RunnerStatus(
            is_running=True,
            is_awaiting_user=False,
            routing_decision=session.config.decision,
        )
    )
    # User-message event so subscribers that hydrate from the conversation
    # store see the bubble immediately, even before the SDK starts
    # producing output. The DB-side row was already inserted by the
    # prompt-endpoint route handler (prompt_dispatch.py); this is the
    # wire-side echo for live subscribers.
    await runner.emit(
        UserMessage(
            session_id=session.config.session_id,
            message_id=prompt.message_id,
            content=prompt.content,
        )
    )
    await client.query(prompt.content, session_id=session.config.session_id)
    last_result: ResultMessage | None = None
    async for sdk_msg in client.receive_response():
        if isinstance(sdk_msg, ResultMessage):
            last_result = sdk_msg
        for event in translator.feed(sdk_msg):
            await runner.emit(event)
    # Persist the assistant row. Skipped when the turn produced no
    # body (rare: would mean a tool-only turn that the SDK terminated
    # without an assistant message — already surfaced as ErrorEvent
    # by the translator).
    db = session.config.db
    body = translator.final_body()
    if db is not None and translator.message_id is not None and body:
        await persist_fn(
            db,
            session_id=session.config.session_id,
            content=body,
            decision=session.config.decision,
            model_usage=last_result.model_usage if last_result is not None else None,
        )


async def _enter_error_state(
    runner: SessionRunner,
    session: AgentSession,
    exc: BaseException,
) -> None:
    """Transition the session to ERROR + fan out a fatal ErrorEvent.

    Defensive against the session already being in a terminal state
    (e.g. close() raced with a fatal SDK error) — silently absorb the
    SessionStateError so we still emit the wire frame for any live
    subscriber.
    """
    with contextlib.suppress(SessionStateError):
        await session.mark_error(str(exc))
    await runner.emit(
        ErrorEvent(
            session_id=session.config.session_id,
            message=f"agent loop error: {exc}",
            fatal=True,
        )
    )


def _to_sdk_options(kwargs: OptionsKwargs) -> ClaudeAgentOptions:
    """Splat :class:`OptionsKwargs` onto :class:`ClaudeAgentOptions`.

    Only the SDK-known fields ride through; the routing-shift surplus
    (``advisor_max_uses``, Bearings-side subagent enforcement) stays
    on the carrier for runtime consumers that need it but does not
    flow to the SDK constructor.

    Empty / None safe-defaults are mapped per the SDK shape:

    * ``system_prompt=""`` → ``None`` (let the SDK pick).
    * ``cwd=""`` → ``None``.
    * ``permission_mode=""`` → ``None``.
    * ``setting_sources=None`` → ``None``.
    """
    # ``fallback_model`` is dropped when it matches ``model`` because the
    # SDK CLI rejects identical pairs ("Fallback model cannot be the
    # same as the main model"). The bearings ``EXECUTOR_FALLBACK_MODEL``
    # table encodes "haiku has no further fallback" by mapping
    # ``haiku → haiku``; that semantic survives by simply omitting the
    # SDK option (SDK then runs without a fallback override).
    sdk_kwargs: dict[str, Any] = {
        "model": kwargs.model,
        "betas": list(kwargs.betas),
        "include_partial_messages": kwargs.include_partial_messages,
        "allowed_tools": list(kwargs.allowed_tools),
        "disallowed_tools": list(kwargs.disallowed_tools),
        "mcp_servers": dict(kwargs.mcp_servers),
        "max_budget_usd": kwargs.max_budget_usd,
        "can_use_tool": kwargs.can_use_tool,
    }
    if kwargs.fallback_model and kwargs.fallback_model != kwargs.model:
        sdk_kwargs["fallback_model"] = kwargs.fallback_model
    if kwargs.effort is not None:
        sdk_kwargs["effort"] = kwargs.effort
    if kwargs.system_prompt:
        sdk_kwargs["system_prompt"] = kwargs.system_prompt
    if kwargs.cwd:
        sdk_kwargs["cwd"] = kwargs.cwd
    if kwargs.permission_mode:
        sdk_kwargs["permission_mode"] = kwargs.permission_mode
    if kwargs.setting_sources is not None:
        sdk_kwargs["setting_sources"] = list(kwargs.setting_sources)
    if kwargs.hooks:
        sdk_kwargs["hooks"] = dict(kwargs.hooks)
    return ClaudeAgentOptions(**sdk_kwargs)


# ``BaseException`` covers both :class:`asyncio.CancelledError` (which
# inherits from ``BaseException``, not ``Exception``) and
# :class:`KeyboardInterrupt`. We only want to bubble cancellation; the
# rest of the exception hierarchy lands in the ``except Exception``
# arm above. Naming it as a tuple lets the ``except`` arm stay one
# line.
import asyncio as _asyncio_mod  # noqa: E402  — kept below the public surface

_CancelledLike: tuple[type[BaseException], ...] = (_asyncio_mod.CancelledError,)


__all__ = [
    "run_session_loop",
]
