"""``Driver`` — autonomous checklist walker.

Per ``docs/architecture-v1.md`` §1.1.4 + §2.1 the ``Driver`` is a
single canonical class (no mixins). It owns the outer-loop walk over a
checklist's unchecked items, per-item leg dispatch via the injected
:class:`DriverRuntime`, sentinel parsing per turn, item-state
transitions, and the durable run-row counters via
:mod:`bearings.db.auto_driver_runs`.

Per ``docs/behavior/checklists.md`` the user observes:

* Start picks the lowest-sort_order unchecked item, transitions to
  running, and the status line ticks live.
* Sentinels (``item_done`` / ``handoff`` / ``followup_*`` /
  ``item_blocked`` / ``item_failed``) drive the per-item state
  transitions.
* Safety caps (max legs per item, max items per run, max followup
  depth) honor the constants in
  :mod:`bearings.config.constants`.
* Stop is a soft halt — the in-flight turn finishes and the driver
  transitions to ``finished`` with outcome ``Halted: stopped by user``.
* Skip-current marks the current item ``skipped`` and advances.

The Driver does NOT import :mod:`bearings.web` (per arch §3 layer
rules); the FastAPI-aware factory glue lives in
:mod:`bearings.agent.auto_driver_runtime`.
"""

from __future__ import annotations

import asyncio
import logging

import aiosqlite

from bearings.agent.auto_driver_types import (
    DriverConfig,
    DriverOutcome,
    DriverResult,
    DriverRuntime,
    StopRequested,
)
from bearings.agent.sentinel import SentinelFinding, first_terminal, parse
from bearings.config.constants import (
    AUTO_DRIVER_FAILURE_POLICY_HALT,
    AUTO_DRIVER_STATE_FINISHED,
    AUTO_DRIVER_STATE_PAUSED,
    AUTO_DRIVER_STATE_RUNNING,
    CHECKLIST_DRIVER_PRESSURE_NUDGE_TEXT,
    ITEM_OUTCOME_BLOCKED,
    ITEM_OUTCOME_FAILED,
    ITEM_OUTCOME_SKIPPED,
    PAIRED_CHAT_SPAWNED_BY_DRIVER,
    SENTINEL_KIND_FOLLOWUP_BLOCKING,
    SENTINEL_KIND_FOLLOWUP_NONBLOCKING,
    SENTINEL_KIND_HANDOFF,
    SENTINEL_KIND_ITEM_BLOCKED,
    SENTINEL_KIND_ITEM_DONE,
    SENTINEL_KIND_ITEM_FAILED,
)
from bearings.db import auto_driver_runs as runs_db
from bearings.db import checklists as checklists_db
from bearings.db.checklists import ChecklistItem

_LOG = logging.getLogger(__name__)

# First-leg prompt template the driver hands to ``run_turn`` when no
# predecessor handoff plug exists. The body is a literal-and-document
# block: tells the agent the item label, notes, and reminds it to emit
# a terminal sentinel. The wording is observable to the user in the
# leg's chat (it surfaces as the first user-bubble) so it is pinned
# here, not inline.
_FIRST_LEG_PROMPT_TEMPLATE: str = (
    "You are working on checklist item: {label}\n\n"
    "Item notes:\n{notes}\n\n"
    "When you complete the item emit:\n"
    '  <bearings:sentinel kind="item_done" />\n\n'
    "When you need to hand off to a successor leg emit:\n"
    '  <bearings:sentinel kind="handoff"><plug>YOUR PLUG HERE</plug></bearings:sentinel>\n\n'
    "When the item is blocked outside agent reach emit:\n"
    '  <bearings:sentinel kind="item_blocked"><category>blocked</category>'
    "<text>WHY</text></bearings:sentinel>\n\n"
    "Begin."
)

# Successor-leg prompt — fed when the predecessor emitted a handoff
# sentinel. The plug body is what the predecessor wrote; the
# instruction reminds the new leg of the terminal-sentinel contract.
_HANDOFF_LEG_PROMPT_TEMPLATE: str = (
    "Successor leg for checklist item: {label}\n\n"
    "Predecessor's handoff plug:\n{plug}\n\n"
    "When you complete the item emit:\n"
    '  <bearings:sentinel kind="item_done" />\n\n'
    "Continue."
)

# Per-turn nudge prompt the driver sends when an assistant message
# produced no sentinel. The wording is fixed per arch (one nudge before
# treating the quiet turn as silent-exit).
_QUIET_TURN_PROMPT: str = (
    "No actionable sentinel detected. Either emit a terminal sentinel "
    "or continue working — but emit a sentinel before this leg ends."
)


class Driver:
    """Single canonical autonomous-checklist driver.

    Construction takes the durable run id (created upstream by the
    route handler / start-flow), the in-memory :class:`DriverConfig`,
    the :class:`DriverRuntime` binding, and the
    :class:`aiosqlite.Connection` for the run-state writes.

    The outer loop in :meth:`drive` walks unchecked items in
    sort_order until terminal. Per-item dispatch happens in
    :meth:`_drive_item`. Per-turn sentinel parsing + state transition
    happens in :meth:`_run_leg_turns`.

    Stop is signalled via :meth:`request_stop` (cooperative — the
    next safe boundary in the loop sees the flag and raises
    :class:`StopRequested`).
    """

    def __init__(
        self,
        *,
        run_id: int,
        checklist_id: str,
        config: DriverConfig,
        runtime: DriverRuntime,
        connection: aiosqlite.Connection,
    ) -> None:
        if not checklist_id:
            raise ValueError("Driver.checklist_id must be non-empty")
        self._run_id = run_id
        self._checklist_id = checklist_id
        self._config = config
        self._runtime = runtime
        self._connection = connection
        self._stop = asyncio.Event()
        self._skip_current = asyncio.Event()
        # Per-run counters mirrored from the run row so the inner loop
        # avoids re-querying on every tick.
        self._items_completed = 0
        self._items_failed = 0
        self._items_blocked = 0
        self._items_skipped = 0
        self._items_attempted = 0
        self._legs_spawned = 0
        # Per-item leg session ids — used to teardown all legs at
        # halt time.
        self._leg_session_ids: list[str] = []

    # -- public control surface --------------------------------------

    @property
    def run_id(self) -> int:
        """Durable run id; the route handler queries this for status."""
        return self._run_id

    @property
    def checklist_id(self) -> str:
        """Checklist session id this driver is walking."""
        return self._checklist_id

    @property
    def config(self) -> DriverConfig:
        """Read-only configuration snapshot."""
        return self._config

    def request_stop(self) -> None:
        """Cooperative stop — the next safe boundary halts the loop."""
        self._stop.set()

    def request_skip_current(self) -> None:
        """Mark the current item ``skipped`` and advance after this turn."""
        self._skip_current.set()

    # -- outer loop --------------------------------------------------

    async def drive(self) -> DriverResult:
        """Walk the checklist; return the terminal :class:`DriverResult`.

        The loop:

        1. Pick the next unchecked, non-blocked, non-skipped item in
           sort order.
        2. If none, terminate ``Completed`` (or ``Halted: empty`` when
           no items existed at start).
        3. Else drive that item via :meth:`_drive_item`.
        4. Honor max_items_per_run cap.
        5. On :class:`StopRequested` terminate ``Halted: stopped by
           user``.
        """
        try:
            return await self._drive_loop()
        except StopRequested:
            return await self._finalize(
                state=AUTO_DRIVER_STATE_FINISHED,
                outcome=DriverOutcome.HALTED_STOPPED,
                outcome_reason=None,
            )

    async def _drive_loop(self) -> DriverResult:
        """Inner loop body — split out so :meth:`drive` is the catch
        boundary for :class:`StopRequested`."""
        # First-time emptiness check — distinguishes "Halted: empty"
        # (no items existed) from "Completed" (every item completed).
        initial_pending = await self._next_pending_item()
        if initial_pending is None:
            return await self._finalize(
                state=AUTO_DRIVER_STATE_FINISHED,
                outcome=DriverOutcome.HALTED_EMPTY,
                outcome_reason=None,
            )
        next_item: ChecklistItem | None = initial_pending
        while next_item is not None:
            self._raise_if_stopped()
            if self._items_attempted >= self._config.max_items_per_run:
                return await self._finalize(
                    state=AUTO_DRIVER_STATE_FINISHED,
                    outcome=DriverOutcome.HALTED_MAX_ITEMS,
                    outcome_reason=None,
                )
            outcome = await self._drive_item(next_item)
            if outcome is not None:
                return outcome
            next_item = await self._next_pending_item()
        return await self._finalize(
            state=AUTO_DRIVER_STATE_FINISHED,
            outcome=DriverOutcome.COMPLETED,
            outcome_reason=None,
        )

    async def _next_pending_item(self) -> ChecklistItem | None:
        """Lowest-sort_order leaf item that is neither checked nor
        terminally blocked/failed/skipped.

        Per behavior/checklists.md the driver walks "unchecked items in
        sort order"; per the same doc parents are not work units (their
        check state is derived from children). We materialise the full
        item list, find the first leaf whose ``checked_at`` and
        ``blocked_at`` are both NULL.
        """
        items = await checklists_db.list_for_checklist(self._connection, self._checklist_id)
        # Build child-set so leaf filter is one in-memory pass.
        parents: set[int] = set()
        for item in items:
            if item.parent_item_id is not None:
                parents.add(item.parent_item_id)
        for item in items:
            if item.id in parents:
                continue
            if item.checked_at is not None or item.blocked_at is not None:
                continue
            return item
        return None

    # -- per-item dispatch -------------------------------------------

    async def _resolve_leg_session_id(
        self, item: ChecklistItem, leg_number: int, plug: str | None
    ) -> str:
        """Return an existing or freshly-spawned leg session id."""
        if self._config.visit_existing and leg_number == 1 and item.chat_session_id:
            _LOG.debug(
                "visit_existing: reusing session %r for item %d",
                item.chat_session_id,
                item.id,
            )
            return item.chat_session_id
        return await self._runtime.spawn_leg(
            item_id=item.id,
            leg_number=leg_number,
            plug=plug,
        )

    async def _handle_item_failed_outcome(
        self, item: ChecklistItem, outcome: SentinelFinding
    ) -> DriverResult | None:
        """Record a failed outcome; return a DriverResult only on halt policy."""
        await checklists_db.mark_outcome(
            self._connection,
            item.id,
            category=ITEM_OUTCOME_FAILED,
            reason=outcome.reason,
        )
        self._items_failed += 1
        await self._save_counters(clear_current_item=True)
        if self._config.failure_policy == AUTO_DRIVER_FAILURE_POLICY_HALT:
            return await self._finalize(
                state=AUTO_DRIVER_STATE_FINISHED,
                outcome=DriverOutcome.halted_failure(item.id),
                outcome_reason=outcome.reason,
            )
        return None

    async def _handle_leg_cap(
        self, item: ChecklistItem, last_failed_reason: str | None
    ) -> DriverResult | None:
        """Handle max_legs_per_item exceeded; return DriverResult on halt policy."""
        reason = (
            f"max_legs_per_item exceeded ({self._config.max_legs_per_item}); "
            f"last failed reason: {last_failed_reason or 'n/a'}"
        )
        await checklists_db.mark_outcome(
            self._connection,
            item.id,
            category=ITEM_OUTCOME_FAILED,
            reason=reason,
        )
        self._items_failed += 1
        await self._save_counters(clear_current_item=True)
        if self._config.failure_policy == AUTO_DRIVER_FAILURE_POLICY_HALT:
            return await self._finalize(
                state=AUTO_DRIVER_STATE_FINISHED,
                outcome=DriverOutcome.halted_failure(item.id),
                outcome_reason=reason,
            )
        return None

    async def _drive_item(self, item: ChecklistItem) -> DriverResult | None:
        """Drive one item to a per-item terminal state.

        Returns a :class:`DriverResult` only if the run as a whole
        terminates inside this method (e.g. halt-on-failure under
        ``halt`` policy); otherwise returns ``None`` and the caller
        picks the next pending item.
        """
        self._items_attempted += 1
        await self._save_counters(current_item_id=item.id)
        leg_number = await checklists_db.count_legs(self._connection, item.id) + 1
        plug: str | None = None  # populated on handoff
        last_failed_reason: str | None = None
        for _ in range(self._config.max_legs_per_item):
            self._raise_if_stopped()
            if self._skip_current.is_set():
                self._skip_current.clear()
                await self._record_skip(item, reason="skip-current requested")
                return None
            leg_session_id = await self._resolve_leg_session_id(item, leg_number, plug)
            self._leg_session_ids.append(leg_session_id)
            self._legs_spawned += 1
            await checklists_db.record_leg(
                self._connection,
                checklist_item_id=item.id,
                chat_session_id=leg_session_id,
                spawned_by=PAIRED_CHAT_SPAWNED_BY_DRIVER,
                leg_number=leg_number,
            )
            await checklists_db.set_paired_chat(
                self._connection, item.id, chat_session_id=leg_session_id
            )
            await self._save_counters(current_item_id=item.id)
            outcome = await self._run_leg_turns(
                item=item,
                leg_session_id=leg_session_id,
                handoff_plug=plug,
            )
            await self._runtime.teardown_leg(leg_session_id=leg_session_id)
            if outcome.kind == SENTINEL_KIND_ITEM_DONE:
                await checklists_db.mark_checked(self._connection, item.id)
                self._items_completed += 1
                await self._save_counters(clear_current_item=True)
                return None
            if outcome.kind == SENTINEL_KIND_HANDOFF:
                plug = outcome.plug or ""
                leg_number += 1
                continue
            if outcome.kind == SENTINEL_KIND_ITEM_BLOCKED:
                await checklists_db.mark_outcome(
                    self._connection,
                    item.id,
                    category=outcome.category or ITEM_OUTCOME_BLOCKED,
                    reason=outcome.reason,
                )
                self._items_blocked += 1
                await self._save_counters(clear_current_item=True)
                return None
            if outcome.kind == SENTINEL_KIND_ITEM_FAILED:
                last_failed_reason = outcome.reason
                return await self._handle_item_failed_outcome(item, outcome)
        # Exited the loop without a terminal-resolving sentinel —
        # max_legs_per_item exceeded.
        return await self._handle_leg_cap(item, last_failed_reason)

    async def _record_skip(self, item: ChecklistItem, *, reason: str) -> None:
        """Mark ``item`` skipped + bump the counter + clear current."""
        await checklists_db.mark_outcome(
            self._connection,
            item.id,
            category=ITEM_OUTCOME_SKIPPED,
            reason=reason,
        )
        self._items_skipped += 1
        await self._save_counters(clear_current_item=True)

    # -- per-leg turn loop -------------------------------------------

    async def _run_leg_turns(
        self,
        *,
        item: ChecklistItem,
        leg_session_id: str,
        handoff_plug: str | None,
    ) -> SentinelFinding:
        """Loop turns on the leg until a terminal sentinel surfaces.

        On a quiet turn (no sentinel) AND context-pressure has crossed
        the watchdog threshold, inject ONE nudge per
        behavior/checklists.md §"Pressure-watchdog handoff request"
        before treating the next quiet turn as silent-exit failure.
        Returns a synthetic ``item_failed`` finding when the leg
        produces nothing actionable within ``max_turns_per_leg``.
        """
        prompt = self._first_prompt(item=item, handoff_plug=handoff_plug)
        nudge_used = False
        for _ in range(self._config.max_turns_per_leg):
            self._raise_if_stopped()
            if self._skip_current.is_set():
                # Bubble up via a synthetic skipped sentinel so the
                # outer loop records it; reset the flag at the call
                # site that observes it.
                self._skip_current.clear()
                await self._record_skip(item, reason="skip-current requested mid-leg")
                return SentinelFinding(
                    kind=SENTINEL_KIND_ITEM_BLOCKED,
                    category=ITEM_OUTCOME_SKIPPED,
                    reason="skip-current requested mid-leg",
                )
            body = await self._runtime.run_turn(leg_session_id=leg_session_id, prompt=prompt)
            findings = parse(body)
            terminal = first_terminal(findings)
            if terminal is not None:
                await self._apply_followups(item=item, findings=findings, depth=0)
                return terminal
            # No terminal sentinel — apply any non-terminal followups
            # the agent emitted before deciding next action.
            await self._apply_followups(item=item, findings=findings, depth=0)
            pressure = self._runtime.last_context_percentage(leg_session_id)
            if (
                not nudge_used
                and pressure is not None
                and pressure >= self._config.pressure_handoff_threshold_pct
            ):
                nudge_used = True
                prompt = CHECKLIST_DRIVER_PRESSURE_NUDGE_TEXT
                continue
            prompt = _QUIET_TURN_PROMPT
        # Exhausted turn budget — synthesise a failure for the outer
        # loop to handle per failure policy.
        return SentinelFinding(
            kind=SENTINEL_KIND_ITEM_FAILED,
            reason=f"leg_turn_cap_exceeded ({self._config.max_turns_per_leg} turns)",
        )

    def _first_prompt(
        self,
        *,
        item: ChecklistItem,
        handoff_plug: str | None,
    ) -> str:
        """Build the first user-prompt for a leg — handoff if present."""
        if handoff_plug is not None:
            return _HANDOFF_LEG_PROMPT_TEMPLATE.format(
                label=item.label,
                plug=handoff_plug or "(none)",
            )
        return _FIRST_LEG_PROMPT_TEMPLATE.format(
            label=item.label,
            notes=item.notes or "(none)",
        )

    # -- followup handling -------------------------------------------

    async def _apply_followups(
        self,
        *,
        item: ChecklistItem,
        findings: list[SentinelFinding],
        depth: int,
    ) -> None:
        """Append followup items as the agent requested.

        Per behavior/checklists.md:
        * ``followup_blocking`` → child item under current.
        * ``followup_nonblocking`` → sibling at end of checklist.
        * Blocking-followup nesting beyond ``max_followup_depth`` is
          treated as a malformed sentinel and ignored.
        """
        if depth >= self._config.max_followup_depth:
            return
        for finding in findings:
            label = finding.label
            if finding.kind == SENTINEL_KIND_FOLLOWUP_BLOCKING and label:
                await checklists_db.create(
                    self._connection,
                    checklist_id=self._checklist_id,
                    label=label,
                    parent_item_id=item.id,
                )
            elif finding.kind == SENTINEL_KIND_FOLLOWUP_NONBLOCKING and label:
                await checklists_db.create(
                    self._connection,
                    checklist_id=self._checklist_id,
                    label=label,
                    parent_item_id=None,
                )

    # -- internal helpers --------------------------------------------

    def _raise_if_stopped(self) -> None:
        """Translate the stop event into the control-flow exception."""
        if self._stop.is_set():
            raise StopRequested

    async def _save_counters(
        self,
        *,
        current_item_id: int | None = None,
        clear_current_item: bool = False,
    ) -> None:
        """Mirror the in-memory counters into the durable run row."""
        await runs_db.update_counters(
            self._connection,
            self._run_id,
            items_completed=self._items_completed,
            items_failed=self._items_failed,
            items_blocked=self._items_blocked,
            items_skipped=self._items_skipped,
            items_attempted=self._items_attempted,
            legs_spawned=self._legs_spawned,
            current_item_id=current_item_id,
            clear_current_item=clear_current_item,
        )

    async def _finalize(
        self,
        *,
        state: str,
        outcome: str,
        outcome_reason: str | None,
    ) -> DriverResult:
        """Stamp run-row terminal state + return the :class:`DriverResult`."""
        # If the run is currently paused (cooperative-pause flow) the
        # state machine doesn't permit ``paused → finished`` directly
        # without first traversing ``running``; bump back to running so
        # finalize's transition is legal. The user's stop signal is the
        # cause either way.
        existing = await runs_db.get(self._connection, self._run_id)
        if existing is not None and existing.state == AUTO_DRIVER_STATE_PAUSED:
            await runs_db.update_state(
                self._connection, self._run_id, state=AUTO_DRIVER_STATE_RUNNING
            )
        await runs_db.finalize(
            self._connection,
            self._run_id,
            state=state,
            outcome=outcome,
            outcome_reason=outcome_reason,
        )
        await self._save_counters(clear_current_item=True)
        return DriverResult(
            outcome=outcome,
            outcome_reason=outcome_reason,
            items_completed=self._items_completed,
            items_failed=self._items_failed,
            items_blocked=self._items_blocked,
            items_skipped=self._items_skipped,
            items_attempted=self._items_attempted,
            legs_spawned=self._legs_spawned,
            legs=list(self._leg_session_ids),
        )


__all__ = ["Driver"]
