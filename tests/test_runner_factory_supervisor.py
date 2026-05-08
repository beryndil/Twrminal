# mypy: disable-error-code=explicit-any
"""Tests for ``InProcessRunnerRegistry``'s worker-loop supervisor.

Per Slice A1.3 of ``~/.claude/plans/wiring-agent-loop.md``: when the
factory is wired with a ``session_setup`` callable, every first-touch
``__call__`` materialises a fresh runner AND spawns
:func:`bearings.agent.sdk_loop.run_session_loop` as the supervisor
task. ``aclose()`` cancels and awaits every supervisor.
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
from bearings.web.runner_factory import (
    InProcessRunnerRegistry,
    build_in_process_factory,
)


class _FakeSDKClient:
    """Same shape as the SDK client; never produces messages so the
    worker just sits in the idle ``await new_prompt_event`` loop."""

    instances: ClassVar[list[_FakeSDKClient]] = []

    def __init__(self, *, options: object) -> None:
        self.options = options
        self.entered = False
        self.exited = False
        _FakeSDKClient.instances.append(self)

    async def __aenter__(self) -> _FakeSDKClient:
        self.entered = True
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.exited = True

    async def query(self, prompt: str, session_id: str = "default") -> None:
        return None

    async def receive_response(self) -> AsyncIterator[Message]:
        # Empty generator — yields no messages so the worker reaches
        # its idle await on new_prompt_event. The empty-list iter
        # keeps the function shaped as an async generator (yield
        # statement present); vulture sees no unreachable code; mypy
        # sees the yield as conditional rather than unconditional.
        empty: list[Message] = []
        for msg in empty:
            yield msg


@pytest.fixture(autouse=True)
def _reset_clients() -> None:
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
        BearingsMcpDeps.minimal(
            CloseSessionDeps(
                session_id="ses_x",
                db_factory=_unused_factory(),
            )
        )
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


# ---------------------------------------------------------------------------
# No-setup path — the existing tests' ring-buffer-only contract
# ---------------------------------------------------------------------------


async def test_factory_without_setup_returns_runner_and_no_supervisor() -> None:
    """Backwards compat: ``InProcessRunnerRegistry()`` with no setup
    works as before — runner returned, no supervisor task spawned."""
    factory = InProcessRunnerRegistry()
    runner = await factory("ses_a")
    assert runner.session_id == "ses_a"
    # No supervisor was spawned because no session_setup was provided.
    assert factory.get_supervisor("ses_a") is None


async def test_factory_returns_same_runner_on_repeat_calls() -> None:
    """Stickiness: second call returns the same SessionRunner."""
    factory = InProcessRunnerRegistry()
    first = await factory("ses_b")
    second = await factory("ses_b")
    assert first is second


# ---------------------------------------------------------------------------
# With-setup path — the production supervisor lifecycle
# ---------------------------------------------------------------------------


async def test_factory_spawns_supervisor_on_first_call(
    conn: aiosqlite.Connection,
) -> None:
    """When ``session_setup`` is wired, first-touch spawns
    ``run_session_loop`` as a supervisor task."""
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp/wd", model="sonnet"
    )

    async def setup(session_id: str, runner: object) -> SessionSetup | None:
        if session_id != session_row.id:
            return None
        return _build_setup_for(conn, session_id)

    # Inject the FakeSDKClient via the sdk_loop module path; the
    # supervisor's run_session_loop call uses the production default,
    # which we monkey-patch here via the client_factory parameter on
    # the run_session_loop callable. Cleanest: stub run_session_loop.
    import bearings.web.runner_factory as factory_mod

    original = factory_mod.run_session_loop  # type: ignore[attr-defined]

    async def stub_run_session_loop(
        runner: object,
        session: object,
        options_kwargs: object,
    ) -> None:
        # Wait forever so the supervisor stays alive until aclose
        # cancels it.
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise

    factory_mod.run_session_loop = stub_run_session_loop  # type: ignore[assignment, attr-defined]
    try:
        factory = InProcessRunnerRegistry(session_setup=setup)
        runner = await factory(session_row.id)
        assert runner.session_id == session_row.id
        # Yield once so the supervisor task starts running.
        await asyncio.sleep(0)
        task = factory.get_supervisor(session_row.id)
        assert task is not None
        assert not task.done()
    finally:
        factory_mod.run_session_loop = original  # type: ignore[attr-defined]
        await factory.aclose()


async def test_factory_skips_supervisor_when_setup_returns_none(
    conn: aiosqlite.Connection,
) -> None:
    """If the setup callable returns None (session row missing), the
    runner still materialises but no supervisor is spawned."""

    async def setup(session_id: str, runner: object) -> SessionSetup | None:
        return None

    factory = InProcessRunnerRegistry(session_setup=setup)
    runner = await factory("ses_missing")
    assert runner.session_id == "ses_missing"
    assert factory.get_supervisor("ses_missing") is None


async def test_aclose_cancels_supervisor_tasks(
    conn: aiosqlite.Connection,
) -> None:
    """``aclose()`` cancels every supervisor + awaits its teardown."""
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp/wd", model="sonnet"
    )

    async def setup(session_id: str, runner: object) -> SessionSetup | None:
        return _build_setup_for(conn, session_id) if session_id == session_row.id else None

    import bearings.web.runner_factory as factory_mod

    original = factory_mod.run_session_loop  # type: ignore[attr-defined]
    cleanup_recorded = asyncio.Event()

    async def stub_run_session_loop(
        runner: object,
        session: object,
        options_kwargs: object,
    ) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup_recorded.set()
            raise

    factory_mod.run_session_loop = stub_run_session_loop  # type: ignore[assignment, attr-defined]
    try:
        factory = InProcessRunnerRegistry(session_setup=setup)
        await factory(session_row.id)
        await asyncio.sleep(0)  # let supervisor task start
        await factory.aclose()
        # The supervisor saw cancellation.
        assert cleanup_recorded.is_set()
        # Supervisor task was reaped from the registry — but the
        # runner stays so post-shutdown ring-buffer reads still work.
        assert factory.get_supervisor(session_row.id) is None
        assert factory.get(session_row.id) is not None
    finally:
        factory_mod.run_session_loop = original  # type: ignore[attr-defined]


async def test_aclose_is_idempotent() -> None:
    """Calling ``aclose()`` twice does not raise."""
    factory = InProcessRunnerRegistry()
    await factory.aclose()
    await factory.aclose()


async def test_recycle_cancels_supervisor_keeps_runner(
    conn: aiosqlite.Connection,
) -> None:
    """``recycle()`` cancels + reaps the live supervisor but leaves
    the runner registered so the ring buffer (and any in-flight
    subscribers) survive — exactly the semantic the
    ``PATCH /api/sessions/{id}/model`` route needs so the next prompt
    respawns with the freshly-persisted model.
    """
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp/wd", model="sonnet"
    )

    async def setup(session_id: str, runner: object) -> SessionSetup | None:
        return _build_setup_for(conn, session_id) if session_id == session_row.id else None

    import bearings.web.runner_factory as factory_mod

    original = factory_mod.run_session_loop  # type: ignore[attr-defined]
    cleanup_recorded = asyncio.Event()

    async def stub_run_session_loop(
        runner: object,
        session: object,
        options_kwargs: object,
    ) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup_recorded.set()
            raise

    factory_mod.run_session_loop = stub_run_session_loop  # type: ignore[assignment, attr-defined]
    try:
        factory = InProcessRunnerRegistry(session_setup=setup)
        await factory(session_row.id)
        await asyncio.sleep(0)  # let supervisor task start
        assert factory.get_supervisor(session_row.id) is not None

        had_supervisor = await factory.recycle(session_row.id)
        assert had_supervisor is True
        # The supervisor task observed cancellation and exited.
        assert cleanup_recorded.is_set()
        # Supervisor handle gone, runner remains so ring-buffer reads
        # (replays for clients that were subscribed before the
        # recycle) keep working.
        assert factory.get_supervisor(session_row.id) is None
        assert factory.get(session_row.id) is not None
    finally:
        factory_mod.run_session_loop = original  # type: ignore[attr-defined]
        await factory.aclose()


async def test_recycle_no_supervisor_returns_false() -> None:
    """``recycle()`` is a no-op + returns ``False`` when the session
    has no live supervisor — covers the "model swapped before any
    prompt has spawned the worker" path."""
    factory = InProcessRunnerRegistry()
    had_supervisor = await factory.recycle("ses_never_spawned")
    assert had_supervisor is False
    await factory.aclose()


async def test_recycle_re_call_respawns_supervisor(
    conn: aiosqlite.Connection,
) -> None:
    """After ``recycle()``, the next ``__call__`` re-spawns the
    supervisor via the existing reap-recovery branch — proves that
    "next prompt respawns with the freshly-persisted row state" is
    actually wired and not just theory.
    """
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp/wd", model="sonnet"
    )
    setup_calls: list[str] = []

    async def setup(session_id: str, runner: object) -> SessionSetup | None:
        setup_calls.append(session_id)
        return _build_setup_for(conn, session_id) if session_id == session_row.id else None

    import bearings.web.runner_factory as factory_mod

    original = factory_mod.run_session_loop  # type: ignore[attr-defined]

    async def stub_run_session_loop(
        runner: object,
        session: object,
        options_kwargs: object,
    ) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise

    factory_mod.run_session_loop = stub_run_session_loop  # type: ignore[assignment, attr-defined]
    try:
        factory = InProcessRunnerRegistry(session_setup=setup)
        await factory(session_row.id)
        await asyncio.sleep(0)
        assert setup_calls == [session_row.id]

        await factory.recycle(session_row.id)
        assert factory.get_supervisor(session_row.id) is None

        # Next call sees the runner registered + supervisor reaped →
        # re-spawns. session_setup runs a SECOND time, which is exactly
        # how the new model gets read from the DB row.
        await factory(session_row.id)
        await asyncio.sleep(0)
        assert factory.get_supervisor(session_row.id) is not None
        assert setup_calls == [session_row.id, session_row.id]
    finally:
        factory_mod.run_session_loop = original  # type: ignore[attr-defined]
        await factory.aclose()


async def test_dead_supervisor_is_respawned_on_next_call(
    conn: aiosqlite.Connection,
) -> None:
    """When the supervisor task ends on its own (e.g. ``sdk_loop``'s
    fatal-error return path after a ``Control request timeout:
    initialize``), the task lands in ``self._supervisors`` with
    ``done() is True``. The next ``__call__`` MUST treat that as
    'gone' and re-spawn — without this, every subsequent prompt
    POST silently queues against a dead worker that never drains.

    Regression: 2026-05-03 incident on ``ses_8f8aa4d947df...``. The
    old guard used ``session_id not in self._supervisors`` which the
    dead-but-present task entry made False, blocking reap-recovery.
    """
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp/wd", model="sonnet"
    )
    setup_calls: list[str] = []

    async def setup(session_id: str, runner: object) -> SessionSetup | None:
        setup_calls.append(session_id)
        return _build_setup_for(conn, session_id) if session_id == session_row.id else None

    import bearings.web.runner_factory as factory_mod

    original = factory_mod.run_session_loop  # type: ignore[attr-defined]

    # Simulate the sdk_loop fatal-error return path: the loop logs +
    # marks ERROR + returns, leaving the task done() with no exception
    # raised out of the task itself.
    async def fatal_run_session_loop(
        runner: object,
        session: object,
        options_kwargs: object,
    ) -> None:
        return None

    factory_mod.run_session_loop = fatal_run_session_loop  # type: ignore[assignment, attr-defined]
    try:
        factory = InProcessRunnerRegistry(session_setup=setup)
        await factory(session_row.id)
        # First supervisor task runs to completion.
        first_task = factory.get_supervisor(session_row.id)
        assert first_task is not None
        await first_task
        assert first_task.done()
        assert setup_calls == [session_row.id]

        # Subsequent call must see the dead task and respawn.
        await factory(session_row.id)
        await asyncio.sleep(0)
        second_task = factory.get_supervisor(session_row.id)
        assert second_task is not None
        assert second_task is not first_task
        assert setup_calls == [session_row.id, session_row.id]
    finally:
        factory_mod.run_session_loop = original  # type: ignore[attr-defined]
        await factory.aclose()


# ---------------------------------------------------------------------------
# Build helper
# ---------------------------------------------------------------------------


async def test_build_in_process_factory_threads_setup_through() -> None:
    sentinel_calls: list[str] = []

    async def setup(session_id: str, runner: object) -> SessionSetup | None:
        sentinel_calls.append(session_id)
        return None

    factory = build_in_process_factory(session_setup=setup)
    await factory("ses_z")
    assert sentinel_calls == ["ses_z"]


def _unused_factory() -> Callable[[], Awaitable[aiosqlite.Connection]]:
    async def _never() -> aiosqlite.Connection:  # pragma: no cover
        raise AssertionError("supervisor test should not invoke close_session DB factory")

    return _never
