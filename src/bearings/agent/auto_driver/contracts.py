"""Public types for the autonomous checklist driver.

Split out of ``auto_driver.py`` (§FileSize). The dataclasses, enums,
and protocol live here; behavior lives in the sibling mixin modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class _ItemOutcome(StrEnum):
    """Per-item completion state surfaced from ``_drive_item`` to
    ``drive``. The outer loop reads this to decide:

    - DONE → advance, item is checked.
    - FAILED → work was attempted but didn't complete; honor
      ``failure_policy`` (halt vs skip-and-advance).
    - SKIPPED → no work attempted (e.g. visit-existing mode hit an
      item with no linked session); advance unconditionally,
      regardless of failure_policy. Must still be added to the
      exclusion set so the SAME item isn't re-picked next iteration
      (which would loop forever).
    """

    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    # Item is genuinely outside the agent's reach (pay a bill, plug
    # in hardware, supply a 2FA code) and Dave must act. Distinct
    # from FAILED: the paired session stays open for Dave, the run
    # advances regardless of `failure_policy`, and the item shows up
    # in the awaiting axis of the sidebar. See sentinel grammar in
    # `checklist_sentinels.py` and migration 0033.
    BLOCKED = "blocked"


class DriverOutcome(StrEnum):
    """Terminal states the driver can reach. Every ``.drive()`` call
    returns exactly one of these in its ``DriverResult``."""

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
    """Outcome snapshot returned by ``Driver.drive()``."""

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
    # Items the agent flagged as `CHECKLIST_ITEM_BLOCKED` — outside
    # its reach and needing Dave to act. Distinct from `items_failed`:
    # blocked items leave their paired session open for Dave to
    # resolve, and the run advances regardless of `failure_policy`.
    items_blocked: int = 0
    failed_item_id: int | None = None
    failure_reason: str | None = None


@dataclass
class DriverConfig:
    """Safety caps. Defaults are conservative — loud failures are
    better than runaway loops in an autonomous context.

    ``max_items_per_run``: total top-level items the driver will touch
    before halting. Catches both "checklist someone accidentally made
    huge" and "non-blocking followups regenerated enough work to
    loop forever."

    ``max_legs_per_item``: handoff cutovers per item. At 5 legs, the
    item is consuming 5x a context window — something is wrong with
    how it's scoped.

    ``max_followup_depth``: nesting depth for blocking followups. The
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

    ``spawn_leg`` creates a new paired chat ``sessions`` row for the
    item (kind='chat', checklist_item_id=item['id']) and whatever
    runner infrastructure the surrounding app needs to execute a
    turn against it. Returns the new session id.

    ``run_turn`` submits one prompt to the leg's runner and awaits
    the end of the assistant turn. Returns the assistant's final
    message body — the text the sentinel parser interprets.
    Exceptions propagate to the driver as leg failures.

    ``teardown_leg`` stops the runner for a leg (keeps the DB row
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
        captured for ``session_id``, or None if no ContextUsage event
        has been observed yet. The driver polls this after each
        ``run_turn`` to decide whether to inject a handoff-request
        nudge turn. Implementations that can't surface context
        pressure (e.g. test stubs that don't care) return None to
        opt out of the pressure-check branch."""
        ...
