"""Unit tests for ``bearings.agent.auto_driver.Driver``.

State machine + sentinel handling + safety caps + RunnerFactory
injection. Uses a stub :class:`DriverRuntime` so tests exercise the
loop without booting an SDK subprocess.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite
import pytest

from bearings.agent.auto_driver import Driver
from bearings.agent.auto_driver_types import DriverConfig, DriverOutcome
from bearings.config.constants import (
    AUTO_DRIVER_FAILURE_POLICY_HALT,
    AUTO_DRIVER_FAILURE_POLICY_SKIP,
    AUTO_DRIVER_STATE_FINISHED,
    DRIVER_OUTCOME_COMPLETED,
    DRIVER_OUTCOME_HALTED_EMPTY,
    DRIVER_OUTCOME_HALTED_STOPPED,
    ITEM_OUTCOME_BLOCKED,
    ITEM_OUTCOME_FAILED,
    ITEM_OUTCOME_SKIPPED,
)
from bearings.db import auto_driver_runs as runs_db
from bearings.db import checklists as checklists_db
from bearings.db import get_connection_factory, load_schema


@dataclass
class StubRuntime:
    """Test stub for :class:`DriverRuntime`.

    The ``leg_responses`` map carries per-leg-session_id queues of
    assistant-body strings; each :meth:`run_turn` call pops the next.
    The stub also inserts a chat-kind ``sessions`` row on spawn so the
    paired_chats FK resolves without test-side pre-seeding.
    """

    connection: aiosqlite.Connection
    leg_responses: dict[str, list[str]] = field(default_factory=dict)
    pressure: dict[str, float | None] = field(default_factory=dict)
    spawned: list[str] = field(default_factory=list)
    teardowns: list[str] = field(default_factory=list)
    turn_calls: list[tuple[str, str]] = field(default_factory=list)
    leg_session_factory: Callable[[int, int, str | None], Awaitable[str]] | None = None

    async def spawn_leg(
        self,
        *,
        item_id: int,
        leg_number: int,
        plug: str | None,
    ) -> str:
        sid = f"leg_{item_id}_{leg_number}"
        # Insert the chat-kind session row so paired_chats FK resolves.
        await self.connection.execute(
            "INSERT OR IGNORE INTO sessions (id, kind, title, working_dir, "
            "model, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, "chat", "L", "/tmp", "sonnet", "2026-01-01", "2026-01-01"),
        )
        await self.connection.commit()
        self.spawned.append(sid)
        return sid

    async def run_turn(self, *, leg_session_id: str, prompt: str) -> str:
        self.turn_calls.append((leg_session_id, prompt))
        queue = self.leg_responses.get(leg_session_id)
        if not queue:
            return ""  # quiet turn → no sentinel
        return queue.pop(0)

    async def teardown_leg(self, *, leg_session_id: str) -> None:
        self.teardowns.append(leg_session_id)

    def last_context_percentage(self, leg_session_id: str) -> float | None:
        return self.pressure.get(leg_session_id)


@pytest.fixture
async def connection(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    factory = get_connection_factory(tmp_path / "driver_unit.db")
    async with factory() as conn:
        await load_schema(conn)
        await conn.execute(
            "INSERT INTO sessions (id, kind, title, working_dir, model, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "chk_1",
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


async def _build_driver(
    connection: aiosqlite.Connection,
    runtime: StubRuntime,
    *,
    config: DriverConfig | None = None,
) -> Driver:
    run = await runs_db.create(connection, checklist_id="chk_1")
    cfg = config or DriverConfig(
        max_legs_per_item=3,
        max_items_per_run=10,
        max_followup_depth=2,
        max_turns_per_leg=4,
    )
    return Driver(
        run_id=run.id,
        checklist_id="chk_1",
        config=cfg,
        runtime=runtime,
        connection=connection,
    )


async def _add_item(
    connection: aiosqlite.Connection,
    label: str,
) -> int:
    """Add a leaf item under chk_1; returns its id."""
    item = await checklists_db.create(connection, checklist_id="chk_1", label=label)
    return item.id


def _leg_id(item_id: int, leg_number: int) -> str:
    """Helper mirroring StubRuntime.spawn_leg's session-id format."""
    return f"leg_{item_id}_{leg_number}"


async def test_drive_empty_returns_halted_empty(
    connection: aiosqlite.Connection,
) -> None:
    runtime = StubRuntime(connection=connection)
    driver = await _build_driver(connection, runtime)
    result = await driver.drive()
    assert result.outcome == DriverOutcome.HALTED_EMPTY
    assert result.items_completed == 0
    assert result.legs_spawned == 0


async def test_drive_one_item_completed(connection: aiosqlite.Connection) -> None:
    item_id = await _add_item(connection, "task A")
    runtime = StubRuntime(connection=connection)
    runtime.leg_responses[_leg_id(item_id, 1)] = [
        '<bearings:sentinel kind="item_done" />',
    ]
    driver = await _build_driver(connection, runtime)
    result = await driver.drive()
    assert result.outcome == DriverOutcome.COMPLETED
    assert result.items_completed == 1
    assert result.legs_spawned == 1
    fetched = await checklists_db.get(connection, item_id)
    assert fetched is not None
    assert fetched.checked_at is not None


async def test_drive_handoff_then_done_spawns_two_legs(
    connection: aiosqlite.Connection,
) -> None:
    item_id = await _add_item(connection, "task A")
    runtime = StubRuntime(connection=connection)
    runtime.leg_responses[_leg_id(item_id, 1)] = [
        '<bearings:sentinel kind="handoff"><plug>continue</plug></bearings:sentinel>',
    ]
    runtime.leg_responses[_leg_id(item_id, 2)] = [
        '<bearings:sentinel kind="item_done" />',
    ]
    driver = await _build_driver(connection, runtime)
    result = await driver.drive()
    assert result.outcome == DriverOutcome.COMPLETED
    assert result.legs_spawned == 2
    assert result.items_completed == 1
    legs = await checklists_db.list_legs(connection, item_id)
    assert len(legs) == 2


async def test_drive_item_blocked(connection: aiosqlite.Connection) -> None:
    item_id = await _add_item(connection, "blocked task")
    runtime = StubRuntime(connection=connection)
    runtime.leg_responses[_leg_id(item_id, 1)] = [
        '<bearings:sentinel kind="item_blocked"><text>creds</text></bearings:sentinel>',
    ]
    driver = await _build_driver(connection, runtime)
    result = await driver.drive()
    assert result.outcome == DriverOutcome.COMPLETED
    assert result.items_blocked == 1
    fetched = await checklists_db.get(connection, item_id)
    assert fetched is not None
    assert fetched.blocked_at is not None
    assert fetched.blocked_reason_category == ITEM_OUTCOME_BLOCKED


async def test_drive_item_failed_halt_policy(
    connection: aiosqlite.Connection,
) -> None:
    item_id = await _add_item(connection, "broken")
    runtime = StubRuntime(connection=connection)
    runtime.leg_responses[_leg_id(item_id, 1)] = [
        '<bearings:sentinel kind="item_failed"><reason>boom</reason></bearings:sentinel>',
    ]
    driver = await _build_driver(connection, runtime)
    result = await driver.drive()
    assert result.outcome == DriverOutcome.halted_failure(item_id)
    assert result.items_failed == 1


async def test_drive_item_failed_skip_policy(
    connection: aiosqlite.Connection,
) -> None:
    item_a = await _add_item(connection, "broken")
    item_b = await _add_item(connection, "next")
    runtime = StubRuntime(connection=connection)
    runtime.leg_responses[_leg_id(item_a, 1)] = [
        '<bearings:sentinel kind="item_failed"><reason>broken</reason></bearings:sentinel>',
    ]
    runtime.leg_responses[_leg_id(item_b, 1)] = [
        '<bearings:sentinel kind="item_done" />',
    ]
    cfg = DriverConfig(
        failure_policy=AUTO_DRIVER_FAILURE_POLICY_SKIP,
        max_legs_per_item=2,
        max_items_per_run=10,
        max_followup_depth=2,
        max_turns_per_leg=4,
    )
    driver = await _build_driver(connection, runtime, config=cfg)
    result = await driver.drive()
    assert result.items_failed == 1
    assert result.items_completed == 1
    assert result.outcome == DriverOutcome.COMPLETED


async def test_drive_max_legs_per_item_failure(
    connection: aiosqlite.Connection,
) -> None:
    item_id = await _add_item(connection, "loop")
    runtime = StubRuntime(connection=connection)
    handoff_response = '<bearings:sentinel kind="handoff"><plug>x</plug></bearings:sentinel>'
    runtime.leg_responses[_leg_id(item_id, 1)] = [handoff_response]
    runtime.leg_responses[_leg_id(item_id, 2)] = [handoff_response]
    cfg = DriverConfig(
        max_legs_per_item=2,
        max_items_per_run=10,
        max_followup_depth=2,
        max_turns_per_leg=4,
    )
    driver = await _build_driver(connection, runtime, config=cfg)
    result = await driver.drive()
    assert result.outcome == DriverOutcome.halted_failure(item_id)
    assert result.items_failed == 1
    assert result.legs_spawned == 2


async def test_drive_max_items_per_run(connection: aiosqlite.Connection) -> None:
    item_a = await _add_item(connection, "a")
    item_b = await _add_item(connection, "b")
    await _add_item(connection, "c")
    runtime = StubRuntime(connection=connection)
    runtime.leg_responses[_leg_id(item_a, 1)] = [
        '<bearings:sentinel kind="item_done" />',
    ]
    runtime.leg_responses[_leg_id(item_b, 1)] = [
        '<bearings:sentinel kind="item_done" />',
    ]
    cfg = DriverConfig(
        max_legs_per_item=2,
        max_items_per_run=2,
        max_followup_depth=2,
        max_turns_per_leg=4,
    )
    driver = await _build_driver(connection, runtime, config=cfg)
    result = await driver.drive()
    assert result.outcome == DriverOutcome.HALTED_MAX_ITEMS
    assert result.items_attempted == 2


async def test_request_stop_halts_driver(connection: aiosqlite.Connection) -> None:
    await _add_item(connection, "task")
    runtime = StubRuntime(connection=connection)
    cfg = DriverConfig(
        max_legs_per_item=2,
        max_items_per_run=10,
        max_followup_depth=2,
        max_turns_per_leg=4,
    )
    driver = await _build_driver(connection, runtime, config=cfg)
    driver.request_stop()
    result = await driver.drive()
    assert result.outcome == DriverOutcome.HALTED_STOPPED
    row = await runs_db.get(connection, driver.run_id)
    assert row is not None
    assert row.state == AUTO_DRIVER_STATE_FINISHED
    assert row.outcome == DRIVER_OUTCOME_HALTED_STOPPED


async def test_request_skip_current_marks_skipped(
    connection: aiosqlite.Connection,
) -> None:
    item_id = await _add_item(connection, "task")
    runtime = StubRuntime(connection=connection)
    cfg = DriverConfig(
        max_legs_per_item=2,
        max_items_per_run=10,
        max_followup_depth=2,
        max_turns_per_leg=4,
    )
    driver = await _build_driver(connection, runtime, config=cfg)
    driver.request_skip_current()
    result = await driver.drive()
    assert result.items_skipped == 1
    fetched = await checklists_db.get(connection, item_id)
    assert fetched is not None
    assert fetched.blocked_reason_category == ITEM_OUTCOME_SKIPPED


async def test_followup_blocking_creates_child(
    connection: aiosqlite.Connection,
) -> None:
    """Blocking followup creates a child item AND drives it before the parent.

    Updated for feature-6-001: the driver now recurses into the child before
    resuming the parent. Here the child has no scripted responses so it exhausts
    the turn budget and is recorded as failed. With failure_policy='skip' the
    run continues; the parent's queued item_done then fires and the parent
    completes.
    """
    parent = await _add_item(connection, "parent")
    runtime = StubRuntime(connection=connection)
    runtime.leg_responses[_leg_id(parent, 1)] = [
        '<bearings:sentinel kind="followup_blocking"><label>new child</label></bearings:sentinel>',
        '<bearings:sentinel kind="item_done" />',
    ]
    cfg = DriverConfig(
        failure_policy="skip",  # child failure must not halt the whole run
        max_legs_per_item=2,
        max_items_per_run=10,
        max_followup_depth=2,
        max_turns_per_leg=4,
    )
    driver = await _build_driver(connection, runtime, config=cfg)
    result = await driver.drive()
    items = await checklists_db.list_for_checklist(connection, "chk_1")
    # Child item was created.
    assert any(i.label == "new child" for i in items)
    # Child was driven (and failed — no responses provided) before parent completed.
    assert result.items_failed == 1, "child should have been driven and failed"
    # Parent completed after the child's failure was recorded.
    assert result.items_completed == 1, "parent should complete after child is resolved"


async def test_quiet_turn_with_pressure_injects_nudge(
    connection: aiosqlite.Connection,
) -> None:
    item_id = await _add_item(connection, "task")
    runtime = StubRuntime(connection=connection)
    leg_id = _leg_id(item_id, 1)
    runtime.leg_responses[leg_id] = [
        "(no sentinel)",
        "(still nothing)",
        '<bearings:sentinel kind="item_done" />',
    ]
    runtime.pressure[leg_id] = 70.0
    cfg = DriverConfig(
        max_legs_per_item=2,
        max_items_per_run=10,
        max_followup_depth=2,
        max_turns_per_leg=5,
    )
    driver = await _build_driver(connection, runtime, config=cfg)
    result = await driver.drive()
    assert result.items_completed == 1
    prompts = [prompt for _, prompt in runtime.turn_calls]
    assert any("watchdog" in p or "handoff plug" in p for p in prompts)


async def test_leg_turn_cap_synthesises_failure(
    connection: aiosqlite.Connection,
) -> None:
    item_id = await _add_item(connection, "task")
    runtime = StubRuntime(connection=connection)
    runtime.leg_responses[_leg_id(item_id, 1)] = ["", "", "", ""]
    cfg = DriverConfig(
        max_legs_per_item=1,
        max_items_per_run=10,
        max_followup_depth=2,
        max_turns_per_leg=2,
    )
    driver = await _build_driver(connection, runtime, config=cfg)
    result = await driver.drive()
    assert result.items_failed == 1
    fetched = await checklists_db.get(connection, item_id)
    assert fetched is not None
    assert fetched.blocked_reason_category == ITEM_OUTCOME_FAILED


def test_driver_rejects_empty_checklist_id() -> None:
    """Constructor validates checklist_id — never reach driver code."""

    class _DummyRuntime:
        async def spawn_leg(self, *, item_id: int, leg_number: int, plug: str | None) -> str:
            return ""

        async def run_turn(self, *, leg_session_id: str, prompt: str) -> str:
            return ""

        async def teardown_leg(self, *, leg_session_id: str) -> None:
            pass

        def last_context_percentage(self, leg_session_id: str) -> float | None:
            return None

    with pytest.raises(ValueError, match="checklist_id"):
        Driver(
            run_id=1,
            checklist_id="",
            config=DriverConfig(),
            runtime=_DummyRuntime(),
            connection=None,  # type: ignore[arg-type]
        )


def test_driver_config_rejects_bad_failure_policy() -> None:
    with pytest.raises(ValueError, match="failure_policy"):
        DriverConfig(failure_policy="not-real")


def test_driver_config_rejects_zero_caps() -> None:
    with pytest.raises(ValueError, match="max_legs_per_item"):
        DriverConfig(max_legs_per_item=0)


def test_driver_outcome_halted_failure_template() -> None:
    s = DriverOutcome.halted_failure(42)
    assert "42" in s
    assert "Halted" in s


def test_driver_outcome_constants_exposed() -> None:
    assert DriverOutcome.COMPLETED == DRIVER_OUTCOME_COMPLETED
    assert DriverOutcome.HALTED_EMPTY == DRIVER_OUTCOME_HALTED_EMPTY
    assert DriverOutcome.HALTED_STOPPED == DRIVER_OUTCOME_HALTED_STOPPED


def test_failure_policy_defaults_halt() -> None:
    cfg = DriverConfig()
    assert cfg.failure_policy == AUTO_DRIVER_FAILURE_POLICY_HALT
