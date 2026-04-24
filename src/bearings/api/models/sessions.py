"""Session-level DTOs: create/update/out shapes, bulk ops, export bundle,
and the `NewSessionSpec` used by split."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


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
    # Phase 4a.1 of the context-menu plan. `model` powers the "Change
    # model for continuation" action (decision §2.1 — mutate in place,
    # no fork); the route drops the runner on model change so the next
    # turn spawns a fresh SDK subprocess on the new model string.
    model: str | None = None
    # `pinned` powers the sidebar pin/unpin affordance (migration 0022).
    # Pure UX — does not trigger a runner respawn. Accepts True/False;
    # `None` at the Pydantic layer means "field not provided" and is
    # ignored by the PATCH path, not "clear to false".
    pinned: bool | None = None
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
    # v0.5.0 per-item paired-chat pointer (migration 0017). NULL on
    # every chat session unless the user spawned it via "💬 Work on
    # this" from a checklist item; non-null is an INTEGER item id and
    # the prompt assembler reads it on every turn to inject the
    # checklist-context layer. SET NULL cascade on the FK means a
    # deleted item degrades the chat to a plain session rather than
    # destroying history.
    checklist_item_id: int | None = None
    # View tracking (migration 0020). `last_completed_at` is the ISO
    # timestamp of the most recent MessageComplete persisted for this
    # session; NULL until the first assistant turn finishes.
    last_completed_at: str | None = None
    # ISO timestamp of the last time the user focused / selected this
    # session (via POST /{id}/viewed). NULL means "never viewed."
    # Sidebar renders the amber "finished but unviewed" dot when
    # last_completed_at is non-null and either last_viewed_at is null
    # or precedes it.
    last_viewed_at: str | None = None
    # v0.2.14 / migration 0021: every tag_id attached to this session,
    # in no particular order. Populated from a GROUP_CONCAT subquery on
    # `session_tags` so the sidebar can render the medallion row (shield
    # for the severity tag, tag icons for each general tag) without an
    # N+1 per-row fetch. Empty list when the session has no tags —
    # shouldn't happen post-0021 but tolerates pre-0021 snapshots.
    tag_ids: list[int] = []
    # Pin flag (migration 0022). Stored as 0/1 in SQLite, coerced to
    # bool by Pydantic. Pinned sessions float to the top of their tag
    # group in the sidebar regardless of recency. False on every pre-
    # 0022 row via the column default.
    pinned: bool = False
    # Latched on an `ErrorEvent` fire, cleared on the next successful
    # `MessageComplete` (migration 0029). Drives the sidebar's
    # red-flashing "look at this now" indicator for crashed turns,
    # alongside the in-flight `awaiting_user` signal carried on the
    # `runner_state` WS frame. Backed by a server-side column so a
    # crashed turn survives page reload without the error signal
    # disappearing. False on every pre-0029 row via the column default.
    error_pending: bool = False


class SessionBulkBody(BaseModel):
    """Body for `POST /sessions/bulk` — Phase 9a of the context-menu
    plan. One endpoint for every multi-session op the sidebar exposes:
    `tag`/`untag` mutate tag attachments on each id, `close` sets
    `closed_at`, `delete` sweeps the rows (cascade-dropped messages,
    tool calls, etc.), `export` returns a combined JSON dump. `payload`
    is typed as a loose dict because each op cares about different
    fields (`tag_id` for tag/untag, nothing for close/delete/export);
    the route validates per-op.
    """

    op: Literal["tag", "untag", "close", "delete", "export"]
    ids: list[str]
    payload: dict[str, Any] = Field(default_factory=dict)


class SessionBulkResult(BaseModel):
    """Response for non-export bulk ops. `succeeded` and `failed` are
    disjoint — every input id appears in exactly one list. `failed`
    carries per-id error detail so the UI can surface partial failure
    without losing the ok path. Export returns a different shape (see
    `SessionExportBundle`) so it's not shared here."""

    op: str
    succeeded: list[str]
    failed: list[dict[str, str]] = Field(default_factory=list)


class SessionExportBundle(BaseModel):
    """Return shape for `op='export'`. `sessions` is the flat list of
    per-session export blobs (same shape as `GET /sessions/{id}/export`)
    in the order the caller requested. Failures are reported in the
    sibling `failed` list; successful ids appear in `sessions` only."""

    op: Literal["export"] = "export"
    sessions: list[dict[str, Any]]
    failed: list[dict[str, str]] = Field(default_factory=list)


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
