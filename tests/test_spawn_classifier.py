"""Unit tests for ``bearings.agent.spawn_classifier``.

Coverage:
  - _heuristic_title strips markdown prefixes, caps at 60 chars
  - _extract_json_block tolerates preamble text / code fences
  - _validate_result accepts + normalises each shape
  - _validate_result rejects malformed payloads
  - classify_reply returns LLM result on success
  - classify_reply falls back to single_chat on parse failure
  - classify_reply falls back to single_chat on exception
  - classify_reply falls back after 2 attempts
  - _fallback produces valid single_chat with title from reply
"""

from __future__ import annotations

import pytest

from bearings.agent.spawn_classifier import (
    _build_user_prompt,
    _extract_json_block,
    _fallback,
    _heuristic_title,
    _validate_result,
    classify_reply,
)
from bearings.api.models.spawn_classify import SpawnShape

# ---------------------------------------------------------------------------
# _heuristic_title
# ---------------------------------------------------------------------------


def test_heuristic_title_plain_line() -> None:
    assert _heuristic_title("Hello world") == "Hello world"


def test_heuristic_title_strips_heading() -> None:
    assert _heuristic_title("## Section") == "Section"


def test_heuristic_title_strips_bullet() -> None:
    assert _heuristic_title("- item one\n- item two") == "item one"


def test_heuristic_title_strips_numbered() -> None:
    assert _heuristic_title("1. First step\n2. Second") == "First step"


def test_heuristic_title_caps_at_60() -> None:
    long = "x" * 70
    result = _heuristic_title(long)
    assert len(result) <= 60
    assert result.endswith("…")


def test_heuristic_title_skips_blank_lines() -> None:
    assert _heuristic_title("\n\n  \nHello") == "Hello"


def test_heuristic_title_empty_reply() -> None:
    assert _heuristic_title("") == "Spawned reply"


# ---------------------------------------------------------------------------
# _extract_json_block
# ---------------------------------------------------------------------------


def test_extract_json_block_plain() -> None:
    text = '{"shape":"single_chat","reason":"ok","suggested":{"title":"T","description":"D"}}'
    result = _extract_json_block(text)
    assert result is not None
    assert result["shape"] == "single_chat"


def test_extract_json_block_with_preamble() -> None:
    text = 'Here is my answer:\n{"shape":"checklist","reason":"r","suggested":[]}'
    result = _extract_json_block(text)
    assert result is not None
    assert result["shape"] == "checklist"


def test_extract_json_block_no_json() -> None:
    assert _extract_json_block("no braces here") is None


def test_extract_json_block_malformed() -> None:
    assert _extract_json_block("{not valid json}") is None


# ---------------------------------------------------------------------------
# _validate_result — single_chat
# ---------------------------------------------------------------------------


def test_validate_single_chat_ok() -> None:
    parsed = {
        "shape": "single_chat",
        "reason": "It is one thing",
        "suggested": {"title": "My title", "description": "Some desc"},
    }
    result = _validate_result(parsed)
    assert result is not None
    assert result.shape is SpawnShape.single_chat
    assert result.suggested_single is not None
    assert result.suggested_single.title == "My title"
    assert result.suggested_multi is None
    assert result.suggested_checklist is None


def test_validate_single_chat_missing_title_returns_none() -> None:
    parsed = {
        "shape": "single_chat",
        "reason": "ok",
        "suggested": {"description": "no title here"},
    }
    assert _validate_result(parsed) is None


def test_validate_single_chat_wrong_suggested_type() -> None:
    parsed = {"shape": "single_chat", "reason": "ok", "suggested": ["list", "not", "dict"]}
    assert _validate_result(parsed) is None


# ---------------------------------------------------------------------------
# _validate_result — multi_chat
# ---------------------------------------------------------------------------


def test_validate_multi_chat_ok() -> None:
    parsed = {
        "shape": "multi_chat",
        "reason": "Three options",
        "suggested": [
            {"title": "A", "description": "desc A"},
            {"title": "B", "description": "desc B"},
            {"title": "C", "description": "desc C"},
        ],
    }
    result = _validate_result(parsed)
    assert result is not None
    assert result.shape is SpawnShape.multi_chat
    assert result.suggested_multi is not None
    assert len(result.suggested_multi) == 3
    assert result.suggested_multi[0].title == "A"


def test_validate_multi_chat_caps_at_5() -> None:
    parsed = {
        "shape": "multi_chat",
        "reason": "Many options",
        "suggested": [{"title": str(i), "description": "d"} for i in range(8)],
    }
    result = _validate_result(parsed)
    assert result is not None
    assert len(result.suggested_multi) == 5  # type: ignore[arg-type]


def test_validate_multi_chat_only_one_item_returns_none() -> None:
    parsed = {
        "shape": "multi_chat",
        "reason": "single option",
        "suggested": [{"title": "A", "description": "d"}],
    }
    assert _validate_result(parsed) is None


def test_validate_multi_chat_not_list_returns_none() -> None:
    parsed = {
        "shape": "multi_chat",
        "reason": "ok",
        "suggested": {"title": "A", "description": "d"},
    }
    assert _validate_result(parsed) is None


# ---------------------------------------------------------------------------
# _validate_result — checklist
# ---------------------------------------------------------------------------


def test_validate_checklist_ok() -> None:
    parsed = {
        "shape": "checklist",
        "reason": "Sequential steps",
        "suggested": [
            {"label": "Step 1", "notes": "Do this"},
            {"label": "Step 2", "notes": "Then that"},
        ],
    }
    result = _validate_result(parsed)
    assert result is not None
    assert result.shape is SpawnShape.checklist
    assert result.suggested_checklist is not None
    assert len(result.suggested_checklist) == 2
    assert result.suggested_checklist[0].label == "Step 1"


def test_validate_checklist_only_one_item_returns_none() -> None:
    parsed = {
        "shape": "checklist",
        "reason": "one step",
        "suggested": [{"label": "Only", "notes": ""}],
    }
    assert _validate_result(parsed) is None


def test_validate_unknown_shape_returns_none() -> None:
    parsed = {"shape": "hexagon", "reason": "ok", "suggested": {}}
    assert _validate_result(parsed) is None


# ---------------------------------------------------------------------------
# classify_reply — integration via query_fn seam
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_reply_single_chat() -> None:
    async def fake_query(_reply: str) -> str:
        return (
            '{"shape":"single_chat","reason":"one thing",'
            '"suggested":{"title":"My T","description":"My D"}}'
        )

    result = await classify_reply("some reply", model="claude-haiku-4-5", query_fn=fake_query)
    assert result.shape is SpawnShape.single_chat
    assert result.suggested_single is not None
    assert result.suggested_single.title == "My T"


@pytest.mark.asyncio
async def test_classify_reply_multi_chat() -> None:
    async def fake_query(_reply: str) -> str:
        return (
            '{"shape":"multi_chat","reason":"options","suggested":'
            '[{"title":"A","description":"da"},{"title":"B","description":"db"}]}'
        )

    result = await classify_reply(
        "reply with options", model="claude-haiku-4-5", query_fn=fake_query
    )
    assert result.shape is SpawnShape.multi_chat
    assert result.suggested_multi is not None
    assert len(result.suggested_multi) == 2


@pytest.mark.asyncio
async def test_classify_reply_checklist() -> None:
    async def fake_query(_reply: str) -> str:
        return (
            '{"shape":"checklist","reason":"steps","suggested":'
            '[{"label":"Step 1","notes":"n1"},{"label":"Step 2","notes":"n2"}]}'
        )

    result = await classify_reply(
        "step-by-step reply", model="claude-haiku-4-5", query_fn=fake_query
    )
    assert result.shape is SpawnShape.checklist
    assert result.suggested_checklist is not None
    assert result.suggested_checklist[1].label == "Step 2"


@pytest.mark.asyncio
async def test_classify_reply_falls_back_on_bad_json() -> None:
    async def fake_query(_reply: str) -> str:
        return "not json at all"

    result = await classify_reply("reply", model="claude-haiku-4-5", query_fn=fake_query)
    assert result.shape is SpawnShape.single_chat
    assert "classifier disabled or failed" in result.reason


@pytest.mark.asyncio
async def test_classify_reply_falls_back_on_exception() -> None:
    async def fake_query(_reply: str) -> str:
        raise RuntimeError("network down")

    result = await classify_reply("reply", model="claude-haiku-4-5", query_fn=fake_query)
    assert result.shape is SpawnShape.single_chat


@pytest.mark.asyncio
async def test_classify_reply_retries_before_fallback() -> None:
    calls: list[int] = []

    async def fake_query(_reply: str) -> str:
        calls.append(1)
        return "bad"

    await classify_reply("reply", model="claude-haiku-4-5", query_fn=fake_query)
    assert len(calls) == 2  # two attempts before fallback


# ---------------------------------------------------------------------------
# _fallback
# ---------------------------------------------------------------------------


def test_fallback_shape_and_reason() -> None:
    result = _fallback("hello")
    assert result.shape is SpawnShape.single_chat
    assert "classifier disabled or failed" in result.reason


def test_fallback_title_from_reply() -> None:
    result = _fallback("## My heading\n\nsome body")
    assert result.suggested_single is not None
    assert result.suggested_single.title == "My heading"


def test_fallback_empty_reply() -> None:
    result = _fallback("")
    assert result.suggested_single is not None
    assert result.suggested_single.title  # non-empty


# ---------------------------------------------------------------------------
# _build_user_prompt
# ---------------------------------------------------------------------------


def test_build_user_prompt_truncates() -> None:
    long_reply = "x" * 5000
    prompt = _build_user_prompt(long_reply)
    assert "truncated" in prompt
    assert len(prompt) < 5500  # reasonable upper bound


def test_build_user_prompt_no_truncation_short() -> None:
    prompt = _build_user_prompt("short reply")
    assert "truncated" not in prompt
    assert "short reply" in prompt
