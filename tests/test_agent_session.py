from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from twrminal.agent.events import (
    ErrorEvent,
    MessageComplete,
    MessageStart,
    Thinking,
    Token,
    ToolCallEnd,
    ToolCallStart,
)
from twrminal.agent.session import AgentSession


def _result(session_id: str = "sdk-sess", total_cost_usd: float | None = None) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=total_cost_usd,
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
    assert session.max_budget_usd is None


@pytest.mark.asyncio
async def test_stream_omits_budget_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class CapturingClient(FakeClient):
        def __init__(self, messages: list[Any], options: Any = None) -> None:
            super().__init__(messages, options)
            captured["options"] = options

    def factory(options: Any = None) -> CapturingClient:
        return CapturingClient([_result()], options)

    monkeypatch.setattr("twrminal.agent.session.ClaudeSDKClient", factory)
    session = AgentSession("s", working_dir="/tmp", model="m")
    _ = [ev async for ev in session.stream("hi")]
    opts = captured["options"]
    assert opts.max_budget_usd is None


@pytest.mark.asyncio
async def test_stream_passes_budget_to_options(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class CapturingClient(FakeClient):
        def __init__(self, messages: list[Any], options: Any = None) -> None:
            super().__init__(messages, options)
            captured["options"] = options

    def factory(options: Any = None) -> CapturingClient:
        return CapturingClient([_result()], options)

    monkeypatch.setattr("twrminal.agent.session.ClaudeSDKClient", factory)
    session = AgentSession("s", working_dir="/tmp", model="m", max_budget_usd=0.25)
    _ = [ev async for ev in session.stream("hi")]
    opts = captured["options"]
    assert opts.max_budget_usd == 0.25


@pytest.mark.asyncio
async def test_stream_translates_text_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        [_assistant(TextBlock("hello ")), _assistant(TextBlock("world")), _result()],
    )
    session = AgentSession("s1", working_dir="/tmp", model="claude-sonnet-4-6")
    events = [ev async for ev in session.stream("hi")]
    assert [type(e).__name__ for e in events] == [
        "MessageStart",
        "Token",
        "Token",
        "MessageComplete",
    ]
    start = events[0]
    complete = events[-1]
    assert isinstance(start, MessageStart)
    assert isinstance(complete, MessageComplete)
    assert start.session_id == "s1"
    assert len(start.message_id) == 32
    assert start.message_id == complete.message_id
    tokens = [e for e in events if isinstance(e, Token)]
    assert [t.text for t in tokens] == ["hello ", "world"]


@pytest.mark.asyncio
async def test_stream_translates_thinking_block(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        [
            _assistant(
                ThinkingBlock(thinking="reasoning about the prompt", signature="sig"),
                TextBlock("answer"),
            ),
            _result(),
        ],
    )
    session = AgentSession("s", working_dir="/tmp", model="m")
    events = [ev async for ev in session.stream("hi")]
    types = [type(e).__name__ for e in events]
    assert types == ["MessageStart", "Thinking", "Token", "MessageComplete"]
    thinking = events[1]
    assert isinstance(thinking, Thinking)
    assert thinking.text == "reasoning about the prompt"


@pytest.mark.asyncio
async def test_stream_translates_tool_use_block(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = ToolUseBlock(id="tool-1", name="Read", input={"path": "/etc/hosts"})
    _patch_client(monkeypatch, [_assistant(TextBlock("looking..."), tool), _result()])
    session = AgentSession("s2", working_dir="/tmp", model="m")
    events = [ev async for ev in session.stream("read it")]
    assert [type(e).__name__ for e in events] == [
        "MessageStart",
        "Token",
        "ToolCallStart",
        "MessageComplete",
    ]
    call = events[2]
    assert isinstance(call, ToolCallStart)
    assert call.tool_call_id == "tool-1"
    assert call.name == "Read"
    assert call.input == {"path": "/etc/hosts"}


@pytest.mark.asyncio
async def test_stream_translates_tool_result_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(
        monkeypatch,
        [
            _assistant(ToolUseBlock(id="t-1", name="Read", input={"path": "/x"})),
            UserMessage(
                content=[
                    ToolResultBlock(tool_use_id="t-1", content="file contents", is_error=False)
                ]
            ),
            _result(),
        ],
    )
    session = AgentSession("s", working_dir="/tmp", model="m")
    events = [ev async for ev in session.stream("read it")]
    types = [type(e).__name__ for e in events]
    assert types == ["MessageStart", "ToolCallStart", "ToolCallEnd", "MessageComplete"]
    end = events[2]
    assert isinstance(end, ToolCallEnd)
    assert end.tool_call_id == "t-1"
    assert end.ok is True
    assert end.output == "file contents"
    assert end.error is None


@pytest.mark.asyncio
async def test_stream_marks_tool_result_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(
        monkeypatch,
        [
            _assistant(ToolUseBlock(id="t-err", name="Bash", input={"cmd": "false"})),
            UserMessage(
                content=[ToolResultBlock(tool_use_id="t-err", content="exit 1", is_error=True)]
            ),
            _result(),
        ],
    )
    session = AgentSession("s", working_dir="/tmp", model="m")
    events = [ev async for ev in session.stream("run it")]
    end = next(e for e in events if isinstance(e, ToolCallEnd))
    assert end.ok is False
    assert end.error == "exit 1"
    assert end.output is None


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
async def test_stream_message_complete_carries_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(
        monkeypatch,
        [_assistant(TextBlock("hi")), _result(total_cost_usd=0.0042)],
    )
    session = AgentSession("s", working_dir="/tmp", model="m")
    events = [ev async for ev in session.stream("x")]
    complete = events[-1]
    assert isinstance(complete, MessageComplete)
    assert complete.cost_usd == pytest.approx(0.0042)


@pytest.mark.asyncio
async def test_stream_message_complete_cost_none_when_sdk_omits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(monkeypatch, [_assistant(TextBlock("hi")), _result()])
    session = AgentSession("s", working_dir="/tmp", model="m")
    events = [ev async for ev in session.stream("x")]
    complete = events[-1]
    assert isinstance(complete, MessageComplete)
    assert complete.cost_usd is None


@pytest.mark.asyncio
async def test_interrupt_is_noop_when_no_active_stream() -> None:
    session = AgentSession("s", working_dir="/tmp", model="m")
    # Should not raise, should not error.
    await session.interrupt()
    assert session._client is None


@pytest.mark.asyncio
async def test_stream_tracks_client_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While an in-flight stream is running, `_client` points at the
    active SDK client so `interrupt()` can reach it. After the stream
    completes naturally, the reference drops."""
    seen: dict[str, Any] = {"mid_stream": None}

    def factory(options: Any = None) -> FakeClient:
        return FakeClient([_assistant(TextBlock("hi")), _result()], options)

    monkeypatch.setattr("twrminal.agent.session.ClaudeSDKClient", factory)
    session = AgentSession("s", working_dir="/tmp", model="m")
    async for ev in session.stream("go"):
        # Capture on the first non-MessageStart event so we know we're
        # inside the `async with` body.
        if not isinstance(ev, MessageStart) and seen["mid_stream"] is None:
            seen["mid_stream"] = session._client
    # After the generator runs to completion, reference drops.
    assert session._client is None
    assert seen["mid_stream"] is not None


@pytest.mark.asyncio
async def test_interrupt_during_stream_calls_sdk_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mid-stream `session.interrupt()` forwards to the active SDK
    client's `interrupt()` method. That's what tells the CLI subprocess
    to abort a running tool — cancelling the iteration alone wouldn't
    stop the tool."""

    class InterruptTrackingClient(FakeClient):
        def __init__(self, messages: list[Any], options: Any = None) -> None:
            super().__init__(messages, options)
            self.interrupt_calls = 0

        async def interrupt(self) -> None:
            self.interrupt_calls += 1

    ref: dict[str, InterruptTrackingClient] = {}

    def factory(options: Any = None) -> InterruptTrackingClient:
        client = InterruptTrackingClient([_assistant(TextBlock("running")), _result()], options)
        ref["client"] = client
        return client

    monkeypatch.setattr("twrminal.agent.session.ClaudeSDKClient", factory)
    session = AgentSession("s", working_dir="/tmp", model="m")
    async for ev in session.stream("go"):
        if isinstance(ev, Token):
            await session.interrupt()
    assert ref["client"].interrupt_calls == 1


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


@pytest.mark.asyncio
async def test_stream_passes_assembled_system_prompt_when_db_wired(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """With db= set, stream() calls assemble_prompt and passes the
    result through as ClaudeAgentOptions.system_prompt. Without db=
    (the prior behavior), system_prompt stays None."""
    from twrminal.agent.base_prompt import BASE_PROMPT
    from twrminal.db.store import (
        attach_tag,
        create_session,
        create_tag,
        init_db,
        put_tag_memory,
        update_session,
    )

    captured: dict[str, Any] = {}

    class CapturingClient(FakeClient):
        def __init__(self, messages: list[Any], options: Any = None) -> None:
            super().__init__(messages, options)
            captured["options"] = options

    def factory(options: Any = None) -> CapturingClient:
        return CapturingClient([_result()], options)

    monkeypatch.setattr("twrminal.agent.session.ClaudeSDKClient", factory)
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m")
        tag = await create_tag(conn, name="infra")
        await attach_tag(conn, sess["id"], tag["id"])
        await put_tag_memory(conn, tag["id"], "Prefer nftables.")
        await update_session(conn, sess["id"], fields={"session_instructions": "Be concise."})
        agent = AgentSession(sess["id"], working_dir="/x", model="m", db=conn)
        _ = [ev async for ev in agent.stream("hi")]
    finally:
        await conn.close()
    opts = captured["options"]
    assert opts.system_prompt is not None
    assert BASE_PROMPT in opts.system_prompt
    assert "Prefer nftables." in opts.system_prompt
    assert "Be concise." in opts.system_prompt


@pytest.mark.asyncio
async def test_stream_omits_system_prompt_when_db_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class CapturingClient(FakeClient):
        def __init__(self, messages: list[Any], options: Any = None) -> None:
            super().__init__(messages, options)
            captured["options"] = options

    def factory(options: Any = None) -> CapturingClient:
        return CapturingClient([_result()], options)

    monkeypatch.setattr("twrminal.agent.session.ClaudeSDKClient", factory)
    session = AgentSession("s", working_dir="/tmp", model="m")
    _ = [ev async for ev in session.stream("hi")]
    assert captured["options"].system_prompt is None
