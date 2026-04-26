"""Checklist DTOs (v0.4.0, Slice 2). Covers the checklist body plus
per-item create/update/toggle/reorder shapes."""

from __future__ import annotations

from pydantic import BaseModel


class ChecklistUpdate(BaseModel):
    """Partial update for a checklist's optional notes body. Unset =
    unchanged; explicit `None` clears the column."""

    notes: str | None = None


class ItemCreate(BaseModel):
    """New checklist item. `parent_item_id` enables nesting (null =
    top-level). `sort_order` is appended by the store when omitted so
    the typical "add to the end" flow needs no client-side bookkeeping."""

    label: str
    notes: str | None = None
    parent_item_id: int | None = None
    sort_order: int | None = None


class ItemUpdate(BaseModel):
    """Partial update for a checklist item. Fields left unset stay
    unchanged; `parent_item_id`/`notes` may be explicitly nulled."""

    label: str | None = None
    notes: str | None = None
    parent_item_id: int | None = None
    sort_order: int | None = None


class ItemToggle(BaseModel):
    """Body for the toggle endpoint. `True` stamps `checked_at` to the
    current time; `False` clears it."""

    checked: bool


class ItemLink(BaseModel):
    """Body for the link endpoint. Sets the item's `chat_session_id`
    pointer to an existing chat-kind session so visit-existing mode
    in the autonomous driver picks it up. Pass `None` to detach a
    prior link without spawning a fresh chat."""

    chat_session_id: str | None


class ItemOut(BaseModel):
    id: int
    checklist_id: str
    parent_item_id: int | None = None
    label: str
    notes: str | None = None
    # ISO timestamp when the item was checked, or null when unchecked.
    checked_at: str | None = None
    sort_order: int
    created_at: str
    updated_at: str
    # v0.5.0 paired-chat pointer (migration 0017). NULL when the user
    # has never clicked "Work on this" for the item; non-null is the
    # chat session id the agent spawns on first click. ChecklistView
    # uses this field to toggle the per-item button state between
    # "Work on this" (spawn) and "Continue working" (navigate).
    chat_session_id: str | None = None
    # Tri-state surface (migration 0033). An item is open
    # (`checked_at IS NULL` and `blocked_at IS NULL`), done
    # (`checked_at IS NOT NULL`), or blocked
    # (`blocked_at IS NOT NULL` and `checked_at IS NULL`) — mutually
    # exclusive at the application layer. The autonomous driver stamps
    # these via the `CHECKLIST_ITEM_BLOCKED` sentinel for items
    # genuinely outside the agent's reach (pay a bill, plug in
    # hardware, supply a 2FA code). The paired chat session stays open
    # for Dave to act on, while the run advances regardless of
    # `failure_policy`. Resolution path = Dave types into the still-
    # open session, agent re-engages and closes the item; closing
    # clears `blocked_at` in the same transaction. Driver wiring lands
    # in a follow-up commit; this one only surfaces the columns.
    blocked_at: str | None = None
    blocked_reason_category: str | None = None
    blocked_reason_text: str | None = None


class ChecklistOut(BaseModel):
    """Checklist body + items in a single round-trip. `items` comes
    back sorted by `sort_order` then `id`; nested children are
    resolved client-side via `parent_item_id`."""

    session_id: str
    notes: str | None = None
    created_at: str
    updated_at: str
    items: list[ItemOut] = []


class ReorderRequest(BaseModel):
    """Bulk sort-order rewrite. `item_ids` is the new order; the
    store silently skips ids that don't belong to this checklist so a
    malicious client can't reorder a list it doesn't own."""

    item_ids: list[int]


class ReorderResult(BaseModel):
    """Rows actually rewritten — may be less than `len(item_ids)` if
    any ids were skipped (foreign checklist, missing, etc.)."""

    reordered: int


class AutoRunStart(BaseModel):
    """Optional overrides for a `POST /sessions/{id}/checklist/run`
    request. All fields are optional — omit the body entirely to use
    the autonomous driver's conservative defaults.

    Per-invocation overrides (not settings) because Dave may want to
    dial caps per checklist — a cleanup list wants a high item cap and
    low leg cap, an exploratory investigation wants the opposite.

    `leg_permission_mode` controls the SDK's `can_use_tool` gating on
    each leg. The driver default is `bypassPermissions` (auto-approve
    every tool — required for genuinely unattended runs). Override to
    `acceptEdits` for "auto-approve file edits, ask for everything
    else" — useful when running the agent against a real working
    tree where you'd like a human in the loop for sudo/network calls.
    `default` re-enables full prompting and effectively turns off
    autonomy; `plan` is rejected (legs need to actually edit files).
    """

    max_items_per_run: int | None = None
    max_legs_per_item: int | None = None
    max_followup_depth: int | None = None
    leg_permission_mode: str | None = None
    # Visit-existing mode: when True, leg 1 of each item reuses the
    # session linked via `checklist_items.chat_session_id` (set by
    # PATCH /items/{id} or the manual "Work on this" flow) instead of
    # spawning fresh. Items with no linked session are skipped (left
    # unchecked, run advances). Handoff legs still spawn fresh.
    # Defaults to False to preserve the spawn-per-item behavior.
    visit_existing_sessions: bool | None = None
    # Failure policy: "halt" (default — first failure stops the run)
    # or "skip" (record the failure on the item, leave it unchecked,
    # advance to the next item). Use "skip" for tour runs over a
    # curated set of pre-existing sessions when you want the driver
    # to do everything it can and leave hard items for human review.
    failure_policy: str | None = None


class AutoRunStatus(BaseModel):
    """Current state of the autonomous driver for a checklist.

    `state` is one of:
    - `"running"` — driver task is active; counters are live.
    - `"finished"` — driver reached a terminal outcome; result fields
      are populated.
    - `"errored"` — driver task raised an uncaught exception; `error`
      carries `type(exc).__name__: str(exc)`. Rare (every expected
      failure is caught in the state machine and surfaces as
      `outcome=halted_failure` under `state=finished`).

    When `state=finished`, `outcome` matches `DriverOutcome`'s string
    values (`completed`, `halted_empty`, `halted_failure`,
    `halted_max_items`, `halted_stop`).
    """

    state: str
    items_completed: int | None = None
    items_failed: int | None = None
    items_skipped: int | None = None
    legs_spawned: int | None = None
    outcome: str | None = None
    failed_item_id: int | None = None
    failure_reason: str | None = None
    error: str | None = None
