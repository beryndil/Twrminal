from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import aiosqlite
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from twrminal.agent.events import (
    AgentEvent,
    ErrorEvent,
    MessageComplete,
    MessageStart,
    Thinking,
    Token,
    ToolCallEnd,
    ToolCallStart,
)
from twrminal.agent.prompt import assemble_prompt


def _stringify(content: str | list[dict[str, object]] | None) -> str | None:
    if content is None or isinstance(content, str):
        return content
    return json.dumps(content)


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
    ) -> None:
        self.session_id = session_id
        self.working_dir = working_dir
        self.model = model
        self.max_budget_usd = max_budget_usd
        # Optional DB connection for the v0.2 prompt assembler. When
        # set, `stream()` calls `assemble_prompt` and passes the
        # concatenated layered prompt as `system_prompt`. Unit tests
        # that don't exercise persistence can leave it None; the WS
        # handler wires it in production.
        self.db = db
        # Tracks the currently-active SDK client so `interrupt()` can
        # reach into an in-flight stream. Set inside `stream()` under
        # the `async with`; cleared on exit.
        self._client: ClaudeSDKClient | None = None

    async def stream(self, prompt: str) -> AsyncIterator[AgentEvent]:
        options_kwargs: dict[str, Any] = {
            "cwd": self.working_dir,
            "model": self.model,
            "include_partial_messages": True,
        }
        if self.max_budget_usd is not None:
            options_kwargs["max_budget_usd"] = self.max_budget_usd
        if self.db is not None:
            # Assemble the layered system prompt (base → project → tag
            # memories → session instructions) from the current DB
            # state. Called per turn so edits to project prompt / tag
            # memories / session instructions take effect on the next
            # prompt without restarting the WS.
            assembled = await assemble_prompt(self.db, self.session_id)
            options_kwargs["system_prompt"] = assembled.text
        options = ClaudeAgentOptions(**options_kwargs)
        message_id = uuid4().hex
        cost_usd: float | None = None
        try:
            async with ClaudeSDKClient(options=options) as client:
                self._client = client
                try:
                    await client.query(prompt)
                    yield MessageStart(session_id=self.session_id, message_id=message_id)
                    async for msg in client.receive_response():
                        if isinstance(msg, AssistantMessage):
                            for block in msg.content:
                                event = self._translate_block(block)
                                if event is not None:
                                    yield event
                        elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
                            for block in msg.content:
                                if isinstance(block, ToolResultBlock):
                                    yield self._tool_call_end(block)
                        elif isinstance(msg, ResultMessage):
                            cost_usd = msg.total_cost_usd
                            break
                finally:
                    self._client = None
            yield MessageComplete(
                session_id=self.session_id,
                message_id=message_id,
                cost_usd=cost_usd,
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
