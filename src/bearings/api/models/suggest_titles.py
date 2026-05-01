"""DTO surface for the auto-suggest-titles plan
(`~/.claude/plans/auto-suggesting-titles.md`) and its bulk follow-up
(`~/.claude/plans/bulk-retitling-checklist.md`).

Two shapes: the single-session response body for
`POST /sessions/{id}/suggest_titles`, and the per-checklist bulk
response that batches `suggest_titles` over every linked-chat split."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SuggestTitlesResult(BaseModel):
    """Response from `POST /sessions/{id}/suggest_titles`. Always
    exactly three candidates on success — the suggester rejects
    shorter responses upstream so the UI can render a fixed three-pill
    row without a length check. Order is narrow → medium → wide
    abstraction levels per the system-prompt instruction."""

    titles: list[str] = Field(min_length=3, max_length=3)


class BulkTitleSuggestItem(BaseModel):
    """One row of the bulk-suggest result. Either `candidates` carries
    three titles (success) or `error` carries the suggester's failure
    reason (per-item error inlined; the batch as a whole still
    returns 200). Mutually exclusive: success populates `candidates`
    and leaves `error` null; failure populates `error` and leaves
    `candidates` null."""

    item_id: int
    chat_session_id: str
    label: str
    current_title: str | None = None
    candidates: list[str] | None = None
    error: str | None = None


class BulkTitleSuggestResult(BaseModel):
    """Response from
    `POST /sessions/{id}/checklist/suggest_item_titles`.

    Lists every checklist item with `chat_session_id IS NOT NULL`,
    serially calling `suggest_titles` on each. Per-item errors are
    inlined in the matching row's `error` field rather than aborting
    the batch, so the operator sees partial successes alongside the
    failures and can apply just the good ones."""

    items: list[BulkTitleSuggestItem]
