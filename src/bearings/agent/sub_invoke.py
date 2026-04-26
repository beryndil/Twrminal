"""One-shot sub-agent invocation for reply-action buttons (TL;DR,
Critique, etc).

Wave 2 lane 2 of the assistant-reply action row (see TODO.md
`L4.3.2`). The reply-action UX clicks `✂ TLDR` (or `⚔ CRIT` later) on a
finished assistant turn → backend POST → this module spawns a fresh,
tool-less `ClaudeSDKClient`, streams its tokens straight to the
caller, and rolls the SDK-reported cost into the parent session's
`total_cost_usd`. The result is *ephemeral* in v0 — surfaced into the
preview modal only — so we don't touch the messages table.

Why this lives outside `AgentSession`: AgentSession is a long-lived
per-session object that primes history, owns SDK session resume,
publishes wire events into a shared ring buffer, juggles MCP servers,
hooks, and a `can_use_tool` broker. A sub-agent invocation needs none
of that. Forcing it through AgentSession would either pollute the
parent's SDK session (resume id collisions, hook re-execution) or
require a wide cascade of "skip this for sub-invokes" branches. A
dedicated, minimal wrapper keeps the contract explicit: one prompt
in, a stream of text deltas out, one cost number folded back at end.

Design constraints:
  - **No tools.** The TL;DR / Critique prompts operate purely on the
    text we hand them. Passing `mcp_servers={}` + `hooks={}` strips any
    inherited config; a blanket `can_use_tool` denier is the second
    line of defense in case a future SDK release surfaces a tool we
    didn't think to disable.
  - **No history priming.** Sub-invokes don't read `messages`; the
    source text is in the user prompt. Skipping history keeps the
    token bill down and avoids leaking sibling-turn content into a
    summary the user expects to be about *one* reply.
  - **No SDK session resume.** A fresh client per call. Sub-invokes
    are independent — chaining them through one SDK session would
    accumulate cost and tokens across unrelated previews.
  - **Cost goes to the parent.** Sub-invocation cost rolls into
    `sessions.total_cost_usd` via `add_session_cost`. L2.1's per-
    session `max_budget_usd` cap is *not* re-checked here — it
    applies to the parent runner's pre-turn gate, and a sub-agent
    call costs cents at most. Future "tools budget" (deferred from
    L2.1 plan) is the place to add a separate cap.

Public API: `run_reply_action(...)` async generator. Yields one of
three event kinds (TextChunk / Complete / Failure). The HTTP layer
translates these into SSE frames; tests can iterate the generator
directly.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import aiosqlite
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    TextBlock,
)

from bearings.db import store

log = logging.getLogger(__name__)

# Per-action prompt templates. Adding a new action = adding an entry
# here + extending `ACTION_LABELS` below. The HTTP route validates the
# action name against `PROMPT_TEMPLATES.keys()`.
#
# Each template MUST be a one-shot instruction: the source assistant
# reply is appended to it (separated by a fenced block) and the model
# returns a self-contained response. Keep templates terse — the model
# pays attention to instructions inversely to their length.
PROMPT_TEMPLATES: dict[str, str] = {
    "summarize": (
        "Summarize the following assistant reply in 3–5 bullets, "
        "preserving file paths and code identifiers verbatim. "
        "Do not add commentary."
    ),
    # L4.3.3 — `⚔ CRIT` button. Adversarial-but-honest pass over the
    # reply, scoped to the four failure modes Dave cares about most:
    # unverified factual claims, missed edge cases, silent-failure
    # risks, and code that reads plausible but wouldn't actually
    # compile/run. The "if sound, say so plainly" clause is load-
    # bearing — the failure mode it heads off is sub-agents inventing
    # problems to look useful (a known regression in adversarial-
    # critique prompts). Quoting the line being critiqued keeps the
    # output actionable; vague critiques ("this might be brittle")
    # are useless against a wall of text.
    "critique": (
        "You are reviewing the following assistant reply for a "
        "Beryndil project. Identify: (a) factual claims that should "
        "be verified against the codebase, (b) edge cases not "
        "addressed, (c) silent-failure risks, (d) any code that "
        "won't actually compile or run as written. Be specific — "
        "quote the line you're critiquing. If the reply is sound, "
        "say so plainly and don't invent problems."
    ),
}

# Human-readable labels shown in the preview modal header. Mirrors
# `PROMPT_TEMPLATES` keys; serves as the public action-name catalog the
# frontend can hydrate without re-parsing the templates dict. Glyphs
# in the label flow into the modal badge so the user gets the same
# visual cue they clicked (⚔ on the button → ⚔ in the modal header).
ACTION_LABELS: dict[str, str] = {
    "summarize": "TL;DR",
    "critique": "⚔ Critique",
}


@dataclass(frozen=True, slots=True)
class TextChunk:
    """One incremental text delta from the sub-agent. The HTTP layer
    forwards these as SSE `event: token` frames; the modal appends
    each `text` to the rendered preview.
    """

    text: str


@dataclass(frozen=True, slots=True)
class Complete:
    """Terminal event signalling the sub-agent finished cleanly. The
    SSE layer emits `event: complete` with the cost (may be None if
    the SDK didn't report one — synthetic completions or older SDK
    versions) so the modal can show a tiny "ran in $X.YY" footer.
    """

    cost_usd: float | None
    full_text: str


@dataclass(frozen=True, slots=True)
class Failure:
    """Sub-agent crashed or the SDK returned an error. The SSE layer
    emits `event: error` and the modal shows the message in red.
    """

    message: str


SubInvokeEvent = TextChunk | Complete | Failure


def is_known_action(action: str) -> bool:
    """Single source of truth for the action enum. Used by the HTTP
    layer's request validation."""
    return action in PROMPT_TEMPLATES


def build_prompt(action: str, source_text: str) -> str:
    """Assemble the full one-shot prompt for the sub-agent. The source
    reply is enclosed in a fenced block so the model never confuses
    instructions with content even when the reply itself contains
    instruction-like text (the failure mode that motivated the fence
    is "the reply contains the literal word 'Summarize'")."""
    template = PROMPT_TEMPLATES[action]
    return f"{template}\n\n<assistant-reply>\n{source_text}\n</assistant-reply>"


async def _deny_all_tools(*_args: Any, **_kwargs: Any) -> PermissionResultDeny:
    """`can_use_tool` callback that refuses every tool. Defense-in-
    depth alongside `mcp_servers={}` + `hooks={}` — if a future SDK
    release ships a built-in tool we didn't think to disable, the
    model still can't reach it. The reason string surfaces in the
    SDK's logs only; the user never sees it because the model
    shouldn't be invoking tools in the first place."""
    return PermissionResultDeny(
        message="Sub-agent invocations are tool-less by design.",
        interrupt=False,
    )


async def run_reply_action(
    *,
    action: str,
    source_text: str,
    working_dir: str,
    model: str,
    db: aiosqlite.Connection | None,
    parent_session_id: str | None,
) -> AsyncIterator[SubInvokeEvent]:
    """Stream a tool-less sub-agent invocation.

    `db` + `parent_session_id` are the cost-attribution couple — if
    both are set, the SDK-reported cost is folded into
    `sessions.total_cost_usd` after the stream completes. Either being
    None disables that path (used by tests that drive the generator
    without persistence).

    Yields one or more `TextChunk` events (token deltas) followed by
    exactly one `Complete` or `Failure` event. The generator never
    yields after a terminal event.
    """
    if action not in PROMPT_TEMPLATES:
        yield Failure(message=f"unknown action: {action!r}")
        return

    prompt = build_prompt(action, source_text)
    options = ClaudeAgentOptions(
        cwd=working_dir,
        model=model,
        # Empty MCP map: no Bearings tools, no inherited user MCP
        # servers. Sub-invokes only need the bare model.
        mcp_servers={},
        # Empty hooks map: skip PostToolUse advisory + PreCompact
        # steering. Both are noise on a one-shot prompt-and-done call.
        hooks={},
        # Belt-and-suspenders: even if the SDK ships a default tool,
        # this denier vetoes every call. The model gets a "tool denied"
        # signal and falls back to text — exactly what the prompt
        # already asks for.
        can_use_tool=_deny_all_tools,
        # Stream content_block_deltas so the modal renders incrementally.
        # Without this the user waits for the full response then sees
        # it appear all at once — fine for batch callers, awful for a
        # preview UX.
        include_partial_messages=True,
    )

    full_text_parts: list[str] = []
    streamed_text = False
    cost_usd: float | None = None

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, StreamEvent):
                    chunk = _extract_text_delta(msg.event)
                    if chunk is not None:
                        streamed_text = True
                        full_text_parts.append(chunk)
                        yield TextChunk(text=chunk)
                elif isinstance(msg, AssistantMessage):
                    # If the model didn't stream (older SDK / certain
                    # model variants), the final AssistantMessage
                    # carries the full text. Yield it as one chunk so
                    # the modal still renders.
                    if streamed_text:
                        continue
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text:
                            full_text_parts.append(block.text)
                            yield TextChunk(text=block.text)
                elif isinstance(msg, ResultMessage):
                    cost_usd = msg.total_cost_usd
    except (ClaudeSDKError, OSError) as exc:
        log.warning("sub_invoke %s failed: %s", action, exc)
        yield Failure(message=str(exc) or "sub-agent stream failed")
        return
    except Exception as exc:  # noqa: BLE001 — surface to caller as Failure
        log.exception("sub_invoke %s crashed", action)
        yield Failure(message=str(exc) or "sub-agent crashed")
        return

    # Cost attribution. Best-effort: a failed cost write must not
    # turn a successful summary into a Failure event for the user.
    if db is not None and parent_session_id is not None and cost_usd:
        try:
            await store.add_session_cost(db, parent_session_id, cost_usd)
        except aiosqlite.Error:
            log.exception(
                "sub_invoke %s: failed to persist cost %.6f to session %s",
                action,
                cost_usd,
                parent_session_id,
            )

    yield Complete(cost_usd=cost_usd, full_text="".join(full_text_parts))


def _extract_text_delta(event: dict[str, Any]) -> str | None:
    """Pull a `text_delta` chunk out of a streaming SDK event dict.
    Mirrors `AgentSession._translate_stream_event` but narrowed to
    the only delta type sub-invokes care about — no thinking blocks,
    no tool deltas. Returns None for any other event shape."""
    if event.get("type") != "content_block_delta":
        return None
    delta = event.get("delta") or {}
    if delta.get("type") != "text_delta":
        return None
    text = delta.get("text") or ""
    return text or None
