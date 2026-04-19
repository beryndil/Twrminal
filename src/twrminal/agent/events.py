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


class MessageStart(BaseModel):
    type: Literal["message_start"] = "message_start"
    session_id: str
    message_id: str


class MessageComplete(BaseModel):
    type: Literal["message_complete"] = "message_complete"
    session_id: str
    message_id: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    session_id: str
    message: str


AgentEvent = (
    UserMessage | Token | ToolCallStart | ToolCallEnd | MessageStart | MessageComplete | ErrorEvent
)
