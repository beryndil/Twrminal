"""Unit tests for the autonomous checklist driver state machine.

The driver in `bearings.agent.auto_driver` is deliberately runtime-
agnostic: it takes a `DriverRuntime` Protocol and calls three methods
on it (`spawn_leg` / `run_turn` / `teardown_leg`). These tests wire
a `StubRuntime` that plays canned scripts per item, so every branch
of the state machine is exercised without touching a real
`claude-agent-sdk` subprocess.

What we're proving here:

- The outer loop picks items in `sort_order` and advances on done.
- Handoff cutover: one item produces multiple legs, each with its
  own session row, and the plug is threaded forward.
- Blocking followups become children that drive before the parent
  can complete; non-blocking followups become top-level items
  picked up by the outer loop.
- Safety caps: `max_items_per_run`, `max_legs_per_item`,
  `max_followup_depth` all halt correctly with the right outcome.
- Silent exit (no sentinel) halts the driver.
- `stop()` from another task halts at the next iteration boundary
  without leaving a leg mid-turn.
- Runtime-raised exceptions propagate to a failure halt and the
  leg is still torn down (no runner leak).

The tests follow the same pattern as `tests/test_checklists_autonomous.py`:
each test opens its own `init_db` connection and closes it in a
try/finally rather than sharing a fixture, because the project's
pytest-asyncio config doesn't use async-yield fixtures.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from bearings.agent.auto_driver import (
    Driver,
    DriverConfig,
    DriverOutcome,
)
from bearings.db.store import (
    create_checklist,
    create_item,
    create_session,
    get_item,
    init_db,
)

# --- stub runtime ---------------------------------------------------


@dataclass
class StubRuntime:
    """Plays a canned list of turn replies per item id.

    `turns_by_item[item_id]` is a list of assistant-text replies; each
    call to `run_turn` for a leg paired to that item pops the next
    reply in order. Exhausting the list raises — tests that care about
    leg counts pre-populate enough replies.

    `run_turn_raises_for_item` lets a test simulate a runtime error
    without having to author a subclass.
    """

    conn: aiosqlite.Connection | None
    turns_by_item: dict[int, list[str]] = field(default_factory=dict)
    run_turn_raises_for_item: set[int] = field(default_factory=set)
    # Per-item percentages played back in order for each run_turn call
    # on a leg paired to that item. Default None from the helper below
    # means "no ContextUsage observed" — opts the item out of the
    # pressure-nudge branch.
    percentages_by_item: dict[int, list[float]] = field(default_factory=dict)
    spawn_calls: list[tuple[int, int, str | None]] = field(default_factory=list)
    turn_calls: list[tuple[str, int, str]] = field(default_factory=list)
    teardown_calls: list[str] = field(default_factory=list)
    _session_to_item: dict[str, int] = field(default_factory=dict)
    _turn_index: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    _pct_index: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    _last_pct_by_session: dict[str, float | None] = field(default_factory=dict)

    async def spawn_leg(
        self,
        *,
        item: dict[str, Any],
        leg_number: int,
        plug: str | None,
    ) -> str:
        assert self.conn is not None
        self.spawn_calls.append((item["id"], leg_number, plug))
        session = await create_session(
            self.conn,
            working_dir="/tmp",
            model="stub-model",
            kind="chat",
            checklist_item_id=item["id"],
            title=f"{item['label']} (leg {leg_number})",
        )
        self._session_to_item[session["id"]] = item["id"]
        return str(session["id"])

    async def run_turn(self, *, session_id: str, prompt: str) -> str:
        item_id = self._session_to_item[session_id]
        self.turn_calls.append((session_id, item_id, prompt))
        if item_id in self.run_turn_raises_for_item:
            raise RuntimeError(f"stub run_turn failure for item {item_id}")
        scripts = self.turns_by_item.get(item_id, [])
        idx = self._turn_index[item_id]
        if idx >= len(scripts):
            raise AssertionError(
                f"StubRuntime: no scripted reply for item {item_id} turn {idx + 1}"
            )
        self._turn_index[item_id] = idx + 1
        # Advance the percentage script in lockstep with the turn
        # script so a test can say "turn 1 pressure=75%, turn 2 after
        # nudge pressure=15%" by listing both.
        pcts = self.percentages_by_item.get(item_id, [])
        pidx = self._pct_index[item_id]
        if pidx < len(pcts):
            self._last_pct_by_session[session_id] = pcts[pidx]
            self._pct_index[item_id] = pidx + 1
        else:
            # Fall back to whatever the last observed percentage was,
            # or None if the test never specified one — matches the
            # real runtime's behavior when a ContextUsage event is
            # missing for a turn.
            self._last_pct_by_session.setdefault(session_id, None)
        return scripts[idx]

    async def teardown_leg(self, session_id: str) -> None:
        self.teardown_calls.append(session_id)

    def last_context_percentage(self, session_id: str) -> float | None:
        return self._last_pct_by_session.get(session_id)


async def _fresh_checklist(conn: aiosqlite.Connection) -> str:
    """Create a fresh kind='checklist' session + empty checklist body
    and return its id. Centralized so every test doesn't repeat the
    two-step boilerplate."""
    session = await create_session(conn, working_dir="/tmp", model="stub-model", kind="checklist")
    await create_checklist(conn, session["id"])
    return str(session["id"])


# --- happy path -----------------------------------------------------


@pytest.mark.asyncio
async def test_empty_checklist_halts_empty(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        runtime = StubRuntime(conn=conn)
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.HALTED_EMPTY
        assert result.items_completed == 0
        assert result.legs_spawned == 0
        assert runtime.spawn_calls == []
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_single_item_done_first_turn(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="single")
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={item["id"]: ["All done.\nCHECKLIST_ITEM_DONE"]},
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.items_completed == 1
        assert result.legs_spawned == 1
        refreshed = await get_item(conn, item["id"])
        assert refreshed is not None
        assert refreshed["checked_at"] is not None
        # Teardown is called even on the happy path — no runner leak.
        assert len(runtime.teardown_calls) == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_multiple_items_drive_in_sort_order(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        a = await create_item(conn, checklist_id, label="a", sort_order=0)
        b = await create_item(conn, checklist_id, label="b", sort_order=1)
        c = await create_item(conn, checklist_id, label="c", sort_order=2)
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                a["id"]: ["CHECKLIST_ITEM_DONE"],
                b["id"]: ["CHECKLIST_ITEM_DONE"],
                c["id"]: ["CHECKLIST_ITEM_DONE"],
            },
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.items_completed == 3
        assert [call[0] for call in runtime.spawn_calls] == [
            a["id"],
            b["id"],
            c["id"],
        ]
    finally:
        await conn.close()


# --- handoff legs ---------------------------------------------------


@pytest.mark.asyncio
async def test_handoff_spawns_successor_leg_with_plug(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="heavy")
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                item["id"]: [
                    # Leg 1 hands off mid-work.
                    "Context getting tight.\n"
                    "CHECKLIST_HANDOFF\n"
                    "progress: wrote the schema; still need the migration\n"
                    "CHECKLIST_HANDOFF_END",
                    # Leg 2 completes.
                    "Finished.\nCHECKLIST_ITEM_DONE",
                ]
            },
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.items_completed == 1
        assert result.legs_spawned == 2
        # Leg 1: no plug. Leg 2: plug from leg 1 threaded forward.
        assert runtime.spawn_calls[0] == (item["id"], 1, None)
        assert runtime.spawn_calls[1][0:2] == (item["id"], 2)
        assert runtime.spawn_calls[1][2] is not None
        assert "wrote the schema" in runtime.spawn_calls[1][2]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_handoff_exceeds_max_legs_halts_failure(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="runaway")
        # Agent just hands off forever — safety cap should kick in.
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                item["id"]: [
                    "CHECKLIST_HANDOFF\nleg 1 plug\nCHECKLIST_HANDOFF_END",
                    "CHECKLIST_HANDOFF\nleg 2 plug\nCHECKLIST_HANDOFF_END",
                ]
            },
        )
        config = DriverConfig(max_legs_per_item=2)
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            config=config,
        )
        result = await driver.drive()
        assert result.outcome == DriverOutcome.HALTED_FAILURE
        assert result.items_failed == 1
        assert result.legs_spawned == 2
        assert result.failed_item_id == item["id"]
        assert "max_legs_per_item" in (result.failure_reason or "")
    finally:
        await conn.close()


# --- followups ------------------------------------------------------


@pytest.mark.asyncio
async def test_non_blocking_followup_appends_top_level_item(
    tmp_path: Path,
) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="primary")
        # The followup's id isn't known until it's inserted, but
        # AUTOINCREMENT gives us item id + 1 for the next insert —
        # pre-seed the stub script with that predicted id.
        followup_id = item["id"] + 1
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                item["id"]: [
                    "Done, but add a doc task for later.\n"
                    "CHECKLIST_FOLLOWUP block=no\n"
                    "Update the README\n"
                    "CHECKLIST_FOLLOWUP_END\n"
                    "CHECKLIST_ITEM_DONE"
                ],
                followup_id: ["CHECKLIST_ITEM_DONE"],
            },
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        # Original item + the followup the agent appended.
        assert result.items_completed == 2
        followup = await get_item(conn, followup_id)
        assert followup is not None
        assert followup["label"] == "Update the README"
        # Non-blocking = top-level (parent_item_id is NULL).
        assert followup["parent_item_id"] is None
        assert followup["checked_at"] is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_blocking_followup_drives_child_before_parent(
    tmp_path: Path,
) -> None:
    """Parent leg 1: file blocking child, no done / no handoff.
    Expectation: driver recurses into child, child completes, parent
    re-enters for leg 2 and marks done."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        parent = await create_item(conn, checklist_id, label="parent")
        child_id = parent["id"] + 1
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                parent["id"]: [
                    "I need a prereq first.\n"
                    "CHECKLIST_FOLLOWUP block=yes\n"
                    "install the dep\n"
                    "CHECKLIST_FOLLOWUP_END",
                    "All done now.\nCHECKLIST_ITEM_DONE",
                ],
                child_id: ["Installed.\nCHECKLIST_ITEM_DONE"],
            },
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.items_completed == 2
        # Spawn order: parent leg 1, child leg 1, parent leg 2.
        assert [call[0] for call in runtime.spawn_calls] == [
            parent["id"],
            child_id,
            parent["id"],
        ]
        child = await get_item(conn, child_id)
        assert child is not None
        assert child["parent_item_id"] == parent["id"]
        assert child["checked_at"] is not None
        parent_refreshed = await get_item(conn, parent["id"])
        assert parent_refreshed is not None
        assert parent_refreshed["checked_at"] is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_blocking_followup_with_done_on_same_turn(
    tmp_path: Path,
) -> None:
    """Agent emits both a blocking child AND done in the same turn.
    Design: blocking-first — drive the child, then apply the done
    toggle. No extra parent leg spawned."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        parent = await create_item(conn, checklist_id, label="parent")
        child_id = parent["id"] + 1
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                parent["id"]: [
                    "Done, but here's a blocking child.\n"
                    "CHECKLIST_FOLLOWUP block=yes\n"
                    "extra step\n"
                    "CHECKLIST_FOLLOWUP_END\n"
                    "CHECKLIST_ITEM_DONE"
                ],
                child_id: ["CHECKLIST_ITEM_DONE"],
            },
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.items_completed == 2
        # Only 1 parent leg + 1 child leg — no re-enter because done
        # was emitted on the parent's first turn.
        assert [call[0] for call in runtime.spawn_calls] == [
            parent["id"],
            child_id,
        ]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_followup_depth_cap_halts_failure(tmp_path: Path) -> None:
    """Blocking-child-spawning blocking-child-spawning... eventually
    hits the depth cap and fails cleanly with a descriptive reason."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        root = await create_item(conn, checklist_id, label="root")
        # Each level just spawns another blocking child and exits
        # without done or handoff. Driver will recurse, hit the cap,
        # and fail.
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                root["id"]: ["CHECKLIST_FOLLOWUP block=yes\nlvl 1\nCHECKLIST_FOLLOWUP_END"],
                root["id"] + 1: ["CHECKLIST_FOLLOWUP block=yes\nlvl 2\nCHECKLIST_FOLLOWUP_END"],
                root["id"] + 2: ["CHECKLIST_FOLLOWUP block=yes\nlvl 3\nCHECKLIST_FOLLOWUP_END"],
                root["id"] + 3: ["CHECKLIST_FOLLOWUP block=yes\nlvl 4\nCHECKLIST_FOLLOWUP_END"],
            },
        )
        config = DriverConfig(max_followup_depth=3)
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            config=config,
        )
        result = await driver.drive()
        assert result.outcome == DriverOutcome.HALTED_FAILURE
        assert "nesting exceeded depth 3" in (result.failure_reason or "")
    finally:
        await conn.close()


# --- silent exit + runtime errors -----------------------------------


@pytest.mark.asyncio
async def test_completed_item_closes_its_leg_session(tmp_path: Path) -> None:
    """When an item completes, its paired leg session should be
    closed so the sidebar moves it into the Closed group rather
    than accumulating one open chat per item."""
    from bearings.db.store import get_session

    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="closeme")
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={item["id"]: ["CHECKLIST_ITEM_DONE"]},
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        await driver.drive()
        # Leg session was created by spawn_leg → closed by _mark_done.
        # The stub's reverse map session_id → item_id is the cleanest
        # way to recover the session id without reading the DB twice.
        leg_session_id = next(
            sid for sid, iid in runtime._session_to_item.items() if iid == item["id"]
        )
        leg_row = await get_session(conn, leg_session_id)
        assert leg_row is not None
        assert leg_row["closed_at"] is not None, "leg session should be closed after item completes"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_completed_run_closes_parent_checklist_session(
    tmp_path: Path,
) -> None:
    """When the last top-level item completes, the parent checklist
    session itself should auto-close — matches the manual toggle_item
    HTTP handler's behavior so autonomous and manual end-states are
    identical."""
    from bearings.db.store import get_session

    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        a = await create_item(conn, checklist_id, label="a", sort_order=0)
        b = await create_item(conn, checklist_id, label="b", sort_order=1)
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                a["id"]: ["CHECKLIST_ITEM_DONE"],
                b["id"]: ["CHECKLIST_ITEM_DONE"],
            },
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        parent = await get_session(conn, checklist_id)
        assert parent is not None
        assert parent["closed_at"] is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_partial_run_leaves_parent_checklist_open(
    tmp_path: Path,
) -> None:
    """If a run halts before every item is done, the parent
    checklist must NOT close — there's still work to do."""
    from bearings.db.store import get_session

    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        a = await create_item(conn, checklist_id, label="a", sort_order=0)
        await create_item(conn, checklist_id, label="b", sort_order=1)
        # Only `a` has a script; `b` would fail. Use max_items_per_run
        # cap to halt cleanly after `a`.
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={a["id"]: ["CHECKLIST_ITEM_DONE"]},
        )
        config = DriverConfig(max_items_per_run=1)
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            config=config,
        )
        result = await driver.drive()
        assert result.outcome == DriverOutcome.HALTED_MAX_ITEMS
        parent = await get_session(conn, checklist_id)
        assert parent is not None
        assert parent["closed_at"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_failure_reason_persists_to_item_notes(tmp_path: Path) -> None:
    """When the driver halts an item with failure, the reason is
    written to `checklist_items.notes` so the existing ChecklistView
    surfaces it without any new UI. Item had no prior notes — the
    note is just the `[auto-run]` line."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="silent-fail")
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={item["id"]: ["just prose, no sentinel"]},
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        await driver.drive()
        refreshed = await get_item(conn, item["id"])
        assert refreshed is not None
        notes = refreshed.get("notes") or ""
        assert notes.startswith("[auto-run]")
        assert "completion sentinel" in notes
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_failure_note_preserves_user_authored_notes(tmp_path: Path) -> None:
    """Pre-existing user notes on the item stay at the top; the
    auto-run failure line is appended after a blank line."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(
            conn,
            checklist_id,
            label="work-item",
            notes="user's original instructions: do X carefully.",
        )
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={item["id"]: ["silent"]},
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        await driver.drive()
        refreshed = await get_item(conn, item["id"])
        assert refreshed is not None
        notes = refreshed["notes"] or ""
        assert notes.startswith("user's original instructions")
        assert "[auto-run]" in notes
        # Separating blank line between the two.
        assert "\n\n[auto-run]" in notes
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_failure_note_replaces_prior_autorun_line(tmp_path: Path) -> None:
    """A second failure run on the same item replaces the first
    `[auto-run]` line rather than stacking. Prevents unbounded
    growth across retries."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="retry-target")
        runtime = StubRuntime(
            conn=conn,
            # Both runs go silent. Fresh run = fresh driver instance
            # each time (the safety-cap handling resets state).
            turns_by_item={item["id"]: ["silent run 1", "silent run 2"]},
        )
        driver1 = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        await driver1.drive()
        first = await get_item(conn, item["id"])
        assert first is not None
        assert (first["notes"] or "").count("[auto-run]") == 1

        # Reset the checked_at (first run didn't check it, but make
        # sure it's unchecked for round 2) and re-run.
        driver2 = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        await driver2.drive()
        second = await get_item(conn, item["id"])
        assert second is not None
        notes = second["notes"] or ""
        assert notes.count("[auto-run]") == 1  # still one, not two
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_silent_agent_exit_halts_failure(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="silent")
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={item["id"]: ["I did some stuff but said nothing."]},
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.HALTED_FAILURE
        assert result.items_failed == 1
        assert "completion sentinel" in (result.failure_reason or "")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_runtime_run_turn_raises_halts_failure(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="exploding")
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={item["id"]: []},
            run_turn_raises_for_item={item["id"]},
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.HALTED_FAILURE
        assert "runtime error" in (result.failure_reason or "")
        # Teardown happens even on the error path — no runner leak.
        assert len(runtime.teardown_calls) == 1
    finally:
        await conn.close()


# --- safety caps ----------------------------------------------------


@pytest.mark.asyncio
async def test_max_items_per_run_halts(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        a = await create_item(conn, checklist_id, label="a", sort_order=0)
        b = await create_item(conn, checklist_id, label="b", sort_order=1)
        c = await create_item(conn, checklist_id, label="c", sort_order=2)
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                a["id"]: ["CHECKLIST_ITEM_DONE"],
                b["id"]: ["CHECKLIST_ITEM_DONE"],
                c["id"]: ["CHECKLIST_ITEM_DONE"],
            },
        )
        config = DriverConfig(max_items_per_run=1)
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            config=config,
        )
        result = await driver.drive()
        assert result.outcome == DriverOutcome.HALTED_MAX_ITEMS
        assert result.items_completed == 1
    finally:
        await conn.close()


# --- stop signal ----------------------------------------------------


@pytest.mark.asyncio
async def test_stop_signal_halts_between_items(tmp_path: Path) -> None:
    """Stop fires from inside a turn on the first item. The driver
    completes that turn (mark done) but halts before picking up the
    next item."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        a = await create_item(conn, checklist_id, label="a", sort_order=0)
        b = await create_item(conn, checklist_id, label="b", sort_order=1)

        class StoppingRuntime(StubRuntime):
            def __init__(self, driver_ref: list[Driver], **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.driver_ref = driver_ref

            async def run_turn(self, *, session_id: str, prompt: str) -> str:
                if self.driver_ref:
                    self.driver_ref[0].stop()
                return await super().run_turn(session_id=session_id, prompt=prompt)

        driver_ref: list[Driver] = []
        runtime = StoppingRuntime(
            driver_ref=driver_ref,
            conn=conn,
            turns_by_item={
                a["id"]: ["CHECKLIST_ITEM_DONE"],
                b["id"]: ["CHECKLIST_ITEM_DONE"],
            },
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        driver_ref.append(driver)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.HALTED_STOP
        # Item A completed before stop was noticed; item B untouched.
        assert result.items_completed == 1
        assert len(runtime.spawn_calls) == 1
        assert runtime.spawn_calls[0][0] == a["id"]
        # Prove item B was never spawned or completed.
        b_refreshed = await get_item(conn, b["id"])
        assert b_refreshed is not None
        assert b_refreshed["checked_at"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_stop_signal_before_drive_exits_immediately(
    tmp_path: Path,
) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        await create_item(conn, checklist_id, label="untouched")
        runtime = StubRuntime(conn=conn)
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        driver.stop()
        result = await driver.drive()
        assert result.outcome == DriverOutcome.HALTED_STOP
        assert runtime.spawn_calls == []
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_stop_from_another_task_halts_before_leg_completes(
    tmp_path: Path,
) -> None:
    """Drive in the main task; a concurrent task fires stop() after
    a short sleep. The driver halts at the next iteration boundary
    after the current turn resolves."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="slow")

        class SleepyRuntime(StubRuntime):
            async def run_turn(self, *, session_id: str, prompt: str) -> str:
                # Give the stop_soon task time to fire before we
                # return.
                await asyncio.sleep(0.05)
                return await super().run_turn(session_id=session_id, prompt=prompt)

        runtime = SleepyRuntime(
            conn=conn,
            turns_by_item={item["id"]: ["CHECKLIST_ITEM_DONE"]},
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)

        async def stop_soon() -> None:
            await asyncio.sleep(0.01)
            driver.stop()

        asyncio.create_task(stop_soon())
        result = await driver.drive()
        # Current item finished (stop was checked after its turn);
        # outer loop next iteration halted on the flag.
        assert result.outcome == DriverOutcome.HALTED_STOP
        assert result.items_completed == 1
    finally:
        await conn.close()


# --- context-pressure watchdog -------------------------------------


@pytest.mark.asyncio
async def test_pressure_nudge_spawns_successor_leg_when_agent_misses_handoff(
    tmp_path: Path,
) -> None:
    """Agent ends a silent turn while leg 1 is at 75% context. Driver
    nudges with an explicit handoff request; the nudge turn produces
    a plug; driver spawns leg 2 with the plug threaded forward."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="heavy")
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                item["id"]: [
                    # Turn 1: silent (no sentinel). Pressure is 75%.
                    "I did some stuff but forgot to emit a sentinel.",
                    # Turn 2: the nudge turn. Agent now emits handoff.
                    "CHECKLIST_HANDOFF\nstate-snapshot-A\nCHECKLIST_HANDOFF_END",
                    # Turn 3: leg 2, done.
                    "CHECKLIST_ITEM_DONE",
                ],
            },
            percentages_by_item={item["id"]: [75.0, 76.0, 5.0]},
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.items_completed == 1
        # Two legs spawned (leg 1 silent, leg 2 done after nudge).
        assert result.legs_spawned == 2
        # The nudge-turn plug was threaded into leg 2's spawn.
        assert runtime.spawn_calls[1][2] == "state-snapshot-A"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_pressure_nudge_honors_item_done_response(tmp_path: Path) -> None:
    """If the agent's nudge-turn response is CHECKLIST_ITEM_DONE
    instead of a handoff, the driver treats the item as complete on
    the current leg — no successor leg spawned."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="ambiguous")
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                item["id"]: [
                    "forgot the sentinel last turn.",
                    "Oh, I was actually done.\nCHECKLIST_ITEM_DONE",
                ],
            },
            percentages_by_item={item["id"]: [70.0, 72.0]},
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.items_completed == 1
        # Only one leg — nudge happened on that leg, not a new one.
        assert result.legs_spawned == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_pressure_nudge_also_silent_halts_failure(tmp_path: Path) -> None:
    """If the nudge turn ALSO produces no sentinel, the driver halts
    with a pressure-specific failure reason so the UI can surface
    'agent refused' rather than the generic silent-exit message."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="stubborn")
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                item["id"]: [
                    "silent turn 1",
                    "silent turn 2 despite being asked",
                ],
            },
            percentages_by_item={item["id"]: [80.0, 85.0]},
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.HALTED_FAILURE
        assert "refused to emit a handoff plug" in (result.failure_reason or "")
        # Two turns fired: original + nudge. No leg cutover (since
        # nudge also silent).
        assert len(runtime.turn_calls) == 2

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_pressure_below_threshold_skips_nudge(tmp_path: Path) -> None:
    """If the leg is at 30% context and the agent goes silent, the
    driver does NOT nudge — low pressure + silent agent = plain
    silent-exit failure (the generic reason, not the pressure one)."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="low-pressure")
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={item["id"]: ["silent, low pressure"]},
            percentages_by_item={item["id"]: [30.0]},
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.HALTED_FAILURE
        # Generic silent-exit reason, NOT the pressure-nudge reason.
        assert "completion sentinel" in (result.failure_reason or "")
        assert "refused" not in (result.failure_reason or "")
        # Only the original turn fired — no nudge.
        assert len(runtime.turn_calls) == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_custom_threshold_via_driver_config(tmp_path: Path) -> None:
    """DriverConfig.handoff_threshold_percent is honored. At 40%
    threshold, a 45% pressure reading triggers the nudge even though
    the default (60%) wouldn't."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="custom-threshold")
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                item["id"]: [
                    "silent",
                    "CHECKLIST_HANDOFF\nunder-default-pressure\nCHECKLIST_HANDOFF_END",
                    "CHECKLIST_ITEM_DONE",
                ],
            },
            percentages_by_item={item["id"]: [45.0, 48.0, 5.0]},
        )
        config = DriverConfig(handoff_threshold_percent=40.0)
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            config=config,
        )
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.legs_spawned == 2
    finally:
        await conn.close()


# --- visit-existing mode -------------------------------------------


@pytest.mark.asyncio
async def test_visit_existing_reuses_linked_session_for_leg_one(
    tmp_path: Path,
) -> None:
    """When `visit_existing_sessions=True` and the item has a linked
    open chat session, the driver runs leg 1 against that session
    without calling spawn_leg or teardown_leg — the user's session
    is theirs, the driver just borrows it for one turn."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="visit-me")
        # Pre-create a chat session and link it to the item.
        existing_chat = await create_session(
            conn,
            working_dir="/tmp",
            model="stub-model",
            kind="chat",
            checklist_item_id=item["id"],
        )
        from bearings.db.store import set_item_chat_session

        await set_item_chat_session(conn, item["id"], existing_chat["id"])
        # Refresh item dict so it carries chat_session_id when the
        # driver looks it up via next_unchecked_top_level_item.
        runtime = StubRuntime(conn=conn)
        # Pre-register the existing session in the stub's reverse map
        # so run_turn can look up the item id.
        runtime._session_to_item[existing_chat["id"]] = item["id"]
        runtime.turns_by_item[item["id"]] = ["CHECKLIST_ITEM_DONE"]
        config = DriverConfig(visit_existing_sessions=True)
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            config=config,
        )
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.items_completed == 1
        # No spawn_leg — the session was the user's. teardown_leg IS
        # called once on the existing session id: this drops any
        # cached runner so the next run_turn rebuilds with the freshly
        # forced bypassPermissions mode (2026-04-25 visit-mode bug 2
        # fix). The session row itself is left intact.
        assert runtime.spawn_calls == []
        assert runtime.teardown_calls == [existing_chat["id"]]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_visit_existing_skips_items_without_linked_session(
    tmp_path: Path,
) -> None:
    """An item with no linked chat session is skipped — counted in
    items_skipped, run advances to the next item. The unchecked
    state stays so the user can revisit it later."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        a = await create_item(conn, checklist_id, label="unlinked", sort_order=0)
        b = await create_item(conn, checklist_id, label="linked", sort_order=1)
        # Only `b` gets a linked session.
        existing_chat = await create_session(
            conn,
            working_dir="/tmp",
            model="stub-model",
            kind="chat",
            checklist_item_id=b["id"],
        )
        from bearings.db.store import set_item_chat_session

        await set_item_chat_session(conn, b["id"], existing_chat["id"])
        runtime = StubRuntime(conn=conn)
        runtime._session_to_item[existing_chat["id"]] = b["id"]
        runtime.turns_by_item[b["id"]] = ["CHECKLIST_ITEM_DONE"]
        config = DriverConfig(visit_existing_sessions=True)
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            config=config,
        )
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.items_completed == 1
        assert result.items_skipped == 1
        # Item `a` stayed unchecked.
        a_refreshed = await get_item(conn, a["id"])
        assert a_refreshed is not None
        assert a_refreshed["checked_at"] is None
        # Item `b` got marked done.
        b_refreshed = await get_item(conn, b["id"])
        assert b_refreshed is not None
        assert b_refreshed["checked_at"] is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_visit_existing_skips_when_linked_session_is_closed(
    tmp_path: Path,
) -> None:
    """A closed linked session counts the same as no link — skip the
    item rather than try to drive a closed session's runner.

    Uses an UNPAIRED chat session (no `checklist_item_id` at create
    time, only forward-link via `set_item_chat_session`). The
    paired-chat close cascade in `close_session` would otherwise
    auto-check the item and close the parent checklist before the
    driver even runs — that's the intended close-cascade behavior for
    real paired chats but it would short-circuit this test."""
    from bearings.db.store import close_session, set_item_chat_session

    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="stale-link")
        existing_chat = await create_session(
            conn,
            working_dir="/tmp",
            model="stub-model",
            kind="chat",
        )
        await set_item_chat_session(conn, item["id"], existing_chat["id"])
        await close_session(conn, existing_chat["id"])
        runtime = StubRuntime(conn=conn)
        config = DriverConfig(visit_existing_sessions=True)
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            config=config,
        )
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.items_completed == 0
        assert result.items_skipped == 1
        assert runtime.spawn_calls == []
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_visit_existing_handoff_spawns_fresh_for_leg_two(
    tmp_path: Path,
) -> None:
    """Visit mode: leg 1 reuses linked session. If that leg hands
    off, leg 2 spawns fresh (the contract is `first leg uses what's
    there, successors are mine`)."""
    from bearings.db.store import set_item_chat_session

    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="legs")
        existing_chat = await create_session(
            conn,
            working_dir="/tmp",
            model="stub-model",
            kind="chat",
            checklist_item_id=item["id"],
        )
        await set_item_chat_session(conn, item["id"], existing_chat["id"])
        runtime = StubRuntime(conn=conn)
        runtime._session_to_item[existing_chat["id"]] = item["id"]
        # Leg 1 = existing session emits handoff; leg 2 (spawned) wraps it up.
        runtime.turns_by_item[item["id"]] = [
            "CHECKLIST_HANDOFF\nstate snapshot\nCHECKLIST_HANDOFF_END",
            "CHECKLIST_ITEM_DONE",
        ]
        config = DriverConfig(visit_existing_sessions=True)
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            config=config,
        )
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.items_completed == 1
        # legs_spawned counts both legs (existing + spawned), but
        # spawn_calls only fires for the second one.
        assert result.legs_spawned == 2
        assert len(runtime.spawn_calls) == 1
        assert runtime.spawn_calls[0][1] == 2  # leg_number=2
        assert runtime.spawn_calls[0][2] == "state snapshot"  # plug threaded
        # Two teardown calls now: (1) existing-session cache drop in
        # _existing_open_session so the rebuilt runner picks up the
        # forced bypassPermissions mode, (2) the spawned leg 2's
        # teardown after its turn. The session ROWS are both left
        # intact in the DB; teardown only drops cached runners.
        spawned_leg_id = next(
            sid
            for sid, iid in runtime._session_to_item.items()
            if iid == item["id"] and sid != existing_chat["id"]
        )
        assert runtime.teardown_calls == [existing_chat["id"], spawned_leg_id]
    finally:
        await conn.close()


# --- visit-existing permission_mode forcing (bug 2 fix) ------------


@pytest.mark.asyncio
async def test_visit_existing_forces_leg_permission_mode_on_session(
    tmp_path: Path,
) -> None:
    """Bug 2 (2026-04-24 unattended-tour permission_prompt halt):
    visit-existing mode reuses a chat session whose permission_mode
    is whatever the user left it at (often 'default' from manual
    interactive use). The driver must FORCE leg_permission_mode
    onto the row before the leg runs, otherwise the SDK's
    `can_use_tool` hook parks on every Edit/Bash and the
    autonomous run hangs waiting for a click that will never come.

    This test verifies the fix: an existing chat session with
    permission_mode=NULL (default) gets bumped to
    'bypassPermissions' (the DriverConfig default) by the time
    the visit happens. Also asserts a teardown_leg call on the
    existing session id — that's the cache-drop signal that
    forces a runner rebuild so the new permission_mode actually
    takes effect this leg.
    """
    from bearings.db.store import get_session, set_item_chat_session

    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="visit-perms")
        existing_chat = await create_session(
            conn,
            working_dir="/tmp",
            model="stub-model",
            kind="chat",
            checklist_item_id=item["id"],
        )
        # Sanity: row starts with permission_mode=None.
        before = await get_session(conn, existing_chat["id"])
        assert before is not None
        assert before["permission_mode"] is None

        await set_item_chat_session(conn, item["id"], existing_chat["id"])
        runtime = StubRuntime(conn=conn)
        runtime._session_to_item[existing_chat["id"]] = item["id"]
        runtime.turns_by_item[item["id"]] = ["CHECKLIST_ITEM_DONE"]
        config = DriverConfig(visit_existing_sessions=True)
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            config=config,
        )
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED

        # Permission mode forced onto the persisted row.
        after = await get_session(conn, existing_chat["id"])
        assert after is not None
        assert after["permission_mode"] == "bypassPermissions"

        # Teardown was called on the existing session id — proves the
        # runner cache was dropped so the rebuilt runner picks up the
        # new mode. Without this, a cached runner with the OLD mode
        # would remain in the registry and the SDK's can_use_tool
        # hook would still park on tool calls.
        assert existing_chat["id"] in runtime.teardown_calls
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_visit_existing_honors_custom_leg_permission_mode(
    tmp_path: Path,
) -> None:
    """A custom DriverConfig.leg_permission_mode (e.g. 'acceptEdits'
    for a mid-ground supervised run) is honored on visit-mode
    sessions just like it is on spawned legs. Symmetry assertion."""
    from bearings.db.store import get_session, set_item_chat_session

    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="custom-mode")
        existing_chat = await create_session(
            conn,
            working_dir="/tmp",
            model="stub-model",
            kind="chat",
            checklist_item_id=item["id"],
        )
        await set_item_chat_session(conn, item["id"], existing_chat["id"])
        runtime = StubRuntime(conn=conn)
        runtime._session_to_item[existing_chat["id"]] = item["id"]
        runtime.turns_by_item[item["id"]] = ["CHECKLIST_ITEM_DONE"]
        config = DriverConfig(
            visit_existing_sessions=True,
            leg_permission_mode="acceptEdits",
        )
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            config=config,
        )
        await driver.drive()
        after = await get_session(conn, existing_chat["id"])
        assert after is not None
        assert after["permission_mode"] == "acceptEdits"
    finally:
        await conn.close()


# --- skip-on-failure mode ------------------------------------------


@pytest.mark.asyncio
async def test_skip_failure_advances_past_silent_item(tmp_path: Path) -> None:
    """With `failure_policy='skip'`, a silent-exit item doesn't halt
    the run — record the failure on its notes and advance to the
    next item. Item stays unchecked."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        a = await create_item(conn, checklist_id, label="silent", sort_order=0)
        b = await create_item(conn, checklist_id, label="ok", sort_order=1)
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                a["id"]: ["I did stuff but said nothing"],
                b["id"]: ["CHECKLIST_ITEM_DONE"],
            },
        )
        config = DriverConfig(failure_policy="skip")
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            config=config,
        )
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.items_completed == 1
        assert result.items_failed == 1
        # Item `a` stayed unchecked but carries a failure note.
        a_refreshed = await get_item(conn, a["id"])
        assert a_refreshed is not None
        assert a_refreshed["checked_at"] is None
        assert "[auto-run]" in (a_refreshed.get("notes") or "")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_skip_failure_does_not_loop_on_failed_item(tmp_path: Path) -> None:
    """A failed-and-skipped item must not be re-picked by the outer
    loop — otherwise the run would loop forever on the same
    uncompleted item. Verify by giving the agent only ONE silent
    turn for the failing item; if it got re-picked, run_turn would
    raise on missing script."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        await create_item(conn, checklist_id, label="silent")
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={1: ["silent, no sentinel"]},  # exactly one script
        )
        config = DriverConfig(failure_policy="skip")
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            config=config,
        )
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.items_completed == 0
        assert result.items_failed == 1
        # Only ONE leg fired — no re-pick loop.
        assert len(runtime.spawn_calls) == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_halt_failure_default_still_halts(tmp_path: Path) -> None:
    """Sanity: default failure_policy='halt' preserves the
    pre-existing first-failure-stops-run behavior."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        await create_item(conn, checklist_id, label="silent", sort_order=0)
        await create_item(conn, checklist_id, label="never-reached", sort_order=1)
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={1: ["silent, no sentinel"]},
        )
        # Default config — failure_policy="halt"
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.HALTED_FAILURE
        # Item 2 was never touched.
        assert len(runtime.spawn_calls) == 1
    finally:
        await conn.close()


# --- shape assertions for the kickoff prompt ----------------------


@pytest.mark.asyncio
async def test_kickoff_prompt_on_first_leg_has_no_plug(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="priminal")
        runtime = StubRuntime(conn=conn, turns_by_item={item["id"]: ["CHECKLIST_ITEM_DONE"]})
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        await driver.drive()
        assert len(runtime.turn_calls) == 1
        prompt = runtime.turn_calls[0][2]
        # No "Previous leg handoff plug" on leg 1.
        assert "Previous leg" not in prompt
        assert "priminal" in prompt
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_kickoff_prompt_on_successor_leg_includes_plug(
    tmp_path: Path,
) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="heavy")
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                item["id"]: [
                    "CHECKLIST_HANDOFF\nmidstate\nCHECKLIST_HANDOFF_END",
                    "CHECKLIST_ITEM_DONE",
                ]
            },
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        await driver.drive()
        assert len(runtime.turn_calls) == 2
        leg_two_prompt = runtime.turn_calls[1][2]
        assert "Previous leg" in leg_two_prompt
        assert "midstate" in leg_two_prompt
    finally:
        await conn.close()
