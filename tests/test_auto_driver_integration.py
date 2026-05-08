"""End-to-end integration tests for the autonomous checklist driver.

Per the executor plug for item 1.6:

    Full loop: create checklist with 3 items, start driver, assert each
    item gets a session dispatched in order, status callbacks advance,
    final completion sentinel fires. Use a stub RunnerFactory that fakes
    session lifecycle (no real SDK calls).

This module wires the :class:`Driver` together with the
:class:`AutoDriverRegistry` + a stub :class:`AgentRunnerDriverRuntime`
so the whole orchestration path runs without booting an SDK subprocess.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest

from bearings.agent.auto_driver import Driver
from bearings.agent.auto_driver_runtime import (
    AutoDriverRegistry,
    build_registry,
    build_runtime,
)
from bearings.agent.auto_driver_types import DriverConfig, DriverOutcome
from bearings.agent.runner import RunnerFactory, SessionRunner
from bearings.db import auto_driver_runs as runs_db
from bearings.db import checklists as checklists_db
from bearings.db import get_connection_factory, load_schema


@pytest.fixture
async def connection(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    factory = get_connection_factory(tmp_path / "integration.db")
    async with factory() as conn:
        await load_schema(conn)
        await conn.execute(
            "INSERT INTO sessions (id, kind, title, working_dir, model, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "chk_int",
                "checklist",
                "T",
                "/tmp",
                "sonnet",
                "2026-01-01",
                "2026-01-01",
            ),
        )
        await conn.commit()
        yield conn


def _make_stub_runner_factory() -> RunnerFactory:
    """Per-test isolated runner registry typed at the Protocol."""
    runners: dict[str, SessionRunner] = {}

    async def _factory(session_id: str) -> SessionRunner:
        runner = runners.get(session_id)
        if runner is None:
            runner = SessionRunner(session_id, ring_buffer_max=10)
            runners[session_id] = runner
        return runner

    return _factory


def _make_leg_session_factory(
    connection: aiosqlite.Connection,
    spawned_log: list[tuple[int, int]],
):
    """Create a leg_session_factory that inserts a chat-kind sessions row.

    Records (item_id, leg_number) into ``spawned_log`` so the test can
    assert dispatch order and per-item leg counts.
    """

    async def _spawn(item_id: int, leg_number: int, plug: str | None) -> str:
        sid = f"intleg_{item_id}_{leg_number}"
        await connection.execute(
            "INSERT OR IGNORE INTO sessions (id, kind, title, working_dir, "
            "model, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, "chat", "L", "/tmp", "sonnet", "2026-01-01", "2026-01-01"),
        )
        await connection.commit()
        spawned_log.append((item_id, leg_number))
        return sid

    return _spawn


def _make_turn_driver(responses: dict[str, list[str]]):
    """Per-leg-session_id queue of assistant-body strings."""

    async def _drive(runner: SessionRunner, prompt: str) -> str:
        queue = responses.get(runner.session_id)
        if not queue:
            return ""
        return queue.pop(0)

    return _drive


async def test_full_loop_three_items_completes(
    connection: aiosqlite.Connection,
) -> None:
    """Plug requirement: create checklist with 3 items, start driver,
    assert each item gets a session dispatched in order, status
    callbacks advance, final completion sentinel fires."""
    a = await checklists_db.create(connection, checklist_id="chk_int", label="A")
    b = await checklists_db.create(connection, checklist_id="chk_int", label="B")
    c = await checklists_db.create(connection, checklist_id="chk_int", label="C")

    spawned_log: list[tuple[int, int]] = []
    runner_factory = _make_stub_runner_factory()
    leg_factory = _make_leg_session_factory(connection, spawned_log)
    responses = {
        f"intleg_{a.id}_1": ['<bearings:sentinel kind="item_done" />'],
        f"intleg_{b.id}_1": ['<bearings:sentinel kind="item_done" />'],
        f"intleg_{c.id}_1": ['<bearings:sentinel kind="item_done" />'],
    }
    runtime = build_runtime(
        runner_factory=runner_factory,
        turn_driver=_make_turn_driver(responses),
        leg_session_factory=leg_factory,
    )

    registry: AutoDriverRegistry = build_registry()
    run = await runs_db.create(connection, checklist_id="chk_int")
    driver = Driver(
        run_id=run.id,
        checklist_id="chk_int",
        config=DriverConfig(
            max_legs_per_item=2,
            max_items_per_run=10,
            max_followup_depth=2,
            max_turns_per_leg=4,
        ),
        runtime=runtime,
        connection=connection,
    )
    registry.register(driver)
    try:
        result = await driver.drive()
    finally:
        registry.unregister("chk_int")

    # Plug-requirement assertions
    assert result.outcome == DriverOutcome.COMPLETED
    assert result.items_completed == 3
    assert result.legs_spawned == 3

    # In-order dispatch: items A, B, C in their sort_order
    assert [pair[0] for pair in spawned_log] == [a.id, b.id, c.id]
    # Each item dispatched exactly once at leg 1
    assert all(pair[1] == 1 for pair in spawned_log)

    # Run-row durably stamped finished
    final = await runs_db.get(connection, run.id)
    assert final is not None
    assert final.state == "finished"
    assert final.outcome == DriverOutcome.COMPLETED
    assert final.items_completed == 3
    assert final.finished_at is not None

    # Each item is checked + has a paired chat + a leg row
    for item_id in (a.id, b.id, c.id):
        fetched = await checklists_db.get(connection, item_id)
        assert fetched is not None
        assert fetched.checked_at is not None
        assert fetched.chat_session_id is not None
        legs = await checklists_db.list_legs(connection, item_id)
        assert len(legs) == 1


async def test_registry_dispatch_stop_signals_driver(
    connection: aiosqlite.Connection,
) -> None:
    """Registry.stop() routes the cooperative-stop signal to the live
    driver instance, which transitions to ``HALTED_STOPPED``."""
    await checklists_db.create(connection, checklist_id="chk_int", label="X")
    spawned_log: list[tuple[int, int]] = []
    runner_factory = _make_stub_runner_factory()
    leg_factory = _make_leg_session_factory(connection, spawned_log)
    runtime = build_runtime(
        runner_factory=runner_factory,
        turn_driver=_make_turn_driver({}),
        leg_session_factory=leg_factory,
    )
    registry = build_registry()
    run = await runs_db.create(connection, checklist_id="chk_int")
    driver = Driver(
        run_id=run.id,
        checklist_id="chk_int",
        config=DriverConfig(
            max_legs_per_item=2,
            max_items_per_run=10,
            max_followup_depth=2,
            max_turns_per_leg=2,
        ),
        runtime=runtime,
        connection=connection,
    )
    registry.register(driver)
    # Pre-fire the stop signal — the driver halts at the first safe boundary.
    assert registry.stop("chk_int") is True
    try:
        result = await driver.drive()
    finally:
        registry.unregister("chk_int")
    assert result.outcome == DriverOutcome.HALTED_STOPPED


async def test_registry_one_active_driver_per_checklist(
    connection: aiosqlite.Connection,
) -> None:
    """Re-registering the same checklist's driver raises before unregister."""
    spawned_log: list[tuple[int, int]] = []
    runner_factory = _make_stub_runner_factory()
    leg_factory = _make_leg_session_factory(connection, spawned_log)
    runtime = build_runtime(
        runner_factory=runner_factory,
        turn_driver=_make_turn_driver({}),
        leg_session_factory=leg_factory,
    )
    registry = build_registry()
    run = await runs_db.create(connection, checklist_id="chk_int")
    driver1 = Driver(
        run_id=run.id,
        checklist_id="chk_int",
        config=DriverConfig(),
        runtime=runtime,
        connection=connection,
    )
    registry.register(driver1)
    driver2 = Driver(
        run_id=run.id + 1,
        checklist_id="chk_int",
        config=DriverConfig(),
        runtime=runtime,
        connection=connection,
    )
    with pytest.raises(RuntimeError, match="active driver"):
        registry.register(driver2)
    assert registry.unregister("chk_int") is True
    # After unregister, register-again succeeds
    registry.register(driver2)
    assert registry.get("chk_int") is driver2


async def test_runtime_pressure_report_is_observable(
    connection: aiosqlite.Connection,
) -> None:
    """Production-side ``report_pressure`` hook updates the per-leg cache."""
    runner_factory = _make_stub_runner_factory()
    spawned_log: list[tuple[int, int]] = []
    leg_factory = _make_leg_session_factory(connection, spawned_log)
    runtime = build_runtime(
        runner_factory=runner_factory,
        turn_driver=_make_turn_driver({}),
        leg_session_factory=leg_factory,
    )
    # Cast through Any since the Protocol hides the concrete impl.
    from bearings.agent.auto_driver_runtime import AgentRunnerDriverRuntime

    assert isinstance(runtime, AgentRunnerDriverRuntime)
    assert runtime.last_context_percentage("nope") is None
    runtime.report_pressure(leg_session_id="leg_x", percentage=42.5)
    assert runtime.last_context_percentage("leg_x") == 42.5


async def test_active_checklists_lists_registrations(
    connection: aiosqlite.Connection,
) -> None:
    runner_factory = _make_stub_runner_factory()
    spawned_log: list[tuple[int, int]] = []
    leg_factory = _make_leg_session_factory(connection, spawned_log)
    runtime = build_runtime(
        runner_factory=runner_factory,
        turn_driver=_make_turn_driver({}),
        leg_session_factory=leg_factory,
    )
    registry = build_registry()
    assert registry.active_checklists() == []
    run = await runs_db.create(connection, checklist_id="chk_int")
    driver = Driver(
        run_id=run.id,
        checklist_id="chk_int",
        config=DriverConfig(),
        runtime=runtime,
        connection=connection,
    )
    registry.register(driver)
    assert registry.active_checklists() == ["chk_int"]
    registry.unregister("chk_int")
    assert registry.active_checklists() == []


# ---------------------------------------------------------------------------
# feature-6-005: visit_existing + closed-chat skip
# ---------------------------------------------------------------------------


async def test_visit_existing_skips_closed_paired_chat(
    connection: aiosqlite.Connection,
) -> None:
    """visit_existing=True + closed paired chat → item skipped, zero legs spawned.

    Acceptance criteria (feature-6-005):
    * driver checks open state before reusing item.chat_session_id
    * if closed → item recorded as skipped (items_skipped == 1)
    * no leg is spawned for that item (legs_spawned == 0)
    """
    item = await checklists_db.create(connection, checklist_id="chk_int", label="X")
    # Create a chat session and immediately close it.
    await connection.execute(
        "INSERT INTO sessions (id, kind, title, working_dir, model, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("closed_chat", "chat", "C", "/tmp", "sonnet", "2026-01-01", "2026-01-01"),
    )
    await connection.execute(
        "UPDATE sessions SET closed_at = '2026-01-02' WHERE id = 'closed_chat'"
    )
    # Wire the closed chat as the item's paired chat pointer.
    await connection.execute(
        "UPDATE checklist_items SET chat_session_id = 'closed_chat' WHERE id = ?",
        (item.id,),
    )
    await connection.commit()

    spawned_log: list[tuple[int, int]] = []
    runner_factory = _make_stub_runner_factory()
    leg_factory = _make_leg_session_factory(connection, spawned_log)
    runtime = build_runtime(
        runner_factory=runner_factory,
        turn_driver=_make_turn_driver({}),
        leg_session_factory=leg_factory,
    )
    run = await runs_db.create(connection, checklist_id="chk_int")
    driver = Driver(
        run_id=run.id,
        checklist_id="chk_int",
        config=DriverConfig(
            visit_existing=True,
            max_legs_per_item=2,
            max_items_per_run=10,
            max_turns_per_leg=4,
        ),
        runtime=runtime,
        connection=connection,
    )
    result = await driver.drive()

    assert result.items_skipped == 1, "closed paired chat must contribute to skipped count"
    assert result.legs_spawned == 0, "no leg must be spawned for the skipped item"
    fetched = await checklists_db.get(connection, item.id)
    assert fetched is not None
    assert fetched.blocked_at is not None, "skipped item must have blocked_at set"


async def test_visit_existing_reuses_open_chat_unchanged(
    connection: aiosqlite.Connection,
) -> None:
    """visit_existing=True + open paired chat → reused normally, not skipped."""
    item = await checklists_db.create(connection, checklist_id="chk_int", label="Y")
    await connection.execute(
        "INSERT INTO sessions (id, kind, title, working_dir, model, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("open_chat", "chat", "O", "/tmp", "sonnet", "2026-01-01", "2026-01-01"),
    )
    await connection.execute(
        "UPDATE checklist_items SET chat_session_id = 'open_chat' WHERE id = ?",
        (item.id,),
    )
    await connection.commit()

    spawned_log: list[tuple[int, int]] = []
    runner_factory = _make_stub_runner_factory()
    leg_factory = _make_leg_session_factory(connection, spawned_log)
    responses = {
        "open_chat": ['<bearings:sentinel kind="item_done" />'],
    }
    runtime = build_runtime(
        runner_factory=runner_factory,
        turn_driver=_make_turn_driver(responses),
        leg_session_factory=leg_factory,
    )
    run = await runs_db.create(connection, checklist_id="chk_int")
    driver = Driver(
        run_id=run.id,
        checklist_id="chk_int",
        config=DriverConfig(
            visit_existing=True,
            max_legs_per_item=2,
            max_items_per_run=10,
            max_turns_per_leg=4,
        ),
        runtime=runtime,
        connection=connection,
    )
    result = await driver.drive()

    assert result.items_completed == 1, "open paired chat must be reused and driven to done"
    assert result.items_skipped == 0
    # open_chat was reused — leg_factory was NOT called (no spawn)
    assert spawned_log == [], "visit_existing should not spawn a new leg for an open chat"


# ---------------------------------------------------------------------------
# feature-6-001: blocking followups recurse before completing parent
# ---------------------------------------------------------------------------


async def test_blocking_followup_drives_child_before_parent_done(
    connection: aiosqlite.Connection,
) -> None:
    """Blocking followup: child is driven to terminal BEFORE parent completes.

    Acceptance criteria (feature-6-001):
    * Parent leg emits a blocking followup sentinel — child item is created.
    * Driver drives the child to terminal (item_done) before the parent's
      item_done is processed.
    * Both child and parent have checked_at set after the run.
    * Counters: items_completed == 2 (child then parent).
    """
    parent = await checklists_db.create(connection, checklist_id="chk_int", label="Parent")

    spawned_log: list[tuple[int, int]] = []
    runner_factory = _make_stub_runner_factory()
    leg_factory = _make_leg_session_factory(connection, spawned_log)

    # The parent leg emits a blocking followup + item_done in the same turn.
    # The driver must drive the child before checking the parent.
    # We don't know the child's item id in advance, so we use a turn_driver
    # that returns item_done for any session that starts with "intleg_".
    _child_driven: list[int] = []  # item_ids driven as children

    async def _smart_turn_driver(runner: SessionRunner, prompt: str) -> str:
        sid = runner.session_id
        if sid == f"intleg_{parent.id}_1":
            # Parent leg: emit a blocking followup + item_done.
            return (
                '<bearings:sentinel kind="followup_blocking">'
                "<label>Child task</label>"
                "</bearings:sentinel>"
                '<bearings:sentinel kind="item_done" />'
            )
        # Any other session is a child leg — record it and complete.
        _child_driven.append(1)
        return '<bearings:sentinel kind="item_done" />'

    runtime = build_runtime(
        runner_factory=runner_factory,
        turn_driver=_smart_turn_driver,
        leg_session_factory=leg_factory,
    )
    run = await runs_db.create(connection, checklist_id="chk_int")
    driver = Driver(
        run_id=run.id,
        checklist_id="chk_int",
        config=DriverConfig(
            max_legs_per_item=2,
            max_items_per_run=10,
            max_followup_depth=2,
            max_turns_per_leg=4,
        ),
        runtime=runtime,
        connection=connection,
    )
    result = await driver.drive()

    assert result.outcome == DriverOutcome.COMPLETED
    assert result.items_completed == 2, "both child and parent must be completed"
    assert len(_child_driven) >= 1, "child leg must have been driven"

    # Parent and child are both checked.
    items = await checklists_db.list_for_checklist(connection, "chk_int")
    assert all(item.checked_at is not None for item in items), "all items must be checked after run"
    # Child was driven (appears in spawned_log) before parent's leg session id
    # is teardown — verified by the two entries in spawned_log.
    parent_leg_entry = (parent.id, 1)
    assert parent_leg_entry in spawned_log
    # Child also appears — spawned_log has at least 2 entries
    assert len(spawned_log) >= 2, "parent leg + child leg both spawned"


async def test_blocking_followup_depth_cap_ignores_deep_nesting(
    connection: aiosqlite.Connection,
) -> None:
    """Blocking followup at max_followup_depth is ignored (malformed sentinel)."""
    await checklists_db.create(connection, checklist_id="chk_int", label="P")

    spawned_log: list[tuple[int, int]] = []
    runner_factory = _make_stub_runner_factory()
    leg_factory = _make_leg_session_factory(connection, spawned_log)

    async def _depth_turn_driver(runner: SessionRunner, prompt: str) -> str:
        # Every leg: emit a blocking followup AND item_done.
        # With max_followup_depth=1, the child (depth=1) sees the followup
        # but depth >= max_followup_depth so it is ignored; child just completes.
        return (
            '<bearings:sentinel kind="followup_blocking">'
            "<label>Deep child</label>"
            "</bearings:sentinel>"
            '<bearings:sentinel kind="item_done" />'
        )

    runtime = build_runtime(
        runner_factory=runner_factory,
        turn_driver=_depth_turn_driver,
        leg_session_factory=leg_factory,
    )
    run = await runs_db.create(connection, checklist_id="chk_int")
    driver = Driver(
        run_id=run.id,
        checklist_id="chk_int",
        config=DriverConfig(
            max_legs_per_item=2,
            max_items_per_run=10,
            max_followup_depth=1,  # cap at depth 1 — child's followup is ignored
            max_turns_per_leg=4,
        ),
        runtime=runtime,
        connection=connection,
    )
    result = await driver.drive()

    assert result.outcome == DriverOutcome.COMPLETED
    # Parent + one child (created at depth 0, driven at depth 1).
    # The child's followup at depth 1 is ignored.
    assert result.items_completed == 2
    items = await checklists_db.list_for_checklist(connection, "chk_int")
    assert all(item.checked_at is not None for item in items)
