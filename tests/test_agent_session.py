from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from twrminal.agent.events import ErrorEvent, MessageComplete, Token, ToolCallStart
from twrminal.agent.session import AgentSession


def _result(session_id: str = "sdk-sess") -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session_id,
    )


def _assistant(*blocks: Any) -> AssistantMessage:
    return AssistantMessage(content=list(blocks), model="claude-sonnet-4-6")


class FakeClient:
    """Drop-in replacement for ClaudeSDKClient used in unit tests."""

    def __init__(self, messages: list[Any], options: Any = None) -> None:
        self._messages = messages
        self.options = options
        self.queried: list[str] = []

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def query(self, prompt: str) -> None:
        self.queried.append(prompt)

    async def receive_response(self) -> AsyncIterator[Any]:
        for msg in self._messages:
            yield msg


def _patch_client(monkeypatch: pytest.MonkeyPatch, messages: list[Any]) -> None:
    def factory(options: Any = None) -> FakeClient:
        return FakeClient(messages, options)

    monkeypatch.setattr("twrminal.agent.session.ClaudeSDKClient", factory)


def test_agent_session_constructs() -> None:
    session = AgentSession("abc", working_dir="/tmp", model="claude-opus-4-7")
    assert session.session_id == "abc"
    assert session.working_dir == "/tmp"
    assert session.model == "claude-opus-4-7"


@pytest.mark.asyncio
async def test_stream_translates_text_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        [_assistant(TextBlock("hello ")), _assistant(TextBlock("world")), _result()],
    )
    session = AgentSession("s1", working_dir="/tmp", model="claude-sonnet-4-6")
    events = [ev async for ev in session.stream("hi")]
    assert [type(e).__name__ for e in events] == ["Token", "Token", "MessageComplete"]
    tokens = [e for e in events if isinstance(e, Token)]
    assert [t.text for t in tokens] == ["hello ", "world"]
    complete = events[-1]
    assert isinstance(complete, MessageComplete)
    assert complete.session_id == "s1"
    assert len(complete.message_id) == 32


@pytest.mark.asyncio
async def test_stream_translates_tool_use_block(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = ToolUseBlock(id="tool-1", name="Read", input={"path": "/etc/hosts"})
    _patch_client(monkeypatch, [_assistant(TextBlock("looking..."), tool), _result()])
    session = AgentSession("s2", working_dir="/tmp", model="m")
    events = [ev async for ev in session.stream("read it")]
    assert [type(e).__name__ for e in events] == [
        "Token",
        "ToolCallStart",
        "MessageComplete",
    ]
    call = events[1]
    assert isinstance(call, ToolCallStart)
    assert call.tool_call_id == "tool-1"
    assert call.name == "Read"
    assert call.input == {"path": "/etc/hosts"}


@pytest.mark.asyncio
async def test_stream_stops_on_result_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        [_assistant(TextBlock("pre")), _result(), _assistant(TextBlock("post"))],
    )
    session = AgentSession("s3", working_dir="/tmp", model="m")
    events = [ev async for ev in session.stream("x")]
    tokens = [e for e in events if isinstance(e, Token)]
    assert [t.text for t in tokens] == ["pre"]


@pytest.mark.asyncio
async def test_stream_emits_error_event_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BoomClient(FakeClient):
        async def query(self, prompt: str) -> None:
            raise RuntimeError("kaboom")

    def factory(options: Any = None) -> BoomClient:
        return BoomClient([], options)

    monkeypatch.setattr("twrminal.agent.session.ClaudeSDKClient", factory)
    session = AgentSession("s4", working_dir="/tmp", model="m")
    events = [ev async for ev in session.stream("x")]
    assert len(events) == 1
    err = events[0]
    assert isinstance(err, ErrorEvent)
    assert "kaboom" in err.message
