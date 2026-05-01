"""Synth-gate evidence gatherer for orchestrator → executor verification.

When an autonomous executor reports `DONE` (or `DONE_WITH_CONCERNS`)
to its orchestrator, the discipline rule
(`~/.claude/rules/decision-discipline.md` §4) says the orchestrator
must verify with an artifact — file change, commit hash, gate output
— before advancing the master checklist. This module is the
verification helper: it reads the executor session's tool-call history
and produces a structured evidence summary the orchestrator can
cross-check against the executor's claim.

The helper does NOT enforce or auto-toggle anything. It returns data;
the orchestrator (LLM session OR Dave) makes the decision. That keeps
the gate composable — call it from a route, a CLI command, or a future
PreToolUse hook without the helper itself owning policy.

What counts as evidence:

- **tool_summary**: per-tool ok/failed counters across the executor's
  full lifetime. A `DONE` claim with zero `Edit`/`Write`/`Bash`
  invocations is suspect.
- **files_modified**: parsed `path` arguments from successful `Edit`,
  `Write`, `MultiEdit`, `NotebookEdit` calls. Dedup'd, sorted by last
  touch.
- **bash_commits**: subject lines parsed from `git commit` /
  `git push` Bash outputs. A claim that involved a commit but
  produced no commit hash here is also suspect.
- **bash_failures**: every Bash call where `error IS NOT NULL`,
  carrying the cmd + first 240 chars of error. The orchestrator can
  scan for "I ran tests, they passed" claims that contradict a
  `pytest` failure here.
- **last_assistant_snippet**: head of the executor's most recent
  assistant message. Anchors the evidence to a specific claim.
- **linked_checklist**: which master checklist item this executor is
  paired to + its current `checked_at`. Tells the orchestrator
  whether the toggle has already happened (idempotency check).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import aiosqlite

from bearings.db import store

log = logging.getLogger(__name__)

# Tools whose successful invocations imply on-disk file changes. Order
# matters for the path-extraction logic below: each name maps to the
# input field that carries the affected path. Keep in sync with the
# SDK's tool catalog when new file-mutating tools land.
_FILE_MUTATING_TOOLS: dict[str, str] = {
    "Edit": "file_path",
    "Write": "file_path",
    "MultiEdit": "file_path",
    "NotebookEdit": "notebook_path",
}

# Hard cap on the bash-failure error excerpt so a runaway error doesn't
# bloat the response. 240 chars is enough to distinguish "command not
# found" from "test failed at line 42" without requiring the
# orchestrator to scroll.
_BASH_ERR_EXCERPT_CHARS = 240

# Hard cap on the assistant-message snippet. 240 mirrors the bash cap
# above so the response stays scannable in a terminal.
_LAST_ASSISTANT_CHARS = 240

# Regex for extracting commit hashes out of `git commit` / `git push`
# Bash output. `[main 7d981d2]`-style line first; falls back to a
# bare 7+ hex run on a line containing "commit". Non-greedy enough
# that a verbose log doesn't flood with false positives.
_COMMIT_LINE_RE = re.compile(r"\[\w[-\w]*\s+([0-9a-f]{7,40})\]\s+(.+?)(?:\n|$)")


async def gather_work_evidence(
    conn: aiosqlite.Connection, session_id: str
) -> dict[str, Any] | None:
    """Build the evidence dict for one executor session.

    Returns None when the session doesn't exist; otherwise returns a
    dict matching the `WorkEvidence` Pydantic shape. All extraction is
    best-effort — malformed JSON in `tool_calls.input`, an
    unrecognized commit format in Bash output, or a tool with an
    unexpected input shape leaves the corresponding field empty
    rather than crashing the whole gather.

    Single SQL pass per data axis (`list_tool_calls`, `list_messages`,
    `list_item_sessions`) — no N+1.
    """
    session = await store.get_session(conn, session_id)
    if session is None:
        return None

    tool_calls = await store.list_tool_calls(conn, session_id)
    messages = await store.list_messages(conn, session_id, limit=20)

    # Per-tool ok/failed counters. Sort by name for deterministic UI.
    counters: dict[str, dict[str, int]] = {}
    for tc in tool_calls:
        name = tc["name"]
        bucket = counters.setdefault(name, {"ok": 0, "failed": 0})
        if tc.get("error"):
            bucket["failed"] += 1
        else:
            bucket["ok"] += 1
    tool_summary = [
        {"name": name, "ok": v["ok"], "failed": v["failed"]} for name, v in sorted(counters.items())
    ]

    files_modified = _extract_files_modified(tool_calls)
    bash_commits = _extract_bash_commits(tool_calls)
    bash_failures = _extract_bash_failures(tool_calls)

    last_assistant_snippet: str | None = None
    for msg in messages:
        if msg.get("role") == "assistant":
            content = (msg.get("content") or "").strip()
            if content:
                last_assistant_snippet = content[:_LAST_ASSISTANT_CHARS]
            break

    linked_checklist = await _resolve_linked_checklist(conn, session_id)

    return {
        "session_id": session_id,
        "tool_summary": tool_summary,
        "files_modified": files_modified,
        "bash_commits": bash_commits,
        "bash_failures": bash_failures,
        "last_assistant_snippet": last_assistant_snippet,
        "linked_checklist": linked_checklist,
    }


def _extract_files_modified(tool_calls: list[dict[str, Any]]) -> list[str]:
    """Pull `file_path` (or `notebook_path`) out of successful
    file-mutating tool calls. Dedup preserving last-seen order so the
    most recent touch sorts last in the response."""
    seen: dict[str, None] = {}
    for tc in tool_calls:
        if tc.get("error"):
            continue
        field = _FILE_MUTATING_TOOLS.get(tc["name"])
        if field is None:
            continue
        try:
            input_dict = json.loads(tc.get("input") or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        path = input_dict.get(field)
        if isinstance(path, str) and path:
            seen[path] = None
    return list(seen)


def _extract_bash_commits(tool_calls: list[dict[str, Any]]) -> list[str]:
    """Scan successful Bash outputs for `[branch hash] subject` lines.
    Returns one `"<short_hash> <subject>"` string per match across all
    Bash calls in chronological order."""
    commits: list[str] = []
    for tc in tool_calls:
        if tc["name"] != "Bash" or tc.get("error"):
            continue
        output = tc.get("output") or ""
        for match in _COMMIT_LINE_RE.finditer(output):
            short = match.group(1)[:7]
            subject = match.group(2).strip()
            commits.append(f"{short} {subject}")
    return commits


def _extract_bash_failures(tool_calls: list[dict[str, Any]]) -> list[dict[str, str]]:
    """One entry per failed Bash invocation, capped excerpt of the
    error column."""
    failures: list[dict[str, str]] = []
    for tc in tool_calls:
        if tc["name"] != "Bash" or not tc.get("error"):
            continue
        try:
            input_dict = json.loads(tc.get("input") or "{}")
        except (json.JSONDecodeError, TypeError):
            input_dict = {}
        cmd = input_dict.get("command") or ""
        if not isinstance(cmd, str):
            cmd = str(cmd)
        err = (tc.get("error") or "")[:_BASH_ERR_EXCERPT_CHARS]
        failures.append(
            {
                "cmd": cmd,
                "error_excerpt": err,
                "started_at": tc.get("started_at") or "",
            }
        )
    return failures


async def _resolve_linked_checklist(
    conn: aiosqlite.Connection, session_id: str
) -> dict[str, Any] | None:
    """Reverse lookup: given the executor session id, return the
    checklist item it's paired to (if any). `get_item_by_chat_session`
    is the canonical helper for this direction."""
    item = await store.get_item_by_chat_session(conn, session_id)
    if item is None:
        return None
    return {
        "item_id": item["id"],
        "label": item.get("label", ""),
        "checked_at": item.get("checked_at"),
        "blocked_at": item.get("blocked_at"),
        "blocked_reason_text": item.get("blocked_reason_text"),
    }
