from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SessionCreate(BaseModel):
    working_dir: str
    model: str
    title: str | None = None
    description: str | None = None
    max_budget_usd: float | None = None
    # v0.2.13: every session must carry ≥1 tag. The POST route
    # validates, the store layer doesn't (import_session and internal
    # fixtures still create tag-less rows — only external API-driven
    # creation is gated).
    tag_ids: list[int] = []
    # v0.4.0 session-kind discriminator. 'chat' is the historical
    # default; 'checklist' renders a structured list view instead of a
    # conversation. When 'checklist', the POST /sessions handler
    # additionally creates the companion `checklists` row inside the
    # same transaction (see routes_sessions).
    kind: Literal["chat", "checklist"] = "chat"


class SessionUpdate(BaseModel):
    """Partial update for an existing session. Any unset field is left
    unchanged; explicit `None` for any nullable field clears it."""

    title: str | None = None
    description: str | None = None
    max_budget_usd: float | None = None
    session_instructions: str | None = None
    # Distinguishes "not provided" from "set to null" for the nullable
    # columns. Pydantic writes `model_fields_set` so routes can dispatch
    # off what was actually passed.


class SessionOut(BaseModel):
    id: str
    created_at: str
    updated_at: str
    working_dir: str
    model: str
    title: str | None = None
    description: str | None = None
    max_budget_usd: float | None = None
    total_cost_usd: float = 0.0
    message_count: int = 0
    session_instructions: str | None = None
    # Persisted PermissionMode (see migration 0012). NULL maps to None
    # here, which the frontend renders as 'default' in the selector.
    # One of: 'default', 'plan', 'acceptEdits', 'bypassPermissions'.
    permission_mode: str | None = None
    # Most recent ContextUsage snapshot (migration 0013). NULL on
    # sessions that have yet to complete an assistant turn, or that
    # predate the column. Frontend renders a context-pressure meter
    # from these when present; live updates come via the `context_usage`
    # WS event.
    last_context_pct: float | None = None
    last_context_tokens: int | None = None
    last_context_max: int | None = None
    # Lifecycle flag (migration 0015). NULL = open, ISO timestamp =
    # closed. Closed sessions are hidden inside the sidebar's collapsed
    # "Closed" group. Reorg ops touching a closed session auto-clear
    # this column — see routes_reorg.
    closed_at: str | None = None
    # v0.4.0 session-kind discriminator (migration 0016). Existing rows
    # backfill to 'chat'; 'checklist' gates the UI right-pane view and
    # rejects runner/WS/reorg attachment.
    kind: str = "chat"


class MessageOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    thinking: str | None = None
    created_at: str
    # Per-turn token counts from `ResultMessage.usage`, populated on
    # assistant messages that completed normally. Null on user rows and
    # on assistant rows from before migration 0011 (backfilling them
    # would require replaying the SDK against the CLI, which we won't
    # do). The UI sums non-null values for session totals and falls
    # back to "—" when every row is null.
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None


class TokenTotalsOut(BaseModel):
    """Aggregate per-session token counts served by
    `/sessions/{id}/tokens`. Every field is a non-negative int —
    NULL rows in the underlying table contribute 0 via COALESCE, so
    a session with zero usable rows returns all-zeros rather than
    null."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


class ToolCallOut(BaseModel):
    id: str
    session_id: str
    message_id: str | None = None
    name: str
    input: str
    output: str | None = None
    error: str | None = None
    started_at: str
    finished_at: str | None = None


class SearchHit(BaseModel):
    message_id: str
    session_id: str
    session_title: str | None = None
    model: str
    role: str
    snippet: str
    created_at: str


class TagCreate(BaseModel):
    name: str
    color: str | None = None
    pinned: bool = False
    sort_order: int = 0
    default_working_dir: str | None = None
    default_model: str | None = None


class TagUpdate(BaseModel):
    """Partial update for an existing tag. Any unset field is left
    unchanged; explicit `None` for nullable fields clears them."""

    name: str | None = None
    color: str | None = None
    pinned: bool | None = None
    sort_order: int | None = None
    default_working_dir: str | None = None
    default_model: str | None = None


class TagOut(BaseModel):
    id: int
    name: str
    color: str | None = None
    pinned: bool
    sort_order: int
    created_at: str
    session_count: int = 0
    default_working_dir: str | None = None
    default_model: str | None = None


class TagMemoryPut(BaseModel):
    content: str


class TagMemoryOut(BaseModel):
    tag_id: int
    content: str
    updated_at: str


class SystemPromptLayerOut(BaseModel):
    name: str
    kind: str
    content: str
    token_count: int


class SystemPromptOut(BaseModel):
    layers: list[SystemPromptLayerOut]
    total_tokens: int


class FsEntryOut(BaseModel):
    name: str
    path: str


class FsListOut(BaseModel):
    path: str
    parent: str | None
    entries: list[FsEntryOut]


class CommandOut(BaseModel):
    """One entry in the slash-command palette (command or skill).

    `slug` is the token inserted into the textarea without the leading
    `/` — it matches what the Claude Code CLI accepts (e.g. `fad:ship`,
    `pr-review-toolkit:review-pr`). `scope` records where the entry came
    from so the UI can group or badge it; `source_path` is kept for
    debugging only — the client should not display it.
    """

    slug: str
    description: str
    kind: Literal["command", "skill"]
    scope: Literal["user", "project", "plugin"]
    source_path: str


class CommandsListOut(BaseModel):
    entries: list[CommandOut]


class ReorgWarning(BaseModel):
    """Advisory issue surfaced by a reorg op — never fatal.

    Slice 2 always returns an empty `warnings` array; Slice 7 (Polish)
    populates this with tool-call-group split detection. The model is
    defined now so the API shape is stable and the future addition is
    non-breaking.
    """

    code: str
    message: str
    details: dict[str, str] = {}


class ReorgMoveRequest(BaseModel):
    """Body for `POST /sessions/{id}/reorg/move`. `message_ids` must
    be non-empty; the route rejects an empty list with 400 even though
    the underlying primitive tolerates it as a no-op."""

    target_session_id: str
    message_ids: list[str]


class ReorgMoveResult(BaseModel):
    """Response shape shared by `move` and (nested in) `split`.

    `moved` and `tool_calls_followed` come directly from
    `store.MoveResult`; `warnings` is the forward-compatible slot for
    Slice 7's group-split detection — currently always `[]`. `audit_id`
    is the row the route wrote to `reorg_audits`; `None` when the op
    was a no-op (zero moves) so no divider was recorded. The frontend
    threads this into its undo handler so `DELETE /reorg/audits/{id}`
    has a direct target — no lookup race against a concurrent second
    op landing in the same millisecond.
    """

    moved: int
    tool_calls_followed: int
    warnings: list[ReorgWarning] = []
    audit_id: int | None = None


class NewSessionSpec(BaseModel):
    """Inline session spec used by split to create the target session.

    `model` and `working_dir` are optional here (unlike
    `SessionCreate`): when omitted, the route copies them from the
    source session so "split this thread off" doesn't require the
    caller to re-specify defaults the source already carries. Tag ids
    must be non-empty — every session must carry ≥1 tag (v0.2.13).
    """

    title: str
    description: str | None = None
    tag_ids: list[int]
    model: str | None = None
    working_dir: str | None = None


class ReorgSplitRequest(BaseModel):
    """Body for `POST /sessions/{id}/reorg/split`. `after_message_id`
    is the anchor — every message chronologically after it moves into
    the new session."""

    after_message_id: str
    new_session: NewSessionSpec


class ReorgSplitResult(BaseModel):
    """Response shape for split — the newly created session plus the
    inner move counts. 201 status code signals a resource was created."""

    session: SessionOut
    result: ReorgMoveResult


class ReorgMergeRequest(BaseModel):
    """Body for `POST /sessions/{id}/reorg/merge`. Moves every message
    on the source session into `target_session_id` in a single op; set
    `delete_source=true` to drop the now-empty source. Merging a
    session into itself is rejected with a 400."""

    target_session_id: str
    delete_source: bool = False


class ReorgMergeResult(BaseModel):
    """Response shape for merge. Carries the same `moved` /
    `tool_calls_followed` / `warnings` / `audit_id` fields as
    move/split, plus `deleted_source` (always matches the request flag
    on success; flip to false means the DELETE call no-op'd because
    the source was already empty of messages and still-live).

    `audit_id` is `None` when no audit row was written — either a
    no-op merge (zero moves) or a merge that deleted the source (the
    cascade would have dropped the row, so the route skips the write)."""

    moved: int
    tool_calls_followed: int
    warnings: list[ReorgWarning] = []
    audit_id: int | None = None
    deleted_source: bool


class ReorgAuditOut(BaseModel):
    """One persistent divider entry rendered on the source session's
    conversation view. The `target_session_id` FK is `ON DELETE SET
    NULL`, so a stale row with null id + a populated title snapshot
    means "the target was deleted after the move." The UI renders
    "(deleted session)" for that case instead of hiding the row."""

    id: int
    source_session_id: str
    target_session_id: str | None = None
    target_title_snapshot: str | None = None
    message_count: int
    op: Literal["move", "split", "merge"]
    created_at: str


# ---------------------------------------------------------------------------
# Checklist DTOs (v0.4.0, Slice 2)
# ---------------------------------------------------------------------------


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
