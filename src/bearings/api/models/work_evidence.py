"""DTO surface for the synth-gate work-evidence endpoint.

The response shape is what an orchestrator (human or LLM) reads to
decide whether to trust an executor's `DONE` claim before toggling a
master checklist item. See `src/bearings/agent/work_evidence.py` for
the gathering logic and `~/.claude/rules/decision-discipline.md` §4
for the contract."""

from __future__ import annotations

from pydantic import BaseModel


class ToolSummary(BaseModel):
    """Per-tool counters across the evidence window. `name` is the
    tool's wire name (e.g. `Edit`, `Write`, `Bash`, `Read`). `failed`
    counts rows where `error IS NOT NULL`; `ok` counts the rest."""

    name: str
    ok: int
    failed: int


class BashFailure(BaseModel):
    """One failed Bash invocation, surfaced verbatim so the orchestrator
    can audit what the executor actually tried. `cmd` is the parsed
    command from `tool_calls.input`; `error_excerpt` is the first 240
    chars of `tool_calls.error` so a runaway error doesn't bloat the
    response."""

    cmd: str
    error_excerpt: str
    started_at: str


class LinkedChecklistItem(BaseModel):
    """The checklist item this executor session is paired to (if any).
    `checked_at` lets the orchestrator quickly confirm whether the
    item is already toggled before deciding to toggle it again."""

    item_id: int
    label: str
    checked_at: str | None
    blocked_at: str | None
    blocked_reason_text: str | None


class WorkEvidence(BaseModel):
    """Aggregated evidence the orchestrator can cross-check against an
    executor's `DONE` claim. The endpoint never enforces — it provides
    the data so the caller (LLM orchestrator OR Dave) can adjudicate.

    Fields are intentionally additive: future evidence axes (test
    pass/fail counts, lint deltas, coverage diffs) can land here
    without breaking existing consumers."""

    session_id: str
    tool_summary: list[ToolSummary]
    files_modified: list[str]
    bash_commits: list[str]
    bash_failures: list[BashFailure]
    last_assistant_snippet: str | None
    linked_checklist: LinkedChecklistItem | None
