"""HTTP surface + unit coverage for L4.3.2 — `POST /api/sessions/
{id}/invoke_reply_action/{message_id}`.

Wave 2 lane 2 of the assistant-reply action row (TODO.md). The route
backs the `✂ TLDR` button (and L4.3.3's `⚔ CRIT`): client POSTs an
action name + target message id, server validates, spawns a tool-less
sub-agent via `bearings.agent.sub_invoke.run_reply_action`, streams
text deltas back as SSE.

What we cover here:
  - Prompt assembly (template + fenced source) is stable.
  - Unknown action surfaces as a Failure event from the generator
    AND as 400 from the route.
  - Action enum is the single source of truth (catalog endpoint
    + `is_known_action` + the route's validation all agree).
  - Route validates message belongs to session + role == assistant.
  - Happy-path SSE stream yields the expected frames in the right
    order (`stream-open` comment → token frames → complete frame).
  - The Failure event from the sub-agent surfaces as an `event: error`
    SSE frame, not an HTTP 5xx.
  - 404 / 400 unhappy paths.

We monkeypatch `routes_reply_actions.run_reply_action` to a fake
async generator so tests don't talk to the real Claude SDK. Pure-
unit tests of `sub_invoke` (prompt assembly, action gating) drive
the module functions directly without any SDK dependency.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bearings.agent import sub_invoke
from bearings.agent.sub_invoke import (
    ACTION_LABELS,
    PROMPT_TEMPLATES,
    Complete,
    Failure,
    SubInvokeEvent,
    TextChunk,
    build_prompt,
    is_known_action,
)

# --- Pure-unit coverage for sub_invoke ---------------------------------


def test_summarize_action_is_registered() -> None:
    """Wave 2 ships `summarize` (lane 2, L4.3.2) and `critique`
    (lane 3, L4.3.3). Pinning both labels here keeps the action-enum
    contract honest — if we ever rename either we want the test to
    scream. The catalog endpoint test below mirrors the same set
    over HTTP."""
    assert "summarize" in PROMPT_TEMPLATES
    assert "summarize" in ACTION_LABELS
    assert ACTION_LABELS["summarize"] == "TL;DR"
    assert "critique" in PROMPT_TEMPLATES
    assert "critique" in ACTION_LABELS
    assert ACTION_LABELS["critique"] == "⚔ Critique"


def test_critique_prompt_covers_all_four_failure_modes() -> None:
    """The L4.3.3 brief specifies the critique prompt asks the sub-
    agent for four specific things: (a) factual claims, (b) edge
    cases, (c) silent-failure risks, (d) code that won't compile/
    run. Locking each substring here so a future "tighten the
    prompt" pass doesn't accidentally drop a category."""
    template = PROMPT_TEMPLATES["critique"]
    assert "factual claims" in template
    assert "edge cases" in template
    assert "silent-failure" in template
    assert "compile or run" in template
    # The "if sound, say so plainly" clause heads off invented-
    # problems failure mode — also load-bearing per the brief.
    assert "don't invent problems" in template


def test_is_known_action_gates_unknown_names() -> None:
    assert is_known_action("summarize") is True
    assert is_known_action("critique") is True
    assert is_known_action("transmogrify") is False
    assert is_known_action("") is False
    assert is_known_action("SUMMARIZE") is False  # case-sensitive enum


def test_build_prompt_wraps_source_in_assistant_reply_fence() -> None:
    """The fence is what stops the model confusing instruction text
    with content text — verify it's emitted verbatim. The template
    text appears before the fence and the source appears inside it."""
    prompt = build_prompt("summarize", "the body of the reply")
    assert prompt.startswith(PROMPT_TEMPLATES["summarize"])
    assert "<assistant-reply>\nthe body of the reply\n</assistant-reply>" in prompt


def test_build_prompt_preserves_source_verbatim() -> None:
    """Source text — including code-block fences and identifiers —
    must reach the model unmodified. The TL;DR prompt requires
    verbatim preservation; mangling here would defeat the contract."""
    src = "```py\ndef foo(): ...\n```\n\nSee `src/bearings/agent/sub_invoke.py`."
    prompt = build_prompt("summarize", src)
    assert src in prompt


# --- Helpers shared with the route tests -------------------------------


def _seed(
    client: TestClient,
    *,
    title: str = "parent",
    assistant_content: str = "the assistant said hello",
) -> dict[str, Any]:
    """Plant a session with one user / one assistant turn via the
    import endpoint (same pattern as test_spawn_from_reply). Returns
    the row plus a `_messages` list for convenience."""
    payload = {
        "session": {
            "working_dir": "/tmp/parent-cwd",
            "model": "claude-sonnet-4-6",
            "title": title,
        },
        "messages": [
            {
                "id": "u1",
                "role": "user",
                "content": "give me alpha",
                "created_at": "2026-04-22T00:00:01Z",
            },
            {
                "id": "a1",
                "role": "assistant",
                "content": assistant_content,
                "created_at": "2026-04-22T00:00:02Z",
            },
        ],
        "tool_calls": [],
    }
    resp = client.post("/api/sessions/import", json=payload)
    assert resp.status_code == 200, resp.text
    session = resp.json()
    msgs = client.get(f"/api/sessions/{session['id']}/messages").json()
    session["_messages"] = msgs
    return session


def _assistant_msg(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for m in messages:
        if m["role"] == "assistant":
            return m
    raise AssertionError("no assistant row in seeded session")


def _user_msg(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for m in messages:
        if m["role"] == "user":
            return m
    raise AssertionError("no user row in seeded session")


def _patch_run(
    monkeypatch: pytest.MonkeyPatch,
    events: list[SubInvokeEvent],
    captured: dict[str, Any] | None = None,
) -> None:
    """Replace `routes_reply_actions.run_reply_action` with a fake
    generator that yields `events` in order. The captured dict (if
    given) records the kwargs the route called us with so tests can
    assert on `action`, `model`, `source_text`, etc."""

    async def fake(**kwargs: Any) -> AsyncIterator[SubInvokeEvent]:
        if captured is not None:
            captured.update(kwargs)
        for ev in events:
            yield ev

    monkeypatch.setattr("bearings.api.routes_reply_actions.run_reply_action", fake)


def _parse_sse(body: str) -> list[dict[str, str]]:
    """Parse an SSE body into a list of `{event, data}` dicts. Comment
    lines (`: ...`) become `{event: 'comment', data: '...'}` so tests
    can assert on the open-stream ping. The stock SSE wire format is
    line-delimited frames separated by blank lines."""
    frames: list[dict[str, str]] = []
    for raw_frame in body.split("\n\n"):
        if not raw_frame.strip():
            continue
        frame: dict[str, str] = {}
        for line in raw_frame.splitlines():
            if line.startswith(":"):
                frame.setdefault("event", "comment")
                frame["data"] = line[1:].strip()
            elif line.startswith("event:"):
                frame["event"] = line[len("event:") :].strip()
            elif line.startswith("data:"):
                frame["data"] = line[len("data:") :].strip()
        if frame:
            frames.append(frame)
    return frames


# --- Route coverage ----------------------------------------------------


def test_invoke_reply_action_streams_token_then_complete(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: route emits the open-stream comment, then one
    `event: token` per TextChunk, then `event: complete` carrying the
    cost. Order matters — the modal renders progressively and shows
    the cost footer only after `complete`."""
    parent = _seed(client)
    assistant = _assistant_msg(parent["_messages"])
    captured: dict[str, Any] = {}
    _patch_run(
        monkeypatch,
        [
            TextChunk(text="alpha "),
            TextChunk(text="beta"),
            Complete(cost_usd=0.0123, full_text="alpha beta"),
        ],
        captured=captured,
    )

    resp = client.post(
        f"/api/sessions/{parent['id']}/invoke_reply_action/{assistant['id']}",
        json={"action": "summarize"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    frames = _parse_sse(resp.text)
    # First frame is the stream-open comment ping.
    assert frames[0]["event"] == "comment"
    # Then two token frames in send order.
    token_frames = [f for f in frames if f["event"] == "token"]
    assert len(token_frames) == 2
    assert token_frames[0]["data"] == '{"text": "alpha "}'
    assert token_frames[1]["data"] == '{"text": "beta"}'
    # Then exactly one complete frame.
    complete = [f for f in frames if f["event"] == "complete"]
    assert len(complete) == 1
    assert '"cost_usd": 0.0123' in complete[0]["data"]
    assert '"full_text": "alpha beta"' in complete[0]["data"]
    # The route forwarded the right kwargs to sub_invoke. Source text =
    # the assistant message content; model defaults to the parent's.
    assert captured["action"] == "summarize"
    assert captured["source_text"] == "the assistant said hello"
    assert captured["model"] == "claude-sonnet-4-6"
    assert captured["working_dir"] == "/tmp/parent-cwd"
    assert captured["parent_session_id"] == parent["id"]


def test_invoke_reply_action_failure_event_streams_as_sse_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Failure from the sub-agent must reach the modal as an SSE
    `event: error` frame, NOT as an HTTP 5xx. The connection has
    already returned 200; a mid-stream failure has to wire-encode."""
    parent = _seed(client)
    assistant = _assistant_msg(parent["_messages"])
    _patch_run(
        monkeypatch,
        [Failure(message="model unavailable")],
    )

    resp = client.post(
        f"/api/sessions/{parent['id']}/invoke_reply_action/{assistant['id']}",
        json={"action": "summarize"},
    )
    assert resp.status_code == 200
    frames = _parse_sse(resp.text)
    error = [f for f in frames if f["event"] == "error"]
    assert len(error) == 1
    assert "model unavailable" in error[0]["data"]


def test_invoke_reply_action_explicit_model_override(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the body carries `model`, the route forwards it instead
    of inheriting the parent's. Lets the frontend force a cheaper
    model for previews without changing the parent session."""
    parent = _seed(client)
    assistant = _assistant_msg(parent["_messages"])
    captured: dict[str, Any] = {}
    _patch_run(monkeypatch, [Complete(cost_usd=None, full_text="")], captured=captured)

    resp = client.post(
        f"/api/sessions/{parent['id']}/invoke_reply_action/{assistant['id']}",
        json={"action": "summarize", "model": "claude-haiku-4-5"},
    )
    assert resp.status_code == 200
    assert captured["model"] == "claude-haiku-4-5"


def test_invoke_reply_action_unknown_action_400(client: TestClient) -> None:
    """Unknown action is a client bug — surface as 400 BEFORE we
    spawn anything. (No monkeypatch: should never reach sub_invoke.)"""
    parent = _seed(client)
    assistant = _assistant_msg(parent["_messages"])
    resp = client.post(
        f"/api/sessions/{parent['id']}/invoke_reply_action/{assistant['id']}",
        json={"action": "transmogrify"},
    )
    assert resp.status_code == 400
    assert "unknown action" in resp.json()["detail"].lower()


def test_invoke_reply_action_rejects_user_message_400(
    client: TestClient,
) -> None:
    """Reply-actions are reply-scoped — user prompts have nothing
    useful to summarize / critique. Mirror of spawn_from_reply's
    same guard."""
    parent = _seed(client)
    user = _user_msg(parent["_messages"])
    resp = client.post(
        f"/api/sessions/{parent['id']}/invoke_reply_action/{user['id']}",
        json={"action": "summarize"},
    )
    assert resp.status_code == 400
    assert "assistant" in resp.json()["detail"].lower()


def test_invoke_reply_action_cross_session_message_400(
    client: TestClient,
) -> None:
    a = _seed(client, title="a")
    b = _seed(client, title="b")
    foreign = _assistant_msg(b["_messages"])
    resp = client.post(
        f"/api/sessions/{a['id']}/invoke_reply_action/{foreign['id']}",
        json={"action": "summarize"},
    )
    assert resp.status_code == 400


def test_invoke_reply_action_unknown_message_404(client: TestClient) -> None:
    parent = _seed(client)
    resp = client.post(
        f"/api/sessions/{parent['id']}/invoke_reply_action/no-such-msg",
        json={"action": "summarize"},
    )
    assert resp.status_code == 404


def test_invoke_reply_action_unknown_session_404(client: TestClient) -> None:
    resp = client.post(
        "/api/sessions/no-such-session/invoke_reply_action/some-msg",
        json={"action": "summarize"},
    )
    assert resp.status_code == 404


def test_reply_actions_catalog_lists_registered_actions(
    client: TestClient,
) -> None:
    """The catalog endpoint mirrors the in-process `ACTION_LABELS`
    dict so the frontend can render labels without hardcoding the
    enum. Both Wave 2 actions must round-trip; the frontend's modal
    badge is what gives the user visual confirmation of which sub-
    agent ran."""
    resp = client.get("/api/sessions/reply_actions/catalog")
    assert resp.status_code == 200
    catalog = resp.json()
    assert catalog["summarize"]["label"] == "TL;DR"
    assert catalog["critique"]["label"] == "⚔ Critique"


def test_invoke_reply_action_critique_is_a_valid_action(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L4.3.3 — `critique` reaches the route's action validator and
    is forwarded to `run_reply_action` with the right kwargs. Unlike
    `summarize`, this asserts the *route* accepts the new enum value
    (the sub_invoke layer is covered by the gating tests above)."""
    parent = _seed(client)
    assistant = _assistant_msg(parent["_messages"])
    captured: dict[str, Any] = {}
    _patch_run(
        monkeypatch,
        [
            TextChunk(text="(a) the claim about X is unverified."),
            Complete(cost_usd=0.01, full_text="(a) the claim about X is unverified."),
        ],
        captured=captured,
    )

    resp = client.post(
        f"/api/sessions/{parent['id']}/invoke_reply_action/{assistant['id']}",
        json={"action": "critique"},
    )
    assert resp.status_code == 200
    assert captured["action"] == "critique"
    assert captured["source_text"] == "the assistant said hello"


# --- sub_invoke generator unit test ------------------------------------


@pytest.mark.asyncio
async def test_run_reply_action_unknown_action_yields_failure() -> None:
    """The generator's own input gate. A bad action is caught before
    any SDK setup happens, so this test runs without monkeypatching
    `ClaudeSDKClient`."""
    events: list[SubInvokeEvent] = []
    async for ev in sub_invoke.run_reply_action(
        action="not-a-real-action",
        source_text="anything",
        working_dir="/tmp",
        model="claude-sonnet-4-6",
        db=None,
        parent_session_id=None,
    ):
        events.append(ev)
    assert len(events) == 1
    assert isinstance(events[0], Failure)
    assert "unknown action" in events[0].message.lower()
