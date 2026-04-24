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
    """

    max_items_per_run: int | None = None
    max_legs_per_item: int | None = None
    max_followup_depth: int | None = None


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
    legs_spawned: int | None = None
    outcome: str | None = None
    failed_item_id: int | None = None
    failure_reason: str | None = None
    error: str | None = None
