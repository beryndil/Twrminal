from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UserMessage(BaseModel):
    type: Literal["user_message"] = "user_message"
    session_id: str
    content: str


class Token(BaseModel):
    type: Literal["token"] = "token"
    session_id: str
    text: str


class Thinking(BaseModel):
    type: Literal["thinking"] = "thinking"
    session_id: str
    text: str


class ToolCallStart(BaseModel):
    type: Literal["tool_call_start"] = "tool_call_start"
    session_id: str
    tool_call_id: str
    name: str
    input: dict[str, object] = Field(default_factory=dict)


class ToolCallEnd(BaseModel):
    type: Literal["tool_call_end"] = "tool_call_end"
    session_id: str
    tool_call_id: str
    ok: bool
    output: str | None = None
    error: str | None = None


class ToolOutputDelta(BaseModel):
    """Incremental chunk of tool output produced while a tool call is
    still running. Frontend reducer appends `delta` to the matching
    tool call's `output`. Deltas MUST be emitted before the final
    `ToolCallEnd` for the same `tool_call_id`; the reducer drops any
    delta whose target call is already finished. Sources that feed
    these events are expected to line-buffer (see
    `agent/line_buffer.py`) so chunks never split multibyte UTF-8
    codepoints or ANSI escape sequences mid-sequence."""

    type: Literal["tool_output_delta"] = "tool_output_delta"
    session_id: str
    tool_call_id: str
    delta: str


class MessageStart(BaseModel):
    type: Literal["message_start"] = "message_start"
    session_id: str
    message_id: str


class MessageComplete(BaseModel):
    type: Literal["message_complete"] = "message_complete"
    session_id: str
    message_id: str
    cost_usd: float | None = None


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    session_id: str
    message: str


AgentEvent = (
    UserMessage
    | Token
    | Thinking
    | ToolCallStart
    | ToolCallEnd
    | ToolOutputDelta
    | MessageStart
    | MessageComplete
    | ErrorEvent
)
