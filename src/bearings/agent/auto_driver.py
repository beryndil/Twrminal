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
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import aiosqlite

from bearings.agent.checklist_sentinels import Followup
from bearings.agent.checklist_sentinels import parse as parse_sentinels
from bearings.db import store

log = logging.getLogger(__name__)


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
    ) -> None:
        self._conn = conn
        self._runtime = runtime
        self._checklist_id = checklist_session_id
        self._config = config or DriverConfig()
        self._stop = asyncio.Event()
        self._items_completed = 0
        self._items_failed = 0
        self._legs_spawned = 0
        self._failed_item_id: int | None = None
        self._failure_reason: str | None = None

    # --- external control --------------------------------------------

    def stop(self) -> None:
        """Request the driver exit at the next iteration boundary.
        Idempotent — repeated calls are harmless."""
        self._stop.set()

    # --- main loop ---------------------------------------------------

    async def drive(self) -> DriverResult:
        """Run the autonomous loop to a terminal state and return."""
        items_seen = 0
        while True:
            if self._stop.is_set():
                return self._result(DriverOutcome.HALTED_STOP)
            if items_seen >= self._config.max_items_per_run:
                return self._result(DriverOutcome.HALTED_MAX_ITEMS)
            item = await store.next_unchecked_top_level_item(self._conn, self._checklist_id)
            if item is None:
                if self._items_completed == 0:
                    return self._result(DriverOutcome.HALTED_EMPTY)
                return self._result(DriverOutcome.COMPLETED)
            items_seen += 1
            ok = await self._drive_item(item, depth=0)
            if not ok:
                return self._result(DriverOutcome.HALTED_FAILURE)

    # --- per-item state machine --------------------------------------

    async def _drive_item(self, item: dict[str, Any], *, depth: int) -> bool:
        """Work a single item (possibly recursively). Returns True on
        success (item marked done), False on any failure or stop."""
        if depth > self._config.max_followup_depth:
            await self._record_failure(
                item["id"],
                f"followup nesting exceeded depth {self._config.max_followup_depth}",
            )
            return False

        # A prior leg may have left blocking children. Drive them
        # first — the parent can't complete until every child is
        # checked (the toggle cascade enforces this at the storage
        # layer, but the driver needs to respect it explicitly so we
        # don't waste a leg proving the point).
        if not await self._drive_blocking_children(item, depth=depth):
            return False

        plug: str | None = None
        for leg in range(1, self._config.max_legs_per_item + 1):
            if self._stop.is_set():
                return False
            leg_session_id = await self._runtime.spawn_leg(item=item, leg_number=leg, plug=plug)
            self._legs_spawned += 1
            try:
                prompt = self._kickoff_prompt(item, leg, plug)
                assistant_text = await self._runtime.run_turn(
                    session_id=leg_session_id, prompt=prompt
                )
            except Exception as exc:
                # A runtime-raised exception ends the leg as a failure;
                # the item is not retryable via another leg because we
                # don't know the agent's state. Fail-safe halt.
                await self._runtime.teardown_leg(leg_session_id)
                await self._record_failure(
                    item["id"],
                    f"runtime error in leg {leg}: {exc}",
                )
                return False
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
                        return False
                await self._mark_done(item["id"])
                self._items_completed += 1
                return True

            if sentinels.handoff_plug is not None:
                plug = sentinels.handoff_plug
                continue

            if created_blocking:
                # Agent chose to block the item on newly-filed children
                # without marking done or handing off. Drive children,
                # then re-enter the parent (fresh context, no plug —
                # the blocking children's completion is the plug).
                if not await self._drive_blocking_children(item, depth=depth):
                    return False
                plug = None
                continue

            # No done, no handoff, no blocking children. Before calling
            # it a silent-exit failure, check context pressure: if the
            # turn burned enough of the window that the NEXT organic
            # turn is likely to cross the cliff, the agent may just
            # have forgotten the handoff syntax. Nudge once — one extra
            # turn asking explicitly for a handoff plug — and re-parse.
            pct = self._runtime.last_context_percentage(leg_session_id)
            if pct is not None and pct >= self._config.handoff_threshold_percent:
                nudge_text = await self._request_handoff_nudge(leg_session_id)
                nudge_sentinels = parse_sentinels(nudge_text)
                # A nudge-turn followup would be weird (the ask was
                # "just emit the plug") but we honor one if it arrives
                # to avoid losing agent-noted work.
                await self._apply_followups(item, nudge_sentinels.followups)
                if nudge_sentinels.handoff_plug is not None:
                    plug = nudge_sentinels.handoff_plug
                    continue
                if nudge_sentinels.item_done:
                    await self._mark_done(item["id"])
                    self._items_completed += 1
                    return True
                # Nudge also silent — fall through to failure with a
                # reason that distinguishes the pressure case.
                await self._record_failure(
                    item["id"],
                    (
                        f"context at {pct:.1f}% but agent refused to emit "
                        "a handoff plug even when asked explicitly"
                    ),
                )
                return False

            # No done, no handoff, no blocking children, context not
            # under pressure — the agent ended the turn saying
            # nothing. Fail-safe halt.
            await self._record_failure(
                item["id"],
                (
                    "agent ended turn without emitting a completion "
                    "sentinel (CHECKLIST_ITEM_DONE / CHECKLIST_HANDOFF)"
                ),
            )
            return False

        # Max legs exceeded — the agent kept handing off. Something is
        # wrong with how the item is scoped.
        await self._record_failure(
            item["id"],
            f"exceeded max_legs_per_item ({self._config.max_legs_per_item})",
        )
        return False

    async def _drive_blocking_children(self, item: dict[str, Any], *, depth: int) -> bool:
        """Drive every unchecked direct child of `item` to completion.
        Returns True when every child succeeds, False on the first
        failure (the parent can't proceed)."""
        while True:
            if self._stop.is_set():
                return False
            children = await store.list_unchecked_children(self._conn, item["id"])
            if not children:
                return True
            child = children[0]
            ok = await self._drive_item(child, depth=depth + 1)
            if not ok:
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
        await store.toggle_item(self._conn, item_id, checked=True)

    async def _record_failure(self, item_id: int, reason: str) -> None:
        self._items_failed += 1
        # First failure wins — the driver halts on first failure by
        # design, so capturing subsequent ones would be dead code.
        if self._failed_item_id is None:
            self._failed_item_id = item_id
            self._failure_reason = reason
        log.warning("autonomous driver failure on item %s: %s", item_id, reason)

    async def _request_handoff_nudge(self, leg_session_id: str) -> str:
        """Submit one extra turn on the current leg asking the agent
        to emit a handoff plug. Used when the leg's context watchdog
        crossed threshold but the agent didn't spontaneously emit
        CHECKLIST_HANDOFF. Returns the assistant's response text for
        sentinel parsing. Exceptions propagate — the caller treats
        any error as silent-exit failure.

        Kept as a driver method (not runtime) so the prompt text is
        authoritative in one place and test stubs don't have to
        re-implement the nudge shape."""
        return await self._runtime.run_turn(
            session_id=leg_session_id,
            prompt=(
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
            ),
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
            "When the item is complete, emit CHECKLIST_ITEM_DONE on its "
            "own line. If you are approaching context limit, emit\n"
            "CHECKLIST_HANDOFF\n"
            "<your handoff plug>\n"
            "CHECKLIST_HANDOFF_END\n"
            "For followups: CHECKLIST_FOLLOWUP block=yes|no / "
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

    # --- result assembly ---------------------------------------------

    def _result(self, outcome: DriverOutcome) -> DriverResult:
        return DriverResult(
            outcome=outcome,
            items_completed=self._items_completed,
            items_failed=self._items_failed,
            legs_spawned=self._legs_spawned,
            failed_item_id=self._failed_item_id,
            failure_reason=self._failure_reason,
        )
