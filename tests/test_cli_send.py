from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from twrminal.cli import _run_send


class FakeWS:
    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self._frames = frames
        self.sent: list[str] = []

    async def __aenter__(self) -> FakeWS:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def send(self, text: str) -> None:
        self.sent.append(text)

    def __aiter__(self) -> AsyncIterator[str]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[str]:
        for frame in self._frames:
            yield json.dumps(frame)


def _patch_connect(monkeypatch: pytest.MonkeyPatch, frames: list[dict[str, Any]]) -> FakeWS:
    ws = FakeWS(frames)

    def factory(url: str) -> FakeWS:
        return ws

    monkeypatch.setattr("twrminal.cli.ws_connect", factory)
    return ws


@pytest.mark.asyncio
async def test_send_sends_prompt_and_prints_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = _patch_connect(
        monkeypatch,
        [
            {"type": "token", "session_id": "s", "text": "hi "},
            {"type": "token", "session_id": "s", "text": "there"},
            {"type": "message_complete", "session_id": "s", "message_id": "m1"},
        ],
    )
    out = io.StringIO()
    rc = await _run_send("ws://localhost:8787/ws/sessions/s", "say hi", out)
    assert rc == 0
    assert json.loads(ws.sent[0]) == {"type": "prompt", "content": "say hi"}
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [event["type"] for event in lines] == ["token", "token", "message_complete"]


@pytest.mark.asyncio
async def test_send_returns_nonzero_on_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_connect(
        monkeypatch,
        [
            {"type": "token", "session_id": "s", "text": "oops"},
            {"type": "error", "session_id": "s", "message": "boom"},
        ],
    )
    out = io.StringIO()
    rc = await _run_send("ws://localhost:8787/ws/sessions/s", "x", out)
    assert rc == 1
