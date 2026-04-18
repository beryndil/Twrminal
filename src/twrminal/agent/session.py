from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from twrminal.agent.events import (
    AgentEvent,
    ErrorEvent,
    MessageComplete,
    Token,
    ToolCallStart,
)


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
                async for msg in client.receive_response():
                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock):
                                yield Token(session_id=self.session_id, text=block.text)
                            elif isinstance(block, ToolUseBlock):
                                yield ToolCallStart(
                                    session_id=self.session_id,
                                    tool_call_id=block.id,
                                    name=block.name,
                                    input=dict(block.input),
                                )
                    elif isinstance(msg, ResultMessage):
                        break
            yield MessageComplete(session_id=self.session_id, message_id=message_id)
        except Exception as exc:  # noqa: BLE001 — surface as a wire event
            yield ErrorEvent(session_id=self.session_id, message=str(exc))
