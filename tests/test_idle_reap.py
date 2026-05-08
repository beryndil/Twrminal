# mypy: disable-error-code=explicit-any
"""Tests for the idle-reap policy in ``InProcessRunnerRegistry``.

Per Slice A5 of ``~/.claude/plans/wiring-agent-loop.md`` and
sign-off Q3 (accepted 2026-05-01): a session whose runner has had
zero subscribers AND zero queued prompts past the idle threshold
gets its supervisor task cancelled so the SDK CLI subprocess
closes. Next prompt POST re-spawns transparently.

Tests inject very-short threshold + poll values so the reap
happens within a sub-second test budget.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import ClassVar

import aiosqlite
import pytest
from claude_agent_sdk import Message

from bearings.agent.bearings_mcp import (
    BearingsMcpDeps,
    CloseSessionDeps,
    build_bearings_mcp_server,
)
from bearings.agent.options import (
    OptionsKwargs,
    compose_session_options,
)
from bearings.agent.routing import RoutingDecision
from bearings.agent.runner import SessionSetup
from bearings.agent.session import AgentSession, SessionConfig
from bearings.config.constants import SESSION_KIND_CHAT
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema
from bearings.web.runner_factory import InProcessRunnerRegistry


class _FakeSDKClient:
    """Async-cm + query + receive_response stub. Never produces
    messages so the worker idles after spawn."""

    instances: ClassVar[list[_FakeSDKClient]] = []

    def __init__(self, *, options: object) -> None:
        self.options = options
        _FakeSDKClient.instances.append(self)

    async def __aenter__(self) -> _FakeSDKClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def query(self, prompt: str, session_id: str = "default") -> None:
        return None

    async def receive_response(self) -> AsyncIterator[Message]:
        empty: list[Message] = []
        for msg in empty:
            yield msg


@pytest.fixture(autouse=True)
def _reset() -> None:
    _FakeSDKClient.instances = []


@pytest.fixture
async def conn(tmp_path: Path):
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as connection:
        await load_schema(connection)
        yield connection


def _decision() -> RoutingDecision:
    return RoutingDecision(
        executor_model="sonnet",
        advisor_model=None,
        advisor_max_uses=0,
        effort_level="medium",
        source="default",
        reason="test",
        matched_rule_id=None,
    )


def _options() -> OptionsKwargs:
    server = build_bearings_mcp_server(
        BearingsMcpDeps.minimal(CloseSessionDeps(session_id="ses_x", db_factory=_unused_factory()))
    )
    return compose_session_options(
        decision=_decision(),
        session_instructions=None,
        working_dir="/tmp/wd",
        permission_profile="standard",
        permission_mode_override=None,
        setting_sources=None,
        max_budget_usd=None,
        bearings_mcp_server=server,
    )


def _build_setup_for(conn: aiosqlite.Connection, session_id: str) -> SessionSetup:
    config = SessionConfig(
        session_id=session_id,
        working_dir="/tmp/wd",
        decision=_decision(),
        db=conn,
    )
    return SessionSetup(session=AgentSession(config), options=_options())


def _stub_sdk_loop_with_event(
    factory_mod,
    cleanup_event: asyncio.Event,
):
    """Replace run_session_loop with a stub that waits forever, then
    sets ``cleanup_event`` on cancellation. Returns the original so
    the caller can restore."""
    original = factory_mod.run_session_loop

    async def stub(
        runner: object,
        session: object,
        options_kwargs: object,
    ) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup_event.set()
            raise

    factory_mod.run_session_loop = stub
    return original


# ---------------------------------------------------------------------------
# Reap policy
# ---------------------------------------------------------------------------


async def test_idle_session_is_reaped_after_threshold(
    conn: aiosqlite.Connection,
) -> None:
    """A session with no subscribers and no queued prompts gets its
    supervisor cancelled after the threshold elapses."""
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp/wd", model="sonnet"
    )

    async def setup(session_id: str, runner: object) -> SessionSetup | None:
        return _build_setup_for(conn, session_id) if session_id == session_row.id else None

    import bearings.web.runner_factory as factory_mod

    cleanup = asyncio.Event()
    original = _stub_sdk_loop_with_event(factory_mod, cleanup)
    try:
        # Aggressive timings so the test runs in well under a second.
        factory = InProcessRunnerRegistry(
            session_setup=setup,
            idle_reap_threshold_s=0.05,
            idle_reap_poll_interval_s=0.02,
        )
        factory.start_reaper()
        await factory(session_row.id)
        # Yield a tick so the supervisor starts.
        await asyncio.sleep(0)
        assert factory.get_supervisor(session_row.id) is not None
        # Wait for the reaper to fire — threshold + a few poll
        # cycles. cleanup event is set inside the supervisor stub
        # when it observes its cancellation.
        try:
            await asyncio.wait_for(cleanup.wait(), timeout=1.0)
        except TimeoutError as exc:  # pragma: no cover
            raise AssertionError("reaper did not cancel the supervisor in time") from exc
        # Supervisor task is reaped from the registry; runner stays
        # so post-reap subscribers can still see the ring buffer.
        assert factory.get_supervisor(session_row.id) is None
        assert factory.get(session_row.id) is not None
    finally:
        factory_mod.run_session_loop = original  # type: ignore[attr-defined]
        await factory.aclose()


async def test_session_with_subscribers_is_not_reaped(
    conn: aiosqlite.Connection,
) -> None:
    """A live WS subscriber prevents reaping."""
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonnet"
    )

    async def setup(session_id: str, runner: object) -> SessionSetup | None:
        return _build_setup_for(conn, session_id)

    import bearings.web.runner_factory as factory_mod

    cleanup = asyncio.Event()
    original = _stub_sdk_loop_with_event(factory_mod, cleanup)
    try:
        factory = InProcessRunnerRegistry(
            session_setup=setup,
            idle_reap_threshold_s=0.05,
            idle_reap_poll_interval_s=0.02,
        )
        factory.start_reaper()
        runner = await factory(session_row.id)
        await asyncio.sleep(0)
        # Attach a subscriber. Subscribe also bumps last_active_ns so
        # the reaper's age check is reset.
        _, queue = runner.subscribe(since_seq=0)
        # Wait long enough for several reap polls; subscriber blocks
        # the reap.
        await asyncio.sleep(0.2)
        assert not cleanup.is_set()
        assert factory.get_supervisor(session_row.id) is not None
        runner.unsubscribe(queue)
    finally:
        factory_mod.run_session_loop = original  # type: ignore[attr-defined]
        await factory.aclose()


async def test_session_with_queued_prompts_is_not_reaped(
    conn: aiosqlite.Connection,
) -> None:
    """A queued prompt blocks reap (the worker has work to do)."""
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonnet"
    )

    async def setup(session_id: str, runner: object) -> SessionSetup | None:
        return _build_setup_for(conn, session_id)

    import bearings.web.runner_factory as factory_mod

    cleanup = asyncio.Event()
    original = _stub_sdk_loop_with_event(factory_mod, cleanup)
    try:
        factory = InProcessRunnerRegistry(
            session_setup=setup,
            idle_reap_threshold_s=0.05,
            idle_reap_poll_interval_s=0.02,
        )
        factory.start_reaper()
        runner = await factory(session_row.id)
        await asyncio.sleep(0)
        runner.enqueue_prompt(message_id="m1", content="hello")
        await asyncio.sleep(0.2)
        assert not cleanup.is_set()
    finally:
        factory_mod.run_session_loop = original  # type: ignore[attr-defined]
        await factory.aclose()


async def test_aclose_stops_reaper_task(
    conn: aiosqlite.Connection,
) -> None:
    """``aclose()`` cancels the reaper alongside supervisors."""
    factory = InProcessRunnerRegistry()
    factory.start_reaper()
    await asyncio.sleep(0)
    assert factory._reaper_task is not None
    await factory.aclose()
    assert factory._reaper_task is None


async def test_start_reaper_is_idempotent() -> None:
    """Calling ``start_reaper()`` twice does not spawn a second
    task — the first one is reused."""
    factory = InProcessRunnerRegistry(
        idle_reap_threshold_s=0.05,
        idle_reap_poll_interval_s=0.02,
    )
    factory.start_reaper()
    first_task = factory._reaper_task
    factory.start_reaper()
    second_task = factory._reaper_task
    assert first_task is second_task
    await factory.aclose()


async def test_reaped_session_re_spawns_on_next_call(
    conn: aiosqlite.Connection,
) -> None:
    """After reap, a fresh ``factory(session_id)`` re-materialises
    the runner + supervisor (long-idle teardown is server-side
    transparent per behavior doc)."""
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonnet"
    )

    async def setup(session_id: str, runner: object) -> SessionSetup | None:
        return _build_setup_for(conn, session_id) if session_id == session_row.id else None

    import bearings.web.runner_factory as factory_mod

    cleanup = asyncio.Event()
    original = _stub_sdk_loop_with_event(factory_mod, cleanup)
    try:
        factory = InProcessRunnerRegistry(
            session_setup=setup,
            idle_reap_threshold_s=0.05,
            idle_reap_poll_interval_s=0.02,
        )
        factory.start_reaper()
        await factory(session_row.id)
        await asyncio.sleep(0)
        await asyncio.wait_for(cleanup.wait(), timeout=1.0)
        assert factory.get_supervisor(session_row.id) is None

        # Reset cleanup for the second spawn so we can verify it
        # spawned a fresh supervisor.
        cleanup.clear()
        # Second call after reap. The runner is sticky (still in
        # the registry); the supervisor is fresh.
        await factory(session_row.id)
        await asyncio.sleep(0)
        assert factory.get_supervisor(session_row.id) is not None
    finally:
        factory_mod.run_session_loop = original  # type: ignore[attr-defined]
        await factory.aclose()


def _unused_factory() -> Callable[[], Awaitable[aiosqlite.Connection]]:
    async def _never() -> aiosqlite.Connection:  # pragma: no cover
        raise AssertionError("idle-reap test should not invoke close_session DB factory")

    return _never
