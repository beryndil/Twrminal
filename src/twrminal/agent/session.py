from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import uuid4

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from twrminal.agent.events import (
    AgentEvent,
    ErrorEvent,
    MessageComplete,
    MessageStart,
    Token,
    ToolCallEnd,
    ToolCallStart,
)


def _stringify(content: str | list[dict[str, object]] | None) -> str | None:
    if content is None or isinstance(content, str):
        return content
    return json.dumps(content)


class AgentSession:
    """Wraps a single Claude Code agent session via claude-agent-sdk.

    One instance per WebSocket connection; a short-lived `ClaudeSDKClient`
    is created for each `stream()` call.
    """

    def __init__(self, session_id: str, working_dir: str, model: str) -> None:
        self.session_id = session_id
        self.working_dir = working_dir
        self.model = model

    async def stream(self, prompt: str) -> AsyncIterator[AgentEvent]:
        options = ClaudeAgentOptions(
            cwd=self.working_dir,
            model=self.model,
            include_partial_messages=True,
        )
        message_id = uuid4().hex
        try:
            async with ClaudeSDKClient(options=options) as client:
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
                        break
            yield MessageComplete(session_id=self.session_id, message_id=message_id)
        except Exception as exc:  # noqa: BLE001 — surface as a wire event
            yield ErrorEvent(session_id=self.session_id, message=str(exc))

    def _translate_block(self, block: object) -> AgentEvent | None:
        if isinstance(block, TextBlock):
            return Token(session_id=self.session_id, text=block.text)
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
