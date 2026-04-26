"""Autonomous checklist driver — the state machine that walks a
`kind='checklist'` session to completion without human input.

The driver is deliberately split from its runtime binding. This module
owns the loop, the sentinel interpretation, the safety caps, and the
persistence of outcomes. A `DriverRuntime` Protocol abstracts the
three things the driver needs from the outside world (spawn a leg,
run a turn, tear down a leg) so unit tests can drive the whole state
machine with a stub and the real implementation can wire in the
`SessionRunner` + registry in its own slice.

### Shape

For each top-level unchecked item, in `sort_order`:

1. If the item already has incomplete children (from a prior
   blocking-followup turn), recurse into them first.
2. Spawn a paired chat session (`leg 1`) linked to the item.
3. Submit a kickoff prompt and await the turn's final assistant
   message.
4. Parse the message for sentinels (`CHECKLIST_ITEM_DONE`,
   `CHECKLIST_HANDOFF`, `CHECKLIST_FOLLOWUP`).
5. On handoff → tear down the leg, spawn `leg 2` with the plug as
   the kickoff context, loop.
6. On blocking followups → create child items, recurse into them
   before the parent can complete.
7. On non-blocking followups → append them at the top-level end of
   the checklist; the outer loop picks them up later.
8. On `item_done` → mark the item checked and advance.
9. On silent exit (no sentinel) → halt (fail-safe default).

Safety caps enforced here, not at the runtime boundary:
- `max_items_per_run` — total top-level items the driver will touch.
- `max_legs_per_item` — handoff cutovers before giving up on an item.
- `max_followup_depth` — nesting depth for blocking followups before
  the driver refuses to recurse further.

An external `.stop()` signal is checked between iterations so the
driver exits cleanly without stranding a mid-turn leg.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Protocol

import aiosqlite

from bearings.agent.checklist_sentinels import Followup
from bearings.agent.checklist_sentinels import parse as parse_sentinels
from bearings.db import store

log = logging.getLogger(__name__)


class _ItemOutcome(StrEnum):
    """Per-item completion state surfaced from `_drive_item` to
    `drive`. The outer loop reads this to decide:

    - DONE → advance, item is checked.
    - FAILED → work was attempted but didn't complete; honor
      `failure_policy` (halt vs skip-and-advance).
    - SKIPPED → no work attempted (e.g. visit-existing mode hit an
      item with no linked session); advance unconditionally,
      regardless of failure_policy. Must still be added to the
      exclusion set so the SAME item isn't re-picked next iteration
      (which would loop forever).
    """

    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class DriverOutcome(StrEnum):
    """Terminal states the driver can reach. Every `.drive()` call
    returns exactly one of these in its `DriverResult`."""

    COMPLETED = "completed"
    # Nothing was unchecked when the driver started — no-op exit.
    HALTED_EMPTY = "halted_empty"
    # An item failed (silent exit, too many legs, nested too deep,
    # or the runtime raised). `failed_item_id` + `failure_reason`
    # carry the detail.
    HALTED_FAILURE = "halted_failure"
    HALTED_MAX_ITEMS = "halted_max_items"
    HALTED_STOP = "halted_stop"


@dataclass
class DriverResult:
    """Outcome snapshot returned by `Driver.drive()`."""

    outcome: DriverOutcome
    items_completed: int
    items_failed: int
    legs_spawned: int
    # Items the driver chose not to attempt. In visit-existing mode,
    # an item with no linked chat session contributes a skip rather
    # than a failure; in skip-failure mode, items that fail to
    # complete are also recorded as `items_failed` AND the loop
    # advances rather than halting. `items_skipped` covers only the
    # "no work attempted" case so the two counters stay distinct.
    items_skipped: int = 0
    failed_item_id: int | None = None
    failure_reason: str | None = None


@dataclass
class DriverConfig:
    """Safety caps. Defaults are conservative — loud failures are
    better than runaway loops in an autonomous context.

    `max_items_per_run`: total top-level items the driver will touch
    before halting. Catches both "checklist someone accidentally made
    huge" and "non-blocking followups regenerated enough work to
    loop forever."

    `max_legs_per_item`: handoff cutovers per item. At 5 legs, the
    item is consuming 5x a context window — something is wrong with
    how it's scoped.

    `max_followup_depth`: nesting depth for blocking followups. The
    default 3 matches the design note in TODO.md — deeper than that
    and the agent is using the checklist as a task queue, not a
    focused work item.
    """

    max_items_per_run: int = 50
    max_legs_per_item: int = 5
    max_followup_depth: int = 3
    # Context-pressure watchdog threshold (percent 0-100). When a leg's
    # last ContextUsage event crosses this percentage AND the agent's
    # turn produced no handoff sentinel, the driver injects a nudge
    # turn asking for a handoff plug BEFORE treating the quiet turn as
    # a silent-exit failure. 60% leaves room for the handoff turn
    # itself + a couple of look-up tool calls; matches Dave's manual
    # handoff discipline (hand off early, not at the cliff).
    handoff_threshold_percent: float = 60.0
    # PermissionMode for leg sessions. The whole point of autonomous
    # mode is unattended execution, so the default is `bypassPermissions`
    # — every tool call auto-approves. Without this, the SDK's
    # `can_use_tool` hook parks on every Edit/Bash, and a leg trying to
    # land its work waits forever for a UI click that will never come.
    # Override to "acceptEdits" if you want file edits auto-approved
    # but other tools still gated (interactive mid-ground), or to
    # "default" if the leg is supposed to be supervised after all.
    leg_permission_mode: str = "bypassPermissions"
    # Visit-existing-sessions mode. When True, the driver's first leg
    # for each item REUSES the session already linked via
    # `checklist_items.chat_session_id` instead of spawning a new
    # one. Items with no linked session (or a closed one) are skipped
    # — counted in `items_skipped`, the outer loop advances. Handoff
    # legs (after CHECKLIST_HANDOFF) still spawn fresh as usual; the
    # contract is "first leg uses what's there, successors are mine".
    # Use this for tour-style runs over a pre-curated set of paired
    # chats: each item already has a session containing the relevant
    # context, the driver just walks them in order.
    visit_existing_sessions: bool = False
    # Failure policy. "halt" (default) ends the run on first failure,
    # matching the conservative autonomous-mode default. "skip"
    # records the failure on the item, leaves it unchecked, and
    # advances to the next — useful for tour mode where you want the
    # driver to do everything it can and leave hard items for human
    # review rather than stopping the whole run.
    failure_policy: str = "halt"


class DriverRuntime(Protocol):
    """Everything the driver needs from the surrounding app.

    `spawn_leg` creates a new paired chat `sessions` row for the
    item (kind='chat', checklist_item_id=item['id']) and whatever
    runner infrastructure the surrounding app needs to execute a
    turn against it. Returns the new session id.

    `run_turn` submits one prompt to the leg's runner and awaits
    the end of the assistant turn. Returns the assistant's final
    message body — the text the sentinel parser interprets.
    Exceptions propagate to the driver as leg failures.

    `teardown_leg` stops the runner for a leg (keeps the DB row
    for the audit trail). Called from both happy-path and error
    paths so implementations should be idempotent.
    """

    async def spawn_leg(
        self,
        *,
        item: dict[str, Any],
        leg_number: int,
        plug: str | None,
    ) -> str: ...

    async def run_turn(
        self,
        *,
        session_id: str,
        prompt: str,
    ) -> str: ...

    async def teardown_leg(self, session_id: str) -> None: ...

    def last_context_percentage(self, session_id: str) -> float | None:
        """Return the most recent ContextUsage percentage (0..100)
        captured for `session_id`, or None if no ContextUsage event
        has been observed yet. The driver polls this after each
        `run_turn` to decide whether to inject a handoff-request
        nudge turn. Implementations that can't surface context
        pressure (e.g. test stubs that don't care) return None to
        opt out of the pressure-check branch."""
        ...


class Driver:
    """Autonomous checklist driver. One per `drive()` invocation.

    Construct with a live DB connection, a runtime implementation,
    and the checklist session id. Call `drive()` to run to a
    terminal state. Call `stop()` from another task (a stop button,
    a signal handler) to cut the loop short — the driver finishes
    any in-flight runtime call, tears down the leg, and returns
    `HALTED_STOP`.
    """

    def __init__(
        self,
        *,
        conn: aiosqlite.Connection,
        runtime: DriverRuntime,
        checklist_session_id: str,
        config: DriverConfig | None = None,
        restore: dict[str, Any] | None = None,
    ) -> None:
        self._conn = conn
        self._runtime = runtime
        self._checklist_id = checklist_session_id
        self._config = config or DriverConfig()
        self._stop = asyncio.Event()
        self._items_completed = 0
        self._items_failed = 0
        self._items_skipped = 0
        self._legs_spawned = 0
        self._failed_item_id: int | None = None
        self._failure_reason: str | None = None
        # Set of item ids that the driver has already attempted and
        # failed under skip-failure mode. They stay unchecked in the
        # DB (per the "leave it open" request), but the outer loop
        # must not re-pick them, or the run would loop forever on
        # the same uncompleted item. Excluded from
        # `next_unchecked_top_level_item` lookups.
        self._attempted_failed: set[int] = set()
        # Rehydrate primer. When the registry rebuilds a driver from a
        # persisted `auto_run_state` row it passes the snapshot dict
        # here; `drive()` seeds counters + `_attempted_failed` from it
        # before entering the main loop. The DB-backed `checked_at`
        # column is the source of truth for which items finished —
        # we DON'T try to resume a leg mid-turn — so resume = restored
        # bookkeeping + outer loop picks up at the next unchecked item.
        self._restore: dict[str, Any] | None = restore

    # --- external control --------------------------------------------

    def stop(self) -> None:
        """Request the driver exit at the next iteration boundary.
        Idempotent — repeated calls are harmless."""
        self._stop.set()

    # --- main loop ---------------------------------------------------

    async def drive(self) -> DriverResult:
        """Run the autonomous loop to a terminal state and return.

        With `failure_policy="halt"` (default), the first item that
        fails to complete halts the run with `HALTED_FAILURE`. With
        `failure_policy="skip"`, the failure is recorded on the item
        but the outer loop advances — useful for tour-style runs
        where you want the driver to do everything it can and leave
        hard items for human review.

        Persistence: writes a `state='running'` row into `auto_run_state`
        on entry and re-snapshots after every per-item outcome so a
        lifespan teardown leaves the rehydrate path enough to rebuild.
        On terminal return the row is flipped to `state='finished'`;
        on an unexpected exception it's flipped to `state='errored'`.
        `asyncio.CancelledError` does NOT flip the state — a cancel is
        almost always a shutdown, and we want the next boot to
        rehydrate. See migration 0031 for the table contract.
        """
        if self._restore is not None:
            self._apply_restore()
        await self._save_snapshot("running")
        try:
            result = await self._drive_loop()
        except asyncio.CancelledError:
            # Shutdown path. Leave the row at 'running' so the next
            # boot rehydrates this driver.
            raise
        except BaseException:
            await self._save_snapshot("errored")
            raise
        await self._save_snapshot("finished")
        return result

    async def _drive_loop(self) -> DriverResult:
        """Inner loop, separate from `drive()` so the outer wrapper can
        own the persistence finalize step without three return paths
        each duplicating the snapshot call."""
        items_seen = 0
        skip_failures = self._config.failure_policy == "skip"
        while True:
            if self._stop.is_set():
                return self._result(DriverOutcome.HALTED_STOP)
            if items_seen >= self._config.max_items_per_run:
                return self._result(DriverOutcome.HALTED_MAX_ITEMS)
            item = await store.next_unchecked_top_level_item(
                self._conn,
                self._checklist_id,
                exclude_ids=self._attempted_failed or None,
            )
            if item is None:
                # HALTED_EMPTY = the run started against a checklist
                # that had no unchecked items. After we've touched
                # ANYTHING (completed, skipped, or failed-and-recorded
                # in skip mode), the run made progress and the right
                # outcome is COMPLETED. Without this, a run that
                # records only failures would surprise the user with
                # "nothing was here" — wrong, plenty was there, the
                # agent just couldn't finish it.
                touched_any = (
                    self._items_completed > 0 or self._items_skipped > 0 or self._items_failed > 0
                )
                if not touched_any:
                    return self._result(DriverOutcome.HALTED_EMPTY)
                return self._result(DriverOutcome.COMPLETED)
            items_seen += 1
            outcome = await self._drive_item(item, depth=0)
            if outcome == _ItemOutcome.FAILED:
                if not skip_failures:
                    return self._result(DriverOutcome.HALTED_FAILURE)
                # Skip-mode failure: record the item id so the next
                # `next_unchecked_top_level_item` lookup excludes it
                # — without this guard the same uncompleted item gets
                # re-picked forever.
                self._attempted_failed.add(int(item["id"]))
            elif outcome == _ItemOutcome.SKIPPED:
                # Skip is unconditional advance (independent of
                # failure_policy) but the item still needs exclusion
                # to avoid re-pick.
                self._attempted_failed.add(int(item["id"]))
            # Snapshot once per outer iteration — captures every
            # counter mutation that just happened (item completion,
            # skip, failure record, attempted_failed add). Cheap on
            # SQLite WAL; keeps the rehydrate primer current to
            # within one item.
            await self._save_snapshot("running")

    # --- per-item state machine --------------------------------------

    async def _drive_item(self, item: dict[str, Any], *, depth: int) -> _ItemOutcome:
        """Work a single item (possibly recursively). Returns one of
        DONE / FAILED / SKIPPED so the outer loop can apply the
        right policy:

        - DONE: item is checked, advance.
        - FAILED: item couldn't complete; halt (default) or advance
          (failure_policy=skip).
        - SKIPPED: item was deliberately not attempted (visit-mode
          with no linked session); always advance.
        """
        if depth > self._config.max_followup_depth:
            await self._record_failure(
                item["id"],
                f"followup nesting exceeded depth {self._config.max_followup_depth}",
            )
            return _ItemOutcome.FAILED

        # A prior leg may have left blocking children. Drive them
        # first — the parent can't complete until every child is
        # checked (the toggle cascade enforces this at the storage
        # layer, but the driver needs to respect it explicitly so we
        # don't waste a leg proving the point).
        if not await self._drive_blocking_children(item, depth=depth):
            return _ItemOutcome.FAILED

        # Visit-existing mode: leg 1 uses the session already linked
        # to this item via `chat_session_id`, if one exists and is
        # open. Items with no usable existing session are skipped
        # entirely — recorded in `items_skipped` and the outer loop
        # advances. Handoff legs (leg 2+) still spawn fresh as usual;
        # the contract is "first leg uses what's there, successors
        # are mine".
        existing_for_leg_one: str | None = None
        if self._config.visit_existing_sessions:
            existing_for_leg_one = await self._existing_open_session(item)
            if existing_for_leg_one is None:
                # No usable existing session. The skip-when-unlinked
                # rule applies only to TOP-LEVEL user-curated items
                # (the visit-existing contract is "walk a curated set
                # of pre-paired chats"). A nested child item — created
                # by the driver itself when a parent emitted
                # CHECKLIST_BLOCKED / CHECKLIST_FOLLOWUP block=yes —
                # has no pre-existing chat by construction; it's a
                # fresh fix-it session the driver needs to spawn. Fall
                # through to the spawn path for those (the leg loop
                # below will spawn_leg since existing_for_leg_one is
                # still None). Top-level unlinked items still skip.
                if item.get("parent_item_id") is None:
                    self._items_skipped += 1
                    log.info(
                        "autonomous driver: skipping item %s — no open chat "
                        "session linked (visit_existing_sessions=True)",
                        item["id"],
                    )
                    return _ItemOutcome.SKIPPED

        plug: str | None = None
        # Labels of blocking children resolved in the most recent
        # iteration. Non-empty means "we just finished a fix-and-return
        # blocker cycle; this leg is the parent resuming." Drives the
        # continuation-prompt path below and the visit-existing
        # reentry decision (reuse the original session so the agent's
        # in-context memory of what it was trying isn't thrown away).
        resolved_blocker_labels: list[str] = []
        for leg in range(1, self._config.max_legs_per_item + 1):
            if self._stop.is_set():
                return _ItemOutcome.FAILED
            # Three scenarios for which session this leg runs against:
            #
            # 1. Visit-existing leg 1 — reuse the session linked via
            #    `chat_session_id`. Already established above.
            # 2. Visit-existing parent reentry after blocker fixes —
            #    REUSE the same existing session id so the agent
            #    picks up where it left off with full memory of what
            #    it was trying. The fix-and-return contract ("go back
            #    to the first session"). Requires the existing
            #    session is still open; if it closed mid-blocker
            #    (rare — close cascade on an unrelated path), fall
            #    through to spawn-fresh.
            # 3. Anything else (spawn-fresh mode, visit-existing
            #    handoff legs, blocker reentry when the original
            #    session is gone) — spawn a fresh leg.
            leg_was_spawned = True
            visit_reentry = False
            if leg == 1 and existing_for_leg_one is not None:
                leg_session_id = existing_for_leg_one
                leg_was_spawned = False
            elif (
                resolved_blocker_labels
                and existing_for_leg_one is not None
                and await self._existing_session_still_open(existing_for_leg_one)
            ):
                leg_session_id = existing_for_leg_one
                leg_was_spawned = False
                visit_reentry = True
            else:
                leg_session_id = await self._runtime.spawn_leg(item=item, leg_number=leg, plug=plug)
            self._legs_spawned += 1
            try:
                if visit_reentry:
                    prompt = self._continuation_prompt(item, resolved_blocker_labels)
                else:
                    prompt = self._kickoff_prompt(item, leg, plug)
                # Consume the resolved-labels carry so a subsequent
                # iteration that doesn't follow a blocker cycle uses
                # the kickoff prompt path.
                resolved_blocker_labels = []
                assistant_text = await self._runtime.run_turn(
                    session_id=leg_session_id, prompt=prompt
                )
            except Exception as exc:
                # A runtime-raised exception ends the leg as a failure;
                # the item is not retryable via another leg because we
                # don't know the agent's state. Fail-safe halt.
                if leg_was_spawned:
                    await self._runtime.teardown_leg(leg_session_id)
                await self._record_failure(
                    item["id"],
                    f"runtime error in leg {leg}: {exc}",
                )
                return _ItemOutcome.FAILED
            if leg_was_spawned:
                await self._runtime.teardown_leg(leg_session_id)

            sentinels = parse_sentinels(assistant_text)
            created_blocking = await self._apply_followups(item, sentinels.followups)

            if sentinels.item_done:
                # If the agent tried to file blocking followups AND
                # call itself done, honor blocking-first: drive the
                # children, then mark done. The toggle cascade ensures
                # the parent's checked_at only sticks when children
                # are all checked, but we want both flags set in the
                # order the agent implied.
                if created_blocking:
                    if not await self._drive_blocking_children(item, depth=depth):
                        return _ItemOutcome.FAILED
                await self._mark_done(item["id"])
                self._items_completed += 1
                return _ItemOutcome.DONE

            if sentinels.handoff_plug is not None:
                plug = sentinels.handoff_plug
                continue

            if created_blocking:
                # Agent chose to block the item on newly-filed children
                # without marking done or handing off. Drive the
                # children, then re-enter the parent.
                #
                # Capture the just-filed blocker labels BEFORE driving
                # so the next iteration can use them in the
                # continuation prompt ("the blocker(s) you raised
                # have been resolved: ..."). In visit-existing mode
                # the next iteration also reuses the same existing
                # session id so the agent's prior context (what it
                # was trying, what it had ruled out) carries forward.
                resolved_blocker_labels = [fu.label for fu in sentinels.followups if fu.blocking]
                if not await self._drive_blocking_children(item, depth=depth):
                    return _ItemOutcome.FAILED
                plug = None
                continue

            # No done, no handoff, no blocking children. Before calling
            # it a silent-exit failure, ALWAYS nudge once. This used to
            # fire only under context pressure on the assumption that
            # silent-exits below the handoff threshold meant the agent
            # had genuinely nothing to say — but the L4.1 leg on
            # 2026-04-26 disproved that: an agent answered design
            # questions in normal prose, ended its turn without a
            # sentinel, and the run halted at low context. The nudge is
            # cheap (one extra turn) and recovers the common
            # forgot-the-sentinel failure mode. We adapt the prompt to
            # the pressure state so the agent knows whether HANDOFF or
            # DONE is the more likely missing sentinel; the agent is
            # free to emit either regardless.
            pct = self._runtime.last_context_percentage(leg_session_id)
            under_pressure = pct is not None and pct >= self._config.handoff_threshold_percent
            nudge_text = await self._request_completion_nudge(
                leg_session_id, under_pressure=under_pressure
            )
            nudge_sentinels = parse_sentinels(nudge_text)
            # A nudge-turn followup would be unusual (the ask was
            # "just emit a sentinel") but we honor one if it arrives
            # to avoid losing agent-noted work.
            await self._apply_followups(item, nudge_sentinels.followups)
            if nudge_sentinels.item_done:
                await self._mark_done(item["id"])
                self._items_completed += 1
                return _ItemOutcome.DONE
            if nudge_sentinels.handoff_plug is not None:
                plug = nudge_sentinels.handoff_plug
                continue
            # Nudge also silent — fall through to failure. Two reason
            # strings so the UI can distinguish "stubbornly refused
            # under pressure" from "still didn't realize the sentinel
            # protocol applied at low context."
            if under_pressure:
                assert pct is not None
                reason = (
                    f"context at {pct:.1f}% but agent refused to emit "
                    "a handoff plug even when asked explicitly"
                )
            else:
                reason = (
                    "agent ended turn without emitting a completion "
                    "sentinel (CHECKLIST_ITEM_DONE / CHECKLIST_HANDOFF); "
                    "nudge response also produced no sentinel"
                )
            await self._record_failure(item["id"], reason)
            return _ItemOutcome.FAILED

        # Max legs exceeded — the agent kept handing off. Something is
        # wrong with how the item is scoped.
        await self._record_failure(
            item["id"],
            f"exceeded max_legs_per_item ({self._config.max_legs_per_item})",
        )
        return _ItemOutcome.FAILED

    async def _drive_blocking_children(self, item: dict[str, Any], *, depth: int) -> bool:
        """Drive every unchecked direct child of `item` to completion.
        Returns True when every child succeeds, False on the first
        failure (the parent can't proceed). A child SKIPPED outcome
        also blocks the parent — a blocking child the driver couldn't
        even attempt is still incomplete from the parent's POV."""
        while True:
            if self._stop.is_set():
                return False
            children = await store.list_unchecked_children(self._conn, item["id"])
            if not children:
                return True
            child = children[0]
            child_outcome = await self._drive_item(child, depth=depth + 1)
            if child_outcome != _ItemOutcome.DONE:
                return False

    async def _apply_followups(self, item: dict[str, Any], followups: list[Followup]) -> bool:
        """Create checklist items for each followup.

        Blocking followups are appended as children of `item` (via
        `parent_item_id`) and will be driven before the parent can
        complete. Non-blocking followups become top-level items at
        the end of the list and are picked up by the outer loop.

        Returns True if any blocking children were created on this
        call — signals the per-item loop to recurse before advancing.
        """
        created_blocking = False
        for fu in followups:
            if fu.blocking:
                await store.create_item(
                    self._conn,
                    item["checklist_id"],
                    label=fu.label,
                    parent_item_id=item["id"],
                )
                created_blocking = True
            else:
                await store.create_item(
                    self._conn,
                    item["checklist_id"],
                    label=fu.label,
                )
        return created_blocking

    async def _mark_done(self, item_id: int) -> None:
        """Mark the item checked. The session-close cascade lives in
        `store.toggle_item` (since 2026-04-25) so both the autonomous
        driver and the manual UI toggle land the same end-state:
        every paired leg auto-closes when an item becomes checked,
        and the parent checklist session auto-closes when the whole
        list completes. This method stays as a one-liner so the
        driver's call sites read intent (`_mark_done`) rather than
        the storage primitive."""
        await store.toggle_item(self._conn, item_id, checked=True)

    async def _record_failure(self, item_id: int, reason: str) -> None:
        self._items_failed += 1
        # First failure wins — the driver halts on first failure by
        # design, so capturing subsequent ones would be dead code.
        if self._failed_item_id is None:
            self._failed_item_id = item_id
            self._failure_reason = reason
        log.warning("autonomous driver failure on item %s: %s", item_id, reason)
        # Persist the reason into the item's `notes` column so the
        # ChecklistView can render it beside the item without any new
        # UI wiring — existing notes rendering already surfaces
        # whatever's here. Prepend with a `[auto-run]` marker so a
        # re-run can find and replace the prior failure entry
        # without clobbering user-authored notes above it.
        await self._persist_failure_note(item_id, reason)

    async def _persist_failure_note(self, item_id: int, reason: str) -> None:
        """Write the failure reason into `checklist_items.notes`.

        If the item already carries user-authored notes, the failure
        line is appended after a blank line so the agent's original
        instruction stays at the top. If a prior `[auto-run]` line
        exists (from an earlier run), it's stripped before the new
        one is added — we only keep the most recent failure to avoid
        notes growing unbounded across retries.

        Best-effort: persistence failures are logged and swallowed.
        The driver's in-memory `failure_reason` is the source of truth
        for the HTTP status endpoint; the note is a UI convenience."""
        try:
            item = await store.get_item(self._conn, item_id)
            if item is None:
                return
            existing = item.get("notes") or ""
            # Strip any prior auto-run line (from a previous halted
            # run on the same item).
            cleaned = "\n".join(
                line for line in existing.splitlines() if not line.startswith("[auto-run]")
            ).rstrip()
            note_line = f"[auto-run] {reason}"
            new_notes = f"{cleaned}\n\n{note_line}" if cleaned else note_line
            await store.update_item(self._conn, item_id, fields={"notes": new_notes})
        except Exception:
            log.exception(
                "autonomous driver: failed to persist failure note for item %s",
                item_id,
            )

    def _apply_restore(self) -> None:
        """Seed in-memory state from a persisted `auto_run_state` row.

        Called once from `drive()` before the main loop when the
        registry rebuilt the driver from a rehydrate scan. The DB-
        backed `checked_at` column is the source of truth for which
        items are done, so we DON'T re-mark anything; we just restore
        the bookkeeping the outer loop needs to behave the same way it
        would have if the original driver had kept running:
        counters (so the status endpoint shows the running totals),
        failure detail (so a halt-failure run that crashed mid-write
        doesn't lose its reason), and `_attempted_failed` (so
        skip-mode runs don't loop on items already failed in the
        prior life of this run).
        """
        snap = self._restore
        if snap is None:
            return
        self._items_completed = int(snap.get("items_completed") or 0)
        self._items_failed = int(snap.get("items_failed") or 0)
        self._items_skipped = int(snap.get("items_skipped") or 0)
        self._legs_spawned = int(snap.get("legs_spawned") or 0)
        failed_id = snap.get("failed_item_id")
        self._failed_item_id = int(failed_id) if failed_id is not None else None
        self._failure_reason = snap.get("failure_reason")
        attempted_raw = snap.get("attempted_failed_json") or "[]"
        try:
            attempted = json.loads(attempted_raw)
            if isinstance(attempted, list):
                self._attempted_failed = {int(x) for x in attempted}
        except (ValueError, TypeError):
            log.warning(
                "autonomous driver: malformed attempted_failed_json on restore "
                "for checklist %s — discarding exclusion set",
                self._checklist_id,
            )
            self._attempted_failed = set()

    async def _save_snapshot(self, state: str) -> None:
        """Persist the current in-memory bookkeeping into
        `auto_run_state`. Best-effort — exceptions are logged and
        swallowed so a write failure (locked DB, disk full, schema
        drift) never crashes the running driver. The in-memory state
        stays authoritative for the live status endpoint; this row
        exists strictly so a fresh-boot lifespan can rehydrate.

        See migration 0031 for the table contract; `state` must be
        one of 'running', 'finished', 'errored'.
        """
        try:
            await store.upsert_auto_run_state(
                self._conn,
                checklist_session_id=self._checklist_id,
                state=state,
                items_completed=self._items_completed,
                items_failed=self._items_failed,
                items_skipped=self._items_skipped,
                legs_spawned=self._legs_spawned,
                failed_item_id=self._failed_item_id,
                failure_reason=self._failure_reason,
                config_json=json.dumps(asdict(self._config)),
                attempted_failed_json=json.dumps(sorted(self._attempted_failed)),
            )
        except Exception:
            log.exception(
                "autonomous driver: failed to persist run-state snapshot "
                "for checklist %s (state=%s)",
                self._checklist_id,
                state,
            )

    async def _existing_open_session(self, item: dict[str, Any]) -> str | None:
        """Return the open chat session linked to `item`, or None.

        Used in visit-existing mode to decide leg 1's session. The
        item dict already carries `chat_session_id` (set by the
        manual "Work on this" path or by `PATCH /items/{id}` in tour
        mode). We re-fetch the session row here to also gate on
        `closed_at` — a closed session would yield a runner the user
        can't see in the open sidebar list, and trying to drive an
        SDK turn against it is not useful.

        Returns the session id when there's an open chat session
        linked to this item; None when no link, the link is stale
        (session deleted), or the linked session is closed.

        Side effect (2026-04-25 fix for unattended-run permission gap):
        before returning the session id, force its `permission_mode`
        to the driver's `leg_permission_mode` (default
        `bypassPermissions`) and drop any cached runner so the next
        `run_turn` rebuilds with the new mode. Without this the
        existing session's pre-set permission_mode (often `default`
        from manual interactive use) would carry into the autonomous
        run and the SDK's `can_use_tool` hook would park on every
        Edit/Bash, hanging the leg forever. Spawned legs get the same
        mode set in `AgentRunnerDriverRuntime.spawn_leg`; this branch
        is the visit-existing equivalent.
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
        run_turn call useless return False so the caller falls back
        to spawning a fresh leg. Defensive: the parent's session
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

        Used whenever a leg's main turn ends without `item_done`,
        `handoff_plug`, or blocking followups. Two prompt variants:

        - **`under_pressure=True`**: leg is past
          `handoff_threshold_percent`. Lead with the handoff ask
          (most likely cause), but accept DONE / BLOCKED if the
          agent actually meant one of those.
        - **`under_pressure=False`**: leg is below threshold. The
          agent probably finished the work and forgot the sentinel,
          OR ended its turn talking to the user when it should have
          handed off. Lead with the DONE ask, accept HANDOFF /
          BLOCKED if applicable.

        Returns the assistant's response text for sentinel parsing.
        Exceptions propagate — the caller treats any error as
        silent-exit failure.

        Kept as a driver method (not runtime) so the prompt text is
        authoritative in one place and test stubs don't have to
        re-implement the nudge shape."""
        if under_pressure:
            prompt = (
                "You're approaching the context window limit on this "
                "leg. Do NOT continue working on the checklist item "
                "this turn. Instead, emit a handoff plug so a "
                "successor leg (fresh context) can finish:\n\n"
                "CHECKLIST_HANDOFF\n"
                "<what you've done, what's left, files touched, "
                "anything the successor MUST NOT redo>\n"
                "CHECKLIST_HANDOFF_END\n\n"
                "If you're actually done with the item, emit "
                "CHECKLIST_ITEM_DONE instead. Do one or the other, "
                "nothing else."
            )
        else:
            prompt = (
                "Your last turn ended without a checklist sentinel. "
                "The autonomous driver needs one to advance. Pick the "
                "one that matches reality and emit it now:\n\n"
                "- If the item is complete, emit CHECKLIST_ITEM_DONE "
                "on its own line.\n"
                "- If you need a fresh context window to continue, "
                "emit CHECKLIST_HANDOFF / <plug> / "
                "CHECKLIST_HANDOFF_END.\n"
                "- If a precondition is broken and you can't proceed, "
                "emit CHECKLIST_BLOCKED / <what's broken> / "
                "CHECKLIST_BLOCKED_END.\n\n"
                "Do not continue the work in this reply — emit the "
                "sentinel and stop."
            )
        return await self._runtime.run_turn(
            session_id=leg_session_id,
            prompt=prompt,
        )

    # --- prompts -----------------------------------------------------

    def _kickoff_prompt(
        self,
        item: dict[str, Any],
        leg: int,
        plug: str | None,
    ) -> str:
        """Per-leg kickoff prompt. This is what the agent sees as its
        first user turn on each leg. The sentinel grammar is described
        inline so the agent doesn't need to be separately briefed.

        The text is deliberately terse — the agent already has the
        checklist-context system-prompt layer from `prompt.py` when
        the leg session has `checklist_item_id` set, so repeating the
        parent-list context here would be noise."""
        sentinel_doc = (
            "When the item is complete, emit CHECKLIST_ITEM_DONE on "
            "its own line. Bias hard toward making the call yourself: "
            "decisions, scope choices, judgment calls, 'pick one of "
            "three tracks' items are agent work. Read the context, "
            "weigh the tradeoffs, write a short rationale, pick. The "
            "user can override by unchecking; bailing on a decision "
            "you could have made wastes the run.\n"
            "If you are approaching context limit, emit\n"
            "CHECKLIST_HANDOFF\n"
            "<your handoff plug>\n"
            "CHECKLIST_HANDOFF_END\n"
            "If a precondition is broken and an agent could fix it "
            "(broken migration, missing config, failing test that "
            "blocks the real work), emit\n"
            "CHECKLIST_BLOCKED\n"
            "<what's broken and what needs fixing>\n"
            "CHECKLIST_BLOCKED_END\n"
            "A blocker spawns a fix-it session; once that completes, "
            "you are resumed in this same chat to finish the work. "
            "Do NOT use BLOCKED for items you could just do yourself "
            "— that's a different kind of bailing.\n"
            "For other followups: CHECKLIST_FOLLOWUP block=yes|no / "
            "CHECKLIST_FOLLOWUP_END. block=yes makes it a child that "
            "must complete before this item. block=no appends to the "
            "end of the checklist."
        )
        if plug is not None:
            return (
                f"You are continuing checklist item {item['id']}: "
                f"{item['label']}\n\n"
                "Previous leg handoff plug:\n"
                "---\n"
                f"{plug}\n"
                "---\n\n"
                "Resume from the plug and complete the item.\n\n"
                f"{sentinel_doc}"
            )
        return f"Work on checklist item {item['id']}: {item['label']}\n\n{sentinel_doc}"

    def _continuation_prompt(
        self,
        item: dict[str, Any],
        resolved_blocker_labels: list[str],
    ) -> str:
        """Re-entry prompt for visit-existing parent resume after a
        blocker fix. Keeps the message short — the agent already has
        the full sentinel doc from the kickoff and full memory of
        what it was trying — and names the resolved blockers so the
        agent knows the fixes landed and can verify before continuing.

        Used only after `CHECKLIST_BLOCKED` (or
        `CHECKLIST_FOLLOWUP block=yes`) resolves. Spawn-fresh mode
        doesn't reach this branch — fresh legs use the kickoff
        prompt with `plug=None`."""
        if len(resolved_blocker_labels) == 1:
            blocker_summary = (
                f"the blocker you raised has been resolved:\n  - {resolved_blocker_labels[0]}"
            )
        else:
            bullets = "\n".join(f"  - {label}" for label in resolved_blocker_labels)
            blocker_summary = f"the blockers you raised have been resolved:\n{bullets}"
        return (
            f"Returning to checklist item {item['id']}: {item['label']}.\n\n"
            f"While you were paused, {blocker_summary}\n\n"
            "Verify the fix(es) landed as expected, then continue the "
            "original work. When done, emit CHECKLIST_ITEM_DONE."
        )

    # --- result assembly ---------------------------------------------

    def _result(self, outcome: DriverOutcome) -> DriverResult:
        return DriverResult(
            outcome=outcome,
            items_completed=self._items_completed,
            items_failed=self._items_failed,
            legs_spawned=self._legs_spawned,
            items_skipped=self._items_skipped,
            failed_item_id=self._failed_item_id,
            failure_reason=self._failure_reason,
        )
