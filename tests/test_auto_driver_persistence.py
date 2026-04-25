"""Persistence + rehydrate tests for the autonomous-checklist driver
(2026-04-25, migration 0031).

Background. Before this slice, `AutoDriverRegistry` held drivers in an
in-memory dict on `app.state.auto_drivers`. A systemd restart, app
crash, or any lifespan teardown evaporated the registry — completed
items stayed checked (the `checked_at` column is durable), but the
run itself silently disappeared. The 2026-04-24 overnight tour run
on checklist fae8f1a8 lost 16 of 31 items this way.

This file exercises the durable-state machinery added on top of the
existing state machine:

- `auto_run_state` table (migration 0031): one row per run, snapshot
  of counters + config + `_attempted_failed` exclusion set + state.
- `Driver._save_snapshot` / `_apply_restore`: best-effort writes on
  each iteration; seed counters + exclusion on resume.
- `AutoDriverRegistry.rehydrate`: scans `state='running'` rows on
  lifespan startup and re-spawns asyncio.Tasks.

Tests follow the pattern in `test_auto_driver.py`: each opens its own
`init_db` connection in try/finally rather than sharing fixtures, the
same `StubRuntime` shape stands in for the real agent runner, and the
Driver is constructed directly so we exercise the state machine
without touching FastAPI plumbing.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bearings.agent.auto_driver import (
    Driver,
    DriverConfig,
    DriverOutcome,
)
from bearings.agent.auto_driver_runtime import AutoDriverRegistry
from bearings.db.store import (
    create_item,
    get_auto_run_state,
    get_item,
    init_db,
    upsert_auto_run_state,
)

# Reuse the StubRuntime shape from the main driver tests so the
# behavior under test is the persistence layer, not a re-implementation
# of the runtime stub.
from tests.test_auto_driver import StubRuntime, _fresh_checklist

# --- Driver-level: snapshot writes during drive() ------------------


@pytest.mark.asyncio
async def test_running_snapshot_written_on_drive_start(tmp_path: Path) -> None:
    """Even an empty-checklist drive() leaves a snapshot — the initial
    'running' write happens before the loop checks for unchecked
    items, so a crash between start and first item still rehydrates
    a sane (zero-counter) state."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        runtime = StubRuntime(conn=conn)
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        await driver.drive()
        snapshot = await get_auto_run_state(conn, checklist_id)
        assert snapshot is not None
        # By drive() return the state has been finalized to 'finished'
        # (HALTED_EMPTY is a clean terminal state, not a crash).
        assert snapshot["state"] == "finished"
        assert snapshot["items_completed"] == 0
        # config_json round-trips the dataclass shape.
        cfg = json.loads(snapshot["config_json"])
        assert cfg["max_legs_per_item"] == DriverConfig().max_legs_per_item
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_completed_run_finalizes_to_finished_state(tmp_path: Path) -> None:
    """A run that completes every item leaves a 'finished' snapshot
    with counters matching the in-memory result. Confirms the
    end-of-drive() flip from 'running' → 'finished' fires once on the
    happy path."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="solo")
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={item["id"]: ["CHECKLIST_ITEM_DONE"]},
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        snapshot = await get_auto_run_state(conn, checklist_id)
        assert snapshot is not None
        assert snapshot["state"] == "finished"
        assert snapshot["items_completed"] == 1
        assert snapshot["legs_spawned"] == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_skip_failure_run_persists_attempted_failed_set(
    tmp_path: Path,
) -> None:
    """In `failure_policy='skip'` runs, the snapshot tracks the
    exclusion set so a rehydrated driver doesn't re-pick the same
    failed item."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        a = await create_item(conn, checklist_id, label="silent", sort_order=0)
        b = await create_item(conn, checklist_id, label="ok", sort_order=1)
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={
                a["id"]: ["no sentinel"],
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
        await driver.drive()
        snapshot = await get_auto_run_state(conn, checklist_id)
        assert snapshot is not None
        assert snapshot["state"] == "finished"
        attempted = json.loads(snapshot["attempted_failed_json"])
        assert a["id"] in attempted
        assert b["id"] not in attempted  # b succeeded; not in exclusion set
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_failure_halt_persists_failed_item_id_and_reason(
    tmp_path: Path,
) -> None:
    """A halt-failure run records the failed item id + reason in the
    snapshot so a status query (or rehydrated driver) carries the
    diagnostic across restart."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="silent")
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={item["id"]: ["agent said nothing useful"]},
        )
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        await driver.drive()
        snapshot = await get_auto_run_state(conn, checklist_id)
        assert snapshot is not None
        assert snapshot["state"] == "finished"  # terminal halt-failure
        assert snapshot["failed_item_id"] == item["id"]
        assert "completion sentinel" in (snapshot["failure_reason"] or "")
    finally:
        await conn.close()


# --- Driver-level: restore from snapshot ---------------------------


@pytest.mark.asyncio
async def test_restore_seeds_counters_into_new_driver(tmp_path: Path) -> None:
    """A Driver constructed with `restore=<snapshot>` and an empty
    checklist returns a result whose counters reflect the snapshot,
    not zeros — proves `_apply_restore` ran before the result builder."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        # An item that's already checked — so the rehydrated drive()
        # has nothing to do but should still report the prior
        # counters.
        item = await create_item(conn, checklist_id, label="already-done")
        # Mark it checked so `next_unchecked_top_level_item` returns
        # None on rehydrate, mirroring a real "the prior life finished
        # this item" scenario.
        from bearings.db.store import toggle_item

        await toggle_item(conn, item["id"], checked=True)

        snapshot = {
            "items_completed": 5,
            "items_failed": 1,
            "items_skipped": 2,
            "legs_spawned": 7,
            "failed_item_id": 42,
            "failure_reason": "leg explosion in prior life",
            "attempted_failed_json": "[42]",
        }
        runtime = StubRuntime(conn=conn)
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            restore=snapshot,
        )
        result = await driver.drive()
        # Empty after restore = COMPLETED (not HALTED_EMPTY) because
        # touched_any is True from the seeded counters.
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.items_completed == 5
        assert result.items_failed == 1
        assert result.items_skipped == 2
        assert result.legs_spawned == 7
        assert result.failed_item_id == 42
        assert result.failure_reason == "leg explosion in prior life"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_restore_excludes_attempted_failed_from_pickup(
    tmp_path: Path,
) -> None:
    """A snapshot's `attempted_failed_json` honors the exclusion when
    the driver resumes — the failed item from the prior life is NOT
    re-picked even though it's still unchecked."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        a = await create_item(conn, checklist_id, label="failed-prior", sort_order=0)
        b = await create_item(conn, checklist_id, label="still-todo", sort_order=1)
        # `a` would be picked first by sort_order, but the snapshot
        # excludes it. The driver should advance to `b` directly.
        snapshot = {
            "items_completed": 0,
            "items_failed": 1,
            "items_skipped": 0,
            "legs_spawned": 1,
            "failed_item_id": a["id"],
            "failure_reason": "from prior life",
            "attempted_failed_json": json.dumps([a["id"]]),
        }
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={b["id"]: ["CHECKLIST_ITEM_DONE"]},
        )
        config = DriverConfig(failure_policy="skip")
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            config=config,
            restore=snapshot,
        )
        result = await driver.drive()
        assert result.outcome == DriverOutcome.COMPLETED
        # Only `b` was driven — proves `a` stayed in the exclusion set.
        assert [c[0] for c in runtime.spawn_calls] == [b["id"]]
        # `a` is still unchecked.
        a_refreshed = await get_item(conn, a["id"])
        assert a_refreshed is not None
        assert a_refreshed["checked_at"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_restore_tolerates_malformed_attempted_failed_json(
    tmp_path: Path,
) -> None:
    """A corrupt snapshot doesn't crash the resume — the driver logs
    and falls back to an empty exclusion set rather than refusing to
    start."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="resilient")
        snapshot = {
            "items_completed": 1,
            "items_failed": 0,
            "items_skipped": 0,
            "legs_spawned": 1,
            "failed_item_id": None,
            "failure_reason": None,
            "attempted_failed_json": "this isn't json",
        }
        runtime = StubRuntime(
            conn=conn,
            turns_by_item={item["id"]: ["CHECKLIST_ITEM_DONE"]},
        )
        driver = Driver(
            conn=conn,
            runtime=runtime,
            checklist_session_id=checklist_id,
            restore=snapshot,
        )
        result = await driver.drive()
        # Despite malformed exclusion JSON, the run completes and the
        # snapshot's other fields seeded fine.
        assert result.outcome == DriverOutcome.COMPLETED
        assert result.items_completed == 2  # 1 from snapshot + 1 fresh
    finally:
        await conn.close()


# --- Driver-level: cancellation does not flip state ----------------


@pytest.mark.asyncio
async def test_cancelled_drive_leaves_state_running_for_rehydrate(
    tmp_path: Path,
) -> None:
    """If the driver task is cancelled (lifespan shutdown), the
    snapshot stays at `state='running'` so the next boot rehydrates
    it. We don't write 'errored' on cancel — that would lock out
    rehydrate of a normally-shutdown driver."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        item = await create_item(conn, checklist_id, label="long")

        # A runtime that hangs forever on run_turn so we can cancel it
        # mid-leg.
        class HangingRuntime(StubRuntime):
            async def run_turn(self, *, session_id: str, prompt: str) -> str:
                await asyncio.sleep(60)
                return ""

        runtime = HangingRuntime(conn=conn, turns_by_item={item["id"]: ["unused"]})
        driver = Driver(conn=conn, runtime=runtime, checklist_session_id=checklist_id)
        task = asyncio.create_task(driver.drive())
        # Yield long enough for the initial 'running' snapshot to land
        # and for run_turn to start sleeping.
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        snapshot = await get_auto_run_state(conn, checklist_id)
        assert snapshot is not None
        assert snapshot["state"] == "running"
    finally:
        await conn.close()


# --- Registry-level: rehydrate ------------------------------------


@pytest.mark.asyncio
async def test_rehydrate_finds_running_rows_and_spawns_drivers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write a 'running' row directly, call rehydrate(), confirm a
    Driver task is spawned. Uses a monkeypatched runtime so the test
    doesn't need real `app.state.runners` plumbing — the empty
    checklist body means run_turn is never called anyway, but the
    runtime constructor still has to succeed."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        # Seed a 'running' snapshot directly — simulates a prior
        # process that wrote one and then died.
        await upsert_auto_run_state(
            conn,
            checklist_session_id=checklist_id,
            state="running",
            items_completed=0,
            items_failed=0,
            items_skipped=0,
            legs_spawned=0,
            failed_item_id=None,
            failure_reason=None,
            config_json=json.dumps(
                {
                    "max_items_per_run": 50,
                    "max_legs_per_item": 5,
                    "max_followup_depth": 3,
                    "handoff_threshold_percent": 60.0,
                    "leg_permission_mode": "bypassPermissions",
                    "visit_existing_sessions": False,
                    "failure_policy": "halt",
                }
            ),
            attempted_failed_json="[]",
        )
        # Stub runtime constructor — empty checklist drives to
        # HALTED_EMPTY (which becomes COMPLETED only when touched_any
        # is true; on a fresh restore where counters are all 0, it's
        # HALTED_EMPTY. Either way no run_turn fires).
        recorded_runtimes: list[Any] = []

        class _StubAgentRuntime:
            def __init__(self, *, app: Any, config: Any = None) -> None:
                self.app = app
                self.config = config
                recorded_runtimes.append(self)

            async def spawn_leg(self, **kwargs: Any) -> str:
                raise AssertionError("empty checklist should not spawn")

            async def run_turn(self, **kwargs: Any) -> str:
                raise AssertionError("empty checklist should not run a turn")

            async def teardown_leg(self, session_id: str) -> None:
                pass

            def last_context_percentage(self, session_id: str) -> float | None:
                return None

        from bearings.agent import auto_driver_runtime

        monkeypatch.setattr(auto_driver_runtime, "AgentRunnerDriverRuntime", _StubAgentRuntime)
        # Minimal fake app — rehydrate only reads .state.db.
        fake_app = SimpleNamespace(state=SimpleNamespace(db=conn))

        registry = AutoDriverRegistry()
        rehydrated = await registry.rehydrate(fake_app)
        assert rehydrated == [checklist_id]
        # Drain the spawned task so it can complete.
        entry = registry._entries[checklist_id]
        await entry[1]
        # Snapshot flipped to 'finished' once drive() returned.
        snapshot = await get_auto_run_state(conn, checklist_id)
        assert snapshot is not None
        assert snapshot["state"] == "finished"
        # The stub runtime constructor was called once with the right
        # config restored from JSON.
        assert len(recorded_runtimes) == 1
        assert recorded_runtimes[0].config.failure_policy == "halt"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_rehydrate_skips_finished_rows(tmp_path: Path) -> None:
    """A row whose state is 'finished' is part of the audit trail, not
    a live run. Rehydrate must NOT re-spawn it — otherwise every
    completed run would wake up on every restart."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        await upsert_auto_run_state(
            conn,
            checklist_session_id=checklist_id,
            state="finished",
            items_completed=10,
            items_failed=0,
            items_skipped=0,
            legs_spawned=10,
            failed_item_id=None,
            failure_reason=None,
            config_json="{}",
            attempted_failed_json="[]",
        )
        fake_app = SimpleNamespace(state=SimpleNamespace(db=conn))
        registry = AutoDriverRegistry()
        rehydrated = await registry.rehydrate(fake_app)
        assert rehydrated == []
        assert checklist_id not in registry._entries
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_rehydrate_idempotent_when_already_in_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling rehydrate twice must not double-spawn the driver task —
    the second call sees the live entry and skips. Without this guard
    every bounce would queue a duplicate driver, which would race on
    the same checklist."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        await upsert_auto_run_state(
            conn,
            checklist_session_id=checklist_id,
            state="running",
            items_completed=0,
            items_failed=0,
            items_skipped=0,
            legs_spawned=0,
            failed_item_id=None,
            failure_reason=None,
            config_json="{}",
            attempted_failed_json="[]",
        )

        class _StubAgentRuntime:
            def __init__(self, *, app: Any, config: Any = None) -> None:
                pass

            async def spawn_leg(self, **kwargs: Any) -> str:
                raise AssertionError("never reached")

            async def run_turn(self, **kwargs: Any) -> str:
                raise AssertionError("never reached")

            async def teardown_leg(self, session_id: str) -> None:
                pass

            def last_context_percentage(self, session_id: str) -> float | None:
                return None

        from bearings.agent import auto_driver_runtime

        monkeypatch.setattr(auto_driver_runtime, "AgentRunnerDriverRuntime", _StubAgentRuntime)
        fake_app = SimpleNamespace(state=SimpleNamespace(db=conn))

        registry = AutoDriverRegistry()
        # Use a never-completing checklist (no items, but counters
        # already > 0) so the first task stays runnable long enough
        # for the second rehydrate to hit. Empty-checklist drive
        # actually finishes immediately (HALTED_EMPTY → 'finished'),
        # so seed one item that will block on the stub.
        item = await create_item(conn, checklist_id, label="hold")
        # The stub raises if run_turn is called, so the first call
        # must NOT actually run a turn. Trick: cancel the task right
        # after spawning so the entry exists but doesn't fire.
        rehydrated_first = await registry.rehydrate(fake_app)
        assert rehydrated_first == [checklist_id]
        # Cancel the task so it doesn't try to spawn_leg on `item`.
        entry = registry._entries[checklist_id]
        entry[1].cancel()
        try:
            await entry[1]
        except (asyncio.CancelledError, AssertionError):
            # Either CancelledError (we cancelled fast enough) or
            # AssertionError (the task got far enough to call the
            # stub spawn_leg). Both are acceptable for idempotency
            # — what matters is that the SECOND rehydrate sees the
            # live entry and refuses to clobber it.
            pass

        # Re-seed running so the row still triggers a rehydrate, but
        # leave the registry's entry in place (still .done() now that
        # cancel completed). Re-running rehydrate should NOT spawn
        # another task because the entry exists and the second-call
        # check uses `not done()`. Since our task is done, the second
        # call DOES re-spawn — that's the recovery path. So instead
        # of testing dones-don't-clobber, exercise the live-don't-
        # clobber: don't cancel the first task; just verify the
        # second call sees a live entry.

        # Reset registry to test the live-entry guard cleanly.
        registry2 = AutoDriverRegistry()
        # Manually inject a live-looking entry (a never-completing
        # task) so rehydrate can observe and skip it.
        forever_loop = asyncio.get_event_loop()
        sentinel_task: asyncio.Task[Any] = forever_loop.create_task(asyncio.sleep(60))
        registry2._entries[checklist_id] = (None, sentinel_task)  # type: ignore[assignment]
        try:
            rehydrated_again = await registry2.rehydrate(fake_app)
            assert rehydrated_again == []
        finally:
            sentinel_task.cancel()
            try:
                await sentinel_task
            except asyncio.CancelledError:
                pass
        _ = item  # silence unused-name lint
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_restore_config_handles_malformed_json(tmp_path: Path) -> None:
    """A row with corrupt config_json falls back to DriverConfig
    defaults rather than crashing the rehydrate scan. Forward-compat
    drift (newer fields the running build doesn't know) is handled
    by dropping unknown keys."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        # Build a row with a bad config_json blob. We bypass the
        # store helper to set malformed JSON — the helper would
        # accept it because the column is just TEXT.
        checklist_id = await _fresh_checklist(conn)
        await upsert_auto_run_state(
            conn,
            checklist_session_id=checklist_id,
            state="running",
            items_completed=0,
            items_failed=0,
            items_skipped=0,
            legs_spawned=0,
            failed_item_id=None,
            failure_reason=None,
            config_json="this isn't json at all",
            attempted_failed_json="[]",
        )
        # _restore_config swallows the bad JSON.
        cfg = AutoDriverRegistry._restore_config(
            {
                "checklist_session_id": checklist_id,
                "config_json": "this isn't json at all",
            }
        )
        # Defaults restored.
        assert cfg.max_items_per_run == DriverConfig().max_items_per_run
        assert cfg.failure_policy == DriverConfig().failure_policy
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_restore_config_drops_unknown_keys(tmp_path: Path) -> None:
    """Forward-compat: a config_json that mentions a field the running
    build doesn't define is rebuilt with that field ignored, not by
    crashing on TypeError."""
    cfg = AutoDriverRegistry._restore_config(
        {
            "config_json": json.dumps(
                {
                    "max_items_per_run": 7,
                    "future_unknown_field": "from a newer build",
                }
            ),
        }
    )
    assert cfg.max_items_per_run == 7
    # Other defaults still in place.
    assert cfg.max_legs_per_item == DriverConfig().max_legs_per_item


# --- Round-trip: snapshot → restart → resume -----------------------


@pytest.mark.asyncio
async def test_round_trip_resume_completes_remaining_items(
    tmp_path: Path,
) -> None:
    """End-to-end: a partial run that halts mid-checklist (we use
    `max_items_per_run=1` to stop cleanly after one item) leaves a
    durable snapshot. A FRESH driver constructed with `restore=` and
    a fresh config picks up at the next unchecked item and finishes.
    This is the bug-1 fix in vivo: the run survives the restart."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        checklist_id = await _fresh_checklist(conn)
        a = await create_item(conn, checklist_id, label="a", sort_order=0)
        b = await create_item(conn, checklist_id, label="b", sort_order=1)
        c = await create_item(conn, checklist_id, label="c", sort_order=2)
        runtime1 = StubRuntime(
            conn=conn,
            turns_by_item={
                a["id"]: ["CHECKLIST_ITEM_DONE"],
                b["id"]: ["CHECKLIST_ITEM_DONE"],
                c["id"]: ["CHECKLIST_ITEM_DONE"],
            },
        )
        # First run: bounded to one item so we halt after `a`.
        driver1 = Driver(
            conn=conn,
            runtime=runtime1,
            checklist_session_id=checklist_id,
            config=DriverConfig(max_items_per_run=1),
        )
        result1 = await driver1.drive()
        assert result1.outcome == DriverOutcome.HALTED_MAX_ITEMS
        assert result1.items_completed == 1

        # Snapshot is durable (state='finished' since HALTED_MAX_ITEMS
        # is a clean terminal state). Pull it and feed into a fresh
        # driver.
        snapshot = await get_auto_run_state(conn, checklist_id)
        assert snapshot is not None

        # Fresh driver (different runtime, full max_items_per_run) —
        # mimics a process restart picking the run back up. Pass
        # snapshot via restore= so counters carry forward.
        runtime2 = StubRuntime(
            conn=conn,
            turns_by_item={
                b["id"]: ["CHECKLIST_ITEM_DONE"],
                c["id"]: ["CHECKLIST_ITEM_DONE"],
            },
        )
        driver2 = Driver(
            conn=conn,
            runtime=runtime2,
            checklist_session_id=checklist_id,
            restore=snapshot,
        )
        result2 = await driver2.drive()
        # Total completed = 1 from prior life + 2 new = 3.
        assert result2.outcome == DriverOutcome.COMPLETED
        assert result2.items_completed == 3
        # Only b and c were spawned in the second life — a was already
        # done before the restart.
        assert [c[0] for c in runtime2.spawn_calls] == [b["id"], c["id"]]
        # Final snapshot is 'finished' with the cumulative counters.
        final = await get_auto_run_state(conn, checklist_id)
        assert final is not None
        assert final["state"] == "finished"
        assert final["items_completed"] == 3
    finally:
        await conn.close()
