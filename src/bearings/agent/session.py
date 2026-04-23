from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import aiosqlite
from claude_agent_sdk import (
    AssistantMessage,
    CanUseTool,
    ClaudeAgentOptions,
    ClaudeSDKClient,
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
)
from bearings.agent.prompt import assemble_prompt
from bearings.db._messages import list_messages

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

    def set_permission_mode(self, mode: PermissionMode | None) -> None:
        self.permission_mode = mode

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

        Best-effort: any SDK or parsing failure returns None and the
        turn continues. The context meter is purely advisory — losing
        an update must not take down a successful turn. Swallowing
        errors here is the one place in this module where we accept a
        silent miss; everywhere else errors surface as `ErrorEvent`."""
        try:
            resp = await client.get_context_usage()
        except Exception:
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
        except Exception:
            return None

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
        message_id = uuid4().hex
        cost_usd: float | None = None
        usage: dict[str, Any] | None = None
        context_event: ContextUsage | None = None
        try:
            async with ClaudeSDKClient(options=options) as client:
                self._client = client
                try:
                    await client.query(prompt)
                    yield MessageStart(session_id=self.session_id, message_id=message_id)
                    # Track per-block-type streaming. Opus 4.7 in adaptive
                    # mode emits text_delta but NOT thinking_delta — the
                    # thinking content only arrives in the final
                    # AssistantMessage's ThinkingBlock. A single
                    # streamed_this_msg flag would drop that thinking
                    # block as a "duplicate" because text_delta fired.
                    # Track each block type independently so we only
                    # suppress the kind we actually saw streamed.
                    streamed_text = False
                    streamed_thinking = False
                    async for msg in client.receive_response():
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
                                if event is not None:
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
                            break
                    # Capture the context-usage snapshot while the CLI
                    # subprocess is still live. The async-with exit
                    # below tears it down; calling afterward would hit
                    # a closed connection.
                    context_event = await self._capture_context_usage(client)
                finally:
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
        except Exception:
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
