from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import aiosqlite
from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    CanUseTool,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    HookMatcher,
    PermissionMode,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ThinkingConfig,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from bearings.agent.events import (
    AgentEvent,
    ContextUsage,
    ErrorEvent,
    MessageComplete,
    MessageStart,
    Thinking,
    Token,
    ToolCallEnd,
    ToolCallStart,
    ToolOutputDelta,
)
from bearings.agent.mcp_tools import (
    BEARINGS_MCP_SERVER_NAME,
    build_bearings_mcp_server,
    tool_output_char_len,
)
from bearings.agent.prompt import assemble_prompt
from bearings.agent.researcher_prompt import RESEARCHER_PROMPT
from bearings.db._messages import list_messages

log = logging.getLogger(__name__)

# Full SDK-prefixed name the model sees for our streaming bash tool.
# When session.stream() observes a ToolCallStart with this name it
# pushes the call's id onto the pending-bash-id queue so the bash
# handler can claim it on entry. See agent/bash_tool.py for the
# correlation rationale.
BASH_TOOL_SDK_NAME = f"mcp__{BEARINGS_MCP_SERVER_NAME}__bash"

# Upper bound on the number of recent DB messages pulled into the
# context-priming preamble on the first turn of a freshly-built
# AgentSession (see `_build_history_prefix`). Ten messages is roughly
# the last five user/assistant exchanges, enough for "what were we just
# talking about?" without blowing the first-turn token budget.
_HISTORY_PRIME_MAX_MESSAGES = 10

# Per-message character cap for the priming preamble. Keeps the total
# preamble bounded (~20 KB ≈ 5k tokens worst case) even when a single
# assistant turn produced a long essay-style response. Messages longer
# than this are truncated with a visible "…[truncated]" marker so the
# model knows it's seeing a partial.
_HISTORY_PRIME_MAX_CHARS = 2000

# Context-pressure percentage at which the user-turn injection fires.
# Below this we stay silent — the meter already renders in the UI and
# nagging the model on every cheap turn burns its own attention budget.
# 50% is where `get_context_usage()` reports "yellow" band color; at
# that point a single research-heavy turn can tip us over the
# auto-compact threshold, so the advisory is worth the prompt real
# estate.
_PRESSURE_INJECT_THRESHOLD_PCT = 50.0

# Default per-turn tool-output cap used when `AgentSession` is built
# without one (tests, callers that don't care). Matches the default
# on `AgentCfg.tool_output_cap_chars`. A dedicated module constant so
# the two places that have to agree can't drift.
_DEFAULT_TOOL_OUTPUT_CAP_CHARS = 8000

# Custom instructions handed to the CLI's compactor via the PreCompact
# hook. Goal: preserve the tool-dense research turns that today get
# lossy-summarized and force the user to re-run the research. The exact
# verbiage is important — the compactor is itself an LLM, so we speak
# to it plainly. Paired with the researcher sub-agent (Option 4 in
# the plan), this should make most research survive auto-compact.
_PRECOMPACT_CUSTOM_INSTRUCTIONS = (
    "Preserve VERBATIM on compaction: (1) the most recent assistant "
    "turn that issued more than ~5 tool calls and its tool outputs "
    "— these are research turns whose findings the user has not yet "
    "consumed; (2) any unanswered user question (a user turn followed "
    "by an assistant turn that did not address it); (3) any tool "
    "output whose findings have not yet been summarized in a "
    "subsequent assistant message. Drop aggressively: repeated Read() "
    "of the same path, failed Bash retries, tool outputs older than "
    "the most recent checkpoint, redundant reconnaissance of files "
    "that were then edited. Keep the user's original ask verbatim. "
    "When in doubt, preserve tool outputs over assistant prose — "
    "Bearings can always re-summarize prose, it cannot re-derive raw "
    "tool output without another API round-trip."
)


def _pressure_hint_for(pct: float) -> str:
    """Band-specific steering text for the context-pressure block. At
    lower pressure we only nudge toward delegation; at higher pressure
    we add an explicit "consider checkpoint/fork" prompt so the model
    can raise it to the user without waiting for compaction to kick.
    Kept here (not in researcher_prompt.py) because the text is
    parent-side guidance and has nothing to do with the sub-agent's
    self-prompt."""
    if pct >= 85.0:
        return (
            "CRITICAL: auto-compact is close. Summarize current findings "
            "now, recommend the user fork from a recent checkpoint, and "
            "avoid any further broad codebase scans in this turn."
        )
    if pct >= 70.0:
        return (
            "High pressure. Prefer the `researcher` sub-agent via the "
            "Task tool for any further codebase survey work — its tool "
            "calls stay out of this context. Consider suggesting a "
            "checkpoint to the user before a large next turn."
        )
    return (
        "Elevated pressure. Prefer the `researcher` sub-agent via the "
        "Task tool for heavy tool work so its calls stay out of this "
        "context. Avoid re-reading files you have already read this "
        "session."
    )


def _stringify(content: str | list[dict[str, object]] | None) -> str | None:
    if content is None or isinstance(content, str):
        return content
    return json.dumps(content)


def _extract_tokens(usage: dict[str, Any] | None) -> dict[str, int | None]:
    """Pull the four token fields out of `ResultMessage.usage`.

    The SDK forwards Anthropic's `usage` block verbatim, so the key
    shape is `input_tokens`, `output_tokens`,
    `cache_creation_input_tokens`, `cache_read_input_tokens` (note the
    `_input_tokens` suffix on the cache fields). We normalize to the
    shorter column names used in the `messages` table.

    Missing keys stay None so the DB column stays NULL — useful for
    future SDK versions that might reshape the payload without us
    noticing. All four are `None` when `usage` itself is None
    (synthetic completions from stop/cancel paths).
    """
    if not usage:
        return {
            "input_tokens": None,
            "output_tokens": None,
            "cache_read_tokens": None,
            "cache_creation_tokens": None,
        }

    def _int_or_none(value: object) -> int | None:
        if isinstance(value, bool):
            # bool is a subclass of int; reject it explicitly so a
            # stray True doesn't silently become 1.
            return None
        if isinstance(value, int):
            return value
        return None

    return {
        "input_tokens": _int_or_none(usage.get("input_tokens")),
        "output_tokens": _int_or_none(usage.get("output_tokens")),
        "cache_read_tokens": _int_or_none(usage.get("cache_read_input_tokens")),
        "cache_creation_tokens": _int_or_none(usage.get("cache_creation_input_tokens")),
    }


class AgentSession:
    """Wraps a single Claude Code agent session via claude-agent-sdk.

    One instance per WebSocket connection; a short-lived `ClaudeSDKClient`
    is created for each `stream()` call.
    """

    def __init__(
        self,
        session_id: str,
        working_dir: str,
        model: str,
        max_budget_usd: float | None = None,
        db: aiosqlite.Connection | None = None,
        sdk_session_id: str | None = None,
        permission_mode: PermissionMode | None = None,
        thinking: ThinkingConfig | None = None,
        setting_sources: list[str] | None = None,
        inherit_mcp_servers: bool = True,
        inherit_hooks: bool = True,
        tool_output_cap_chars: int = _DEFAULT_TOOL_OUTPUT_CAP_CHARS,
        enable_bearings_mcp: bool = True,
        enable_precompact_steering: bool = True,
        enable_researcher_subagent: bool = False,
    ) -> None:
        self.session_id = session_id
        self.working_dir = working_dir
        self.model = model
        self.max_budget_usd = max_budget_usd
        # Extended-thinking config passed through to
        # `ClaudeAgentOptions.thinking`. When set, the SDK adds the
        # corresponding `--thinking` / `--max-thinking-tokens` flag to
        # the CLI invocation and the model emits ThinkingBlocks / live
        # thinking deltas, which we surface as `Thinking` wire events
        # for the Conversation view's collapsed thinking block.
        self.thinking = thinking
        # Optional DB connection for the v0.2 prompt assembler. When
        # set, `stream()` calls `assemble_prompt` and passes the
        # concatenated layered prompt as `system_prompt`. Unit tests
        # that don't exercise persistence can leave it None; the WS
        # handler wires it in production.
        self.db = db
        # Claude-agent-sdk session id captured from the first
        # AssistantMessage and passed back as `resume=` on the next
        # turn so the fresh SDK client inherits prior history instead
        # of starting blind. WS handler persists this to `sessions.
        # sdk_session_id` so reconnects keep context too.
        self.sdk_session_id = sdk_session_id
        # Current permission mode — applied to every subsequent
        # stream() call's options. Flipping this (via
        # set_permission_mode) is how `/plan` engages plan mode.
        self.permission_mode = permission_mode
        # Permission-profile gates wired through to the SDK. `None` /
        # `True` reproduce today's behavior — the SDK applies its own
        # defaults (inherit user `~/.claude` settings, MCP servers,
        # hooks). The `safe` profile flips these so a session under
        # Bearings starts from a clean slate without leaking the
        # operator's global config into the session run. See
        # `bearings.config.AgentCfg` for the per-knob rationale.
        self.setting_sources = setting_sources
        self.inherit_mcp_servers = inherit_mcp_servers
        self.inherit_hooks = inherit_hooks
        # Optional `can_use_tool` callback passed to `ClaudeAgentOptions`.
        # When set (by the runner, post-construction), the SDK invokes
        # it whenever a tool call needs permission — the runner parks
        # a Future and fans an `ApprovalRequest` event out to WS
        # subscribers, resolving the Future when the UI replies. Left
        # None for unit tests that don't exercise permission gating.
        self.can_use_tool: CanUseTool | None = None
        # Tracks the currently-active SDK client so `interrupt()` can
        # reach into an in-flight stream. Set inside `stream()` under
        # the `async with`; cleared on exit.
        self._client: ClaudeSDKClient | None = None
        # Whether this instance has already primed the SDK with a
        # transcript of recent history. Set True after the first
        # `stream()` call so subsequent turns rely on `resume=` /
        # SDK-side context instead of re-prepending the same history.
        # A brand-new runner after a reconnect starts with
        # `_primed=False`, so the first turn carries an explicit
        # preamble — a belt-and-suspenders backup for cases where SDK
        # session resume fails silently (stale session file, cwd
        # mismatch, system_prompt divergence). See `_build_history_prefix`.
        self._primed: bool = False
        # Per-turn tool-output cap. When a tool output is larger than
        # this (in chars) the PostToolUse hook appends a short
        # advisory to the model's context telling it the full text is
        # persisted in the Bearings DB and retrievable via the
        # `bearings__get_tool_output` MCP tool. See plan Option 6.
        self.tool_output_cap_chars = tool_output_cap_chars
        # Feature toggles — all four default to the values that
        # reproduce the token-cost plan's recommended shipping state.
        # Tests that want to lock a specific subset of these on/off
        # can pass them explicitly.
        self.enable_bearings_mcp = enable_bearings_mcp
        self.enable_precompact_steering = enable_precompact_steering
        self.enable_researcher_subagent = enable_researcher_subagent

    def set_permission_mode(self, mode: PermissionMode | None) -> None:
        self.permission_mode = mode

    def _current_db(self) -> aiosqlite.Connection | None:
        """DB-getter closure handed to the Bearings MCP server so its
        tool handlers always see the session's current connection even
        if it swaps under us. Kept as a bound method so subclassing
        stays straightforward."""
        return self.db

    async def _build_history_prefix(self, prompt: str) -> str | None:
        """Render the last few DB-persisted turns into a preamble the
        SDK can prepend to the user's message.

        Why it exists: passing `resume=<sdk_session_id>` tells the CLI
        to rehydrate its own session file, but that path has failure
        modes we can't detect — the file may be gone, the cwd may have
        shifted, the system prompt may no longer match — and when it
        fails the fresh client simply starts with no history. This
        preamble gives the model an explicit textual transcript of
        recent turns as a guaranteed-present safety net.

        Called once per `AgentSession` instance (gated by `_primed`).
        Returns `None` when there's nothing to prime (fresh session, no
        prior turns). The runner inserts the current user prompt into
        `messages` *before* calling `stream()`, so the most-recent row
        is often this very turn's prompt — the dedupe logic below drops
        it so we don't echo the user's message back at them inside the
        preamble.
        """
        if self.db is None:
            return None
        # Pull one extra so the dedupe step still leaves the full
        # history window intact when the trailing row is our own.
        # `exclude_hidden=True` honors the `hidden_from_context` flag
        # (migration 0023) — rows the user marked as hidden skip the
        # history preamble so the next turn doesn't see them.
        rows = await list_messages(
            self.db,
            self.session_id,
            limit=_HISTORY_PRIME_MAX_MESSAGES + 1,
            exclude_hidden=True,
        )
        if not rows:
            return None
        # `list_messages(..., limit=...)` returns newest-first. Drop the
        # current turn's own user row if the runner already persisted it.
        if rows[0].get("role") == "user" and rows[0].get("content") == prompt:
            rows = rows[1:]
        if not rows:
            return None
        rows = rows[:_HISTORY_PRIME_MAX_MESSAGES]
        # Flip to oldest-first for a chronological transcript.
        rows.reverse()
        lines: list[str] = []
        for row in rows:
            role = str(row.get("role") or "unknown")
            body = str(row.get("content") or "")
            if len(body) > _HISTORY_PRIME_MAX_CHARS:
                body = body[:_HISTORY_PRIME_MAX_CHARS] + "…[truncated]"
            lines.append(f"{role}: {body}")
        if not lines:
            return None
        transcript = "\n\n".join(lines)
        return (
            "<previous-conversation>\n"
            "[The following are earlier turns in this session, provided "
            "so the assistant keeps context after a reconnect or process "
            "restart. Do not re-execute any tool calls shown below; use "
            "this only to understand the ongoing conversation.]\n\n"
            f"{transcript}\n\n"
            "[End of previous conversation. The user's new message "
            "follows.]\n"
            "</previous-conversation>\n\n"
        )

    async def _capture_context_usage(self, client: ClaudeSDKClient) -> ContextUsage | None:
        """Pull the SDK's current context-window snapshot and translate
        it into a `ContextUsage` wire event. Called inside the
        `ClaudeSDKClient` context manager at the end of a turn so the
        underlying CLI subprocess is still live — calling after
        `async with` exit would hit a closed connection.

        Best-effort: SDK call failure or response-shape mismatch
        returns None and the turn continues. The context meter is
        purely advisory — losing an update must not take down a
        successful turn. Swallowing errors here is the one place in
        this module where we accept a silent miss; everywhere else
        errors surface as `ErrorEvent`.

        `AttributeError` covers the older-SDK case where the method
        isn't on the client at all (also matches test fixtures that
        skip stubbing it); `ClaudeSDKError` / `OSError` cover the
        active-call failure modes (CLI subprocess crash, transport
        hiccup)."""
        try:
            resp = await client.get_context_usage()
        except (ClaudeSDKError, OSError, AttributeError):
            return None

        def _opt_int(value: object) -> int | None:
            if isinstance(value, bool) or not isinstance(value, int):
                return None
            return value

        try:
            return ContextUsage(
                session_id=self.session_id,
                total_tokens=int(resp.get("totalTokens") or 0),
                max_tokens=int(resp.get("maxTokens") or 0),
                percentage=float(resp.get("percentage") or 0.0),
                model=str(resp.get("model") or self.model),
                is_auto_compact_enabled=bool(resp.get("isAutoCompactEnabled", False)),
                auto_compact_threshold=_opt_int(resp.get("autoCompactThreshold")),
            )
        except (TypeError, ValueError, AttributeError):
            return None

    async def _build_context_pressure_block(self) -> str | None:
        """Render a `<context-pressure>` block for injection ahead of
        the user's prompt when the last persisted pct crossed the
        threshold.

        Reads directly from the session row (populated by the runner
        on every ContextUsage event). Returns None on no-data or
        low-pressure — we only nag the model when there's real reason
        to, otherwise the advisory just eats tokens it's trying to
        save. Swallows DB errors: if the read fails the injection is
        silently skipped; the meter is advisory and the next turn
        still works."""
        if self.db is None:
            return None
        try:
            async with self.db.execute(
                "SELECT last_context_pct, last_context_tokens, last_context_max "
                "FROM sessions WHERE id = ?",
                (self.session_id,),
            ) as cursor:
                row = await cursor.fetchone()
        except aiosqlite.Error:
            return None
        if row is None or row["last_context_pct"] is None:
            return None
        pct = float(row["last_context_pct"])
        if pct < _PRESSURE_INJECT_THRESHOLD_PCT:
            return None
        tokens = row["last_context_tokens"]
        max_tokens = row["last_context_max"]
        hint = _pressure_hint_for(pct)
        return (
            f'<context-pressure pct="{pct:.1f}" tokens="{tokens}" '
            f'max="{max_tokens}">\n'
            f"{hint}\n"
            "</context-pressure>\n\n"
        )

    def _build_post_tool_use_hook(self) -> Any:
        """Return an async hook callback that attaches a tool-output
        retrieval advisory when a tool produced more than
        `tool_output_cap_chars` of content.

        The advisory is the best we can do for native (Read / Bash /
        Grep / Edit) tools: the SDK's hook output schema only allows
        rewriting MCP tool output (`updatedMCPToolOutput`), not native
        tool output. So we leave the raw output in context for this
        turn but tell the model "this is big — when it gets dropped
        from context on compaction, retrieve via
        `bearings__get_tool_output` instead of asking me to re-run
        the tool." That steers the model toward summarizing
        aggressively in its reply and relying on retrieval later.

        Returns a no-op callback (`None` output) when the cap is
        non-positive — lets operators disable the advisory without
        unwiring the hook machinery."""
        cap = int(self.tool_output_cap_chars or 0)

        async def hook(
            input_data: Any,
            tool_use_id: str | None,
            _context: Any,
        ) -> dict[str, Any]:
            if cap <= 0:
                return {}
            response = input_data.get("tool_response") if isinstance(input_data, dict) else None
            body: Any
            if isinstance(response, dict):
                body = response.get("content")
            else:
                body = response
            try:
                length = await tool_output_char_len(body)
            except (TypeError, ValueError):
                length = 0
            if length <= cap:
                return {}
            tool_name = input_data.get("tool_name") if isinstance(input_data, dict) else None
            advisory = (
                f"[bearings: this {tool_name or 'tool'} call produced "
                f"{length} chars of output — above the {cap}-char "
                "context-cost cap. Summarize now; on future turns, if "
                "the raw text has fallen out of context, retrieve via "
                "`bearings__get_tool_output` with "
                f'tool_use_id="{tool_use_id or "<id>"}" rather than '
                "re-running the tool.]"
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": advisory,
                }
            }

        return hook

    def _build_precompact_hook(self) -> Any:
        """Return an async hook callback that hands the CLI's
        compactor explicit preservation instructions. See
        `_PRECOMPACT_CUSTOM_INSTRUCTIONS` for the policy text."""

        async def hook(
            _input_data: Any,
            _tool_use_id: str | None,
            _context: Any,
        ) -> dict[str, Any]:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreCompact",
                    "customInstructions": _PRECOMPACT_CUSTOM_INSTRUCTIONS,
                }
            }

        return hook

    async def stream(self, prompt: str) -> AsyncIterator[AgentEvent]:
        options_kwargs: dict[str, Any] = {
            "cwd": self.working_dir,
            "model": self.model,
            "include_partial_messages": True,
        }
        if self.max_budget_usd is not None:
            options_kwargs["max_budget_usd"] = self.max_budget_usd
        if self.permission_mode is not None:
            options_kwargs["permission_mode"] = self.permission_mode
        if self.sdk_session_id is not None:
            # Resume the prior SDK session so conversation history is
            # on the CLI side even though this is a fresh client.
            options_kwargs["resume"] = self.sdk_session_id
        if self.thinking is not None:
            options_kwargs["thinking"] = self.thinking
        if self.can_use_tool is not None:
            options_kwargs["can_use_tool"] = self.can_use_tool
        # Permission-profile gates. We pass each only when it diverges
        # from the SDK default so a power-user run (today's behavior)
        # still produces the exact same `ClaudeAgentOptions` payload as
        # before this knob landed.
        if self.setting_sources is not None:
            options_kwargs["setting_sources"] = self.setting_sources
        mcp_servers: dict[str, Any] = {}
        if not self.inherit_mcp_servers:
            # Empty dict tells the SDK "no MCP servers" rather than
            # "use defaults". The dict is required-typed in the SDK
            # so we can't pass `None`.
            options_kwargs["mcp_servers"] = mcp_servers
        # Per-stream side channel for the streaming bash tool. The
        # bash handler pushes a `ToolOutputDelta` per subprocess line
        # onto `delta_queue`; the receive_response loop multiplexes
        # those into the yielded event stream alongside SDK messages.
        # The bash handler also awaits `pending_bash_ids.get()` to
        # claim its model-side `tool_use.id` (the MCP tools/call
        # payload doesn't carry it; we push from the matching
        # ToolCallStart). Both queues are unbounded — the SDK's own
        # backpressure (handler runs on the same loop as the consumer)
        # keeps growth in check.
        delta_queue: asyncio.Queue[ToolOutputDelta] = asyncio.Queue()
        pending_bash_ids: asyncio.Queue[str] = asyncio.Queue()

        def emit_delta_cb(tool_use_id: str, line: str) -> None:
            try:
                delta_queue.put_nowait(
                    ToolOutputDelta(
                        session_id=self.session_id,
                        tool_call_id=tool_use_id,
                        delta=line,
                    )
                )
            except asyncio.QueueFull:
                # Unbounded queue — should never happen. Log and drop
                # rather than crash the bash subprocess pump.
                log.warning(
                    "session %s: delta_queue full (unexpected); dropping live frame",
                    self.session_id,
                )

        # Bearings' own in-process MCP server. Gated by the
        # `enable_bearings_mcp` knob AND the presence of a DB (the
        # `get_tool_output` tool reads from it). Composed with the
        # `inherit_mcp_servers` behavior above — whatever the inherit
        # policy, the Bearings server is added on top.
        if self.enable_bearings_mcp and self.db is not None:
            mcp_servers[BEARINGS_MCP_SERVER_NAME] = build_bearings_mcp_server(
                self.session_id,
                self._current_db,
                emit_delta=emit_delta_cb,
                bash_id_getter=pending_bash_ids.get,
            )
            options_kwargs["mcp_servers"] = mcp_servers
        hooks_map: dict[str, list[HookMatcher]] = {}
        if not self.inherit_hooks:
            options_kwargs["hooks"] = hooks_map
        # PostToolUse advisory hook (Option 6). Cheap to register even
        # on turns that don't produce big outputs — the hook short-
        # circuits on length.
        hooks_map.setdefault("PostToolUse", []).append(
            HookMatcher(hooks=[self._build_post_tool_use_hook()])
        )
        if self.enable_precompact_steering:
            hooks_map.setdefault("PreCompact", []).append(
                HookMatcher(hooks=[self._build_precompact_hook()])
            )
        if hooks_map:
            options_kwargs["hooks"] = hooks_map
        if self.enable_researcher_subagent:
            options_kwargs["agents"] = {
                "researcher": AgentDefinition(
                    description=(
                        "Read-only codebase survey sub-agent. Runs tool "
                        "calls in isolated context and returns only a "
                        "compact summary — use it via the Task tool for "
                        "heavy exploration so raw outputs do not enter "
                        "this turn's context."
                    ),
                    prompt=RESEARCHER_PROMPT,
                    # Streaming bash tool replaces the built-in Bash
                    # so the researcher's shell calls also flow through
                    # the live-output pipe. Read/Grep/Glob remain
                    # builtin — they're already small-output.
                    tools=["Read", "Grep", "Glob", BASH_TOOL_SDK_NAME],
                    model="inherit",
                )
            }
        # Route the model away from the built-in `Bash` tool toward
        # our streaming MCP equivalent. We disallow built-in Bash and
        # leave allowed_tools empty (= "no allowlist filter") so every
        # other tool — including all MCP tools we expose — remains
        # available. Setting allowed_tools to a non-empty list would
        # turn it into an exclusive allowlist and accidentally hide
        # everything else from the model. Wired only when our MCP
        # server is registered, so test sessions without DB still
        # have the built-in Bash available.
        if self.enable_bearings_mcp and self.db is not None:
            disallowed = list(options_kwargs.get("disallowed_tools") or [])
            if "Bash" not in disallowed:
                disallowed.append("Bash")
            options_kwargs["disallowed_tools"] = disallowed
        if self.db is not None:
            # Assemble the layered system prompt (base → tag memories →
            # session instructions) from the current DB state. Called
            # per turn so edits to tag memories / session instructions
            # take effect on the next prompt without restarting the WS.
            assembled = await assemble_prompt(self.db, self.session_id)
            options_kwargs["system_prompt"] = assembled.text
        options = ClaudeAgentOptions(**options_kwargs)
        # First-turn context priming. Only runs once per AgentSession
        # instance — subsequent turns rely on the SDK's own context
        # chain (the `resume=` hint above + the CLI's session file).
        # Set `_primed` before building the prefix so a transient DB
        # error below doesn't trap us in a re-prime loop; the worst
        # case is a single missed priming, not an infinite retry.
        if not self._primed:
            self._primed = True
            prefix = await self._build_history_prefix(prompt)
            if prefix is not None:
                prompt = prefix + prompt
        # Context-pressure injection (Option 1 finish). Runs on every
        # turn (not gated by `_primed`) because pressure accumulates
        # over the life of the session and we want the nudge every
        # turn above threshold, not just the first. The block is
        # prepended after the history prefix so the prompt reads:
        # [transcript] [pressure] [user message] — the model sees
        # "here's where we are, here's the warning, here's the ask."
        pressure_block = await self._build_context_pressure_block()
        if pressure_block is not None:
            prompt = pressure_block + prompt
        message_id = uuid4().hex
        cost_usd: float | None = None
        usage: dict[str, Any] | None = None
        context_event: ContextUsage | None = None

        # Sentinels for the multiplexed event channel. The drain task
        # below pushes ("msg", msg) for every receive_response item
        # and ("done", None) once the iterator is exhausted; the bash
        # handler pushes ("delta", ToolOutputDelta) directly via the
        # emit_delta callback. The main loop drains a single queue,
        # so ordering matches the order things land — receive_response
        # messages and tool-output deltas interleave naturally.
        async def _drain_msgs(
            client: ClaudeSDKClient,
            shared: asyncio.Queue[tuple[str, Any]],
        ) -> None:
            try:
                async for msg in client.receive_response():
                    await shared.put(("msg", msg))
            except asyncio.CancelledError:
                # Cancelled when the main loop breaks out of the
                # multiplex — re-raise so the task winds down cleanly.
                raise
            except Exception as exc:  # noqa: BLE001 — surface to consumer
                await shared.put(("error", exc))
            finally:
                with contextlib.suppress(asyncio.QueueFull):
                    shared.put_nowait(("done", None))

        try:
            async with ClaudeSDKClient(options=options) as client:
                self._client = client
                drain_task: asyncio.Task[None] | None = None
                try:
                    await client.query(prompt)
                    yield MessageStart(session_id=self.session_id, message_id=message_id)
                    # Single multiplex queue: receive_response messages
                    # AND streaming tool-output deltas land here. The
                    # bash handler put-no-waits onto the same channel
                    # via the `delta_queue` shared with emit_delta_cb.
                    shared: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
                    drain_task = asyncio.create_task(_drain_msgs(client, shared))
                    # Track per-block-type streaming. Opus 4.7 in
                    # adaptive mode emits text_delta but NOT
                    # thinking_delta — the thinking content only
                    # arrives in the final AssistantMessage's
                    # ThinkingBlock. A single streamed_this_msg flag
                    # would drop that thinking block as a "duplicate"
                    # because text_delta fired. Track each block type
                    # independently so we only suppress the kind we
                    # actually saw streamed.
                    streamed_text = False
                    streamed_thinking = False
                    finished = False
                    while not finished:
                        # Drain any tool-output deltas first so a fast
                        # bash command's lines can't pile up behind a
                        # slow receive_response. ``get_nowait`` is the
                        # right primitive: when there are no deltas,
                        # we fall through to an awaitable shared.get().
                        flushed_delta = False
                        while True:
                            try:
                                yield delta_queue.get_nowait()
                                flushed_delta = True
                            except asyncio.QueueEmpty:
                                break
                        if flushed_delta:
                            # Yield once more so deltas published in
                            # bursts can drain without blocking on a
                            # message that might not arrive for a while.
                            await asyncio.sleep(0)
                        # Wait on EITHER a fresh delta OR the next
                        # multiplexed message. Whichever lands first
                        # wins the iteration.
                        delta_get: asyncio.Task[ToolOutputDelta] = asyncio.create_task(
                            delta_queue.get()
                        )
                        shared_get: asyncio.Task[tuple[str, Any]] = asyncio.create_task(
                            shared.get()
                        )
                        pending: set[asyncio.Task[Any]] = {delta_get, shared_get}
                        try:
                            done, pending = await asyncio.wait(
                                pending,
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                        finally:
                            for task in (delta_get, shared_get):
                                if not task.done():
                                    task.cancel()
                                    with contextlib.suppress(asyncio.CancelledError):
                                        await task
                        for task in done:
                            if task is delta_get:
                                # delta_queue.get() returns ToolOutputDelta
                                yield delta_get.result()
                                continue
                            # The other branch is shared.get() returning
                            # ("kind", payload). Read off the typed
                            # task to keep mypy happy with the union.
                            kind, payload = shared_get.result()
                            if kind == "delta":
                                # Bash handler pushes onto delta_queue
                                # directly; this branch covers a future
                                # producer that wants to push through
                                # `shared`. Harmless either way.
                                if isinstance(payload, ToolOutputDelta):
                                    yield payload
                                continue
                            if kind == "done":
                                finished = True
                                continue
                            if kind == "error":
                                if isinstance(payload, BaseException):
                                    raise payload
                                continue
                            msg = payload
                            if isinstance(msg, StreamEvent):
                                event = self._translate_stream_event(msg.event)
                                if event is not None:
                                    if isinstance(event, Token):
                                        streamed_text = True
                                    elif isinstance(event, Thinking):
                                        streamed_thinking = True
                                    yield event
                            elif isinstance(msg, AssistantMessage):
                                if msg.session_id:
                                    self.sdk_session_id = msg.session_id
                                for block in msg.content:
                                    if streamed_text and isinstance(block, TextBlock):
                                        continue
                                    if streamed_thinking and isinstance(block, ThinkingBlock):
                                        continue
                                    event = self._translate_block(block)
                                    if event is None:
                                        continue
                                    # Pre-register bash tool_use_ids
                                    # for the side-channel correlator
                                    # before yielding so the handler
                                    # can claim the right id when the
                                    # SDK invokes call_tool.
                                    if (
                                        isinstance(event, ToolCallStart)
                                        and event.name == BASH_TOOL_SDK_NAME
                                    ):
                                        with contextlib.suppress(asyncio.QueueFull):
                                            pending_bash_ids.put_nowait(event.tool_call_id)
                                    yield event
                                streamed_text = False
                                streamed_thinking = False
                            elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
                                for block in msg.content:
                                    if isinstance(block, ToolResultBlock):
                                        yield self._tool_call_end(block)
                            elif isinstance(msg, ResultMessage):
                                cost_usd = msg.total_cost_usd
                                usage = msg.usage
                                finished = True
                    # Drain any deltas that landed between the final
                    # multiplex iteration and now (a fast bash command
                    # whose last line raced the ResultMessage).
                    while True:
                        try:
                            yield delta_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    # Capture the context-usage snapshot while the CLI
                    # subprocess is still live. The async-with exit
                    # below tears it down; calling afterward would hit
                    # a closed connection.
                    context_event = await self._capture_context_usage(client)
                finally:
                    if drain_task is not None and not drain_task.done():
                        drain_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await drain_task
                    self._client = None
            # Yield the context-usage snapshot *before* MessageComplete
            # because the runner's stream loop breaks on MessageComplete
            # to persist the turn — anything after that is dropped on
            # the floor. The frontend reducer handles the two events on
            # independent state slots (fringe vs. meter) so ordering
            # doesn't create a visible glitch.
            if context_event is not None:
                yield context_event
            tokens = _extract_tokens(usage)
            yield MessageComplete(
                session_id=self.session_id,
                message_id=message_id,
                cost_usd=cost_usd,
                input_tokens=tokens["input_tokens"],
                output_tokens=tokens["output_tokens"],
                cache_read_tokens=tokens["cache_read_tokens"],
                cache_creation_tokens=tokens["cache_creation_tokens"],
            )
        except Exception as exc:  # noqa: BLE001 — surface as a wire event
            yield ErrorEvent(session_id=self.session_id, message=str(exc))

    async def interrupt(self) -> None:
        """Cancel an in-flight stream at the SDK level. When a tool is
        mid-execution this tells the Claude CLI to abort it rather than
        merely stopping the token stream. A no-op when no stream is
        active."""
        client = self._client
        if client is None:
            return
        try:
            await client.interrupt()
        except (ClaudeSDKError, OSError):
            # The SDK may refuse a second interrupt or fail if the
            # subprocess is already winding down. Swallow — the outer
            # WS handler breaks out of the stream loop regardless.
            pass

    def _translate_stream_event(self, event: dict[str, Any]) -> AgentEvent | None:
        """Turn an Anthropic streaming event dict into a wire event.

        Only `content_block_delta` with `text_delta` / `thinking_delta`
        payloads are surfaced — other event kinds (message_start,
        content_block_start, input_json_delta, etc.) are ignored because
        the rest of the pipeline keys off the completed blocks in the
        trailing `AssistantMessage`.
        """
        if event.get("type") != "content_block_delta":
            return None
        delta = event.get("delta") or {}
        delta_type = delta.get("type")
        if delta_type == "text_delta":
            text = delta.get("text") or ""
            return Token(session_id=self.session_id, text=text) if text else None
        if delta_type == "thinking_delta":
            text = delta.get("thinking") or ""
            return Thinking(session_id=self.session_id, text=text) if text else None
        return None

    def _translate_block(self, block: object) -> AgentEvent | None:
        if isinstance(block, TextBlock):
            return Token(session_id=self.session_id, text=block.text)
        if isinstance(block, ThinkingBlock):
            return Thinking(session_id=self.session_id, text=block.thinking)
        if isinstance(block, ToolUseBlock):
            return ToolCallStart(
                session_id=self.session_id,
                tool_call_id=block.id,
                name=block.name,
                input=dict(block.input),
            )
        if isinstance(block, ToolResultBlock):
            return self._tool_call_end(block)
        return None

    def _tool_call_end(self, block: ToolResultBlock) -> ToolCallEnd:
        is_error = bool(block.is_error)
        body = _stringify(block.content)
        return ToolCallEnd(
            session_id=self.session_id,
            tool_call_id=block.tool_use_id,
            ok=not is_error,
            output=None if is_error else body,
            error=body if is_error else None,
        )
