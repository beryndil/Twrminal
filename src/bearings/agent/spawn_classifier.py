"""Wave 3 spawn-from-reply classifier
(`~/.claude/plans/classifying-spawn-reply-wave-3.md`).

One-shot LLM caller that reads an assistant reply and classifies its
shape as one of:

  - ``single_chat``  — the reply is a single coherent piece of content
    (explanation, code, analysis). Default when ambiguous.
  - ``multi_chat``   — the reply proposes N independent approaches /
    options / recommendations each worth its own exploration thread.
    Capped at N=5 to prevent an accidental 30-chat fan-out.
  - ``checklist``    — the reply enumerates N sequential action items
    (installation steps, migration steps, audit points) the operator
    needs to tick off one by one.

Mirrors ``title_suggester.py`` 1:1 in structure — same SDK, same
two-attempt retry, same JSON-block extraction, same ``query_fn`` test
seam — so the validation patterns the codebase already tests carry
over without surprise.

The route handler in ``bearings.api.routes_spawn_classify`` enforces
the config gate (``agent.enable_llm_spawn_classifier``) and the
session/message validation; this module is a pure helper and assumes
the caller has already cleared those gates. The classifier **never
raises** — fallback_result() is always the last-resort return so the
endpoint can guarantee a 200 response.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from bearings.api.models.spawn_classify import (
    ChecklistPayload,
    MultiChatPayload,
    SingleChatPayload,
    SpawnClassifyResult,
    SpawnShape,
)

logger = logging.getLogger(__name__)

# Hard cap on the number of multi_chat suggestions surfaced to the UI.
# Five is generous for an exploration fan-out; anything larger is likely
# the model over-splitting a reply that is really a single-chat or a
# checklist. Surfaced in the system prompt so the model's count never
# exceeds it without needing a post-hoc truncation.
_MULTI_CHAT_CAP = 5

# Per-reply character cap fed into the prompt. The full reply is used;
# this cap exists to guard against pathological inputs (a 100 kB bash
# log pasted as a reply). 4 000 chars ≈ 1 000 tokens — enough to read
# structure, not enough to blow the Haiku input budget.
_REPLY_CHAR_CAP = 4000

_SYSTEM_PROMPT = f"""You are a spawn-shape classifier for Bearings, a Claude Code session manager.

You read an assistant reply and decide which spawn shape fits best:

  - "single_chat"  : The reply is one coherent piece of content (an
    explanation, a code diff, a single recommendation). DEFAULT — pick
    this whenever ambiguous.
  - "multi_chat"   : The reply presents 2–{_MULTI_CHAT_CAP} independent
    alternatives / approaches / options where each is actionable on its
    own and worth a separate exploration thread. Require clear delineation
    (numbered list of distinct approaches, "Option A / Option B / Option C"
    framing, etc.). Do NOT use multi_chat for a reply that just happens to
    have multiple paragraphs.
  - "checklist"    : The reply is a sequential list of action items the
    operator must tick off in order (installation steps, migration steps,
    an audit checklist, a deployment runbook). Require numbered or bulleted
    steps with a clear "do these in order" intent.

Output ONE JSON object — no prose, no markdown fences. Schema:

For single_chat:
{{"shape":"single_chat","reason":"<one sentence>",
 "suggested":{{"title":"<≤60 chars>","description":"<≤200 chars>"}}}}

For multi_chat (2–{_MULTI_CHAT_CAP} items):
{{"shape":"multi_chat","reason":"<one sentence>",
 "suggested":[{{"title":"<≤60 chars>","description":"<≤200 chars>"}},...] }}

For checklist (≥2 items):
{{"shape":"checklist","reason":"<one sentence>",
 "suggested":[{{"label":"<≤80 chars>","notes":"<≤200 chars>"}},...] }}

Rules:
- Bias toward single_chat. Only choose multi_chat or checklist when the
  signal is strong and unambiguous.
- multi_chat cap: at most {_MULTI_CHAT_CAP} items.
- checklist items: flat only (no nesting). ≥2 items.
- title/label must be ≤60 / ≤80 chars respectively.
- description/notes ≤200 chars each.
- reason ≤120 chars.
- No null values — all fields required per shape.
"""


def _fallback(reply_text: str) -> SpawnClassifyResult:
    """Always-safe return when the classifier is disabled or fails.
    Produces a single_chat result using the first usable line of the
    reply as the title, mirroring the title heuristic in
    routes_spawn_from_reply._synthesize_title."""
    title = _heuristic_title(reply_text)
    desc = (reply_text[:200] + "…") if len(reply_text) > 200 else reply_text
    return SpawnClassifyResult(
        shape=SpawnShape.single_chat,
        reason="classifier disabled or failed",
        suggested_single=SingleChatPayload(title=title, description=desc),
    )


_MD_PREFIX_RE = re.compile(r"^#+\s+|^>\s*|^[-*]\s+|^\d+\.\s+")
_TITLE_CAP = 60


def _heuristic_title(reply_text: str) -> str:
    for raw in reply_text.splitlines():
        line = _MD_PREFIX_RE.sub("", raw.strip()).strip()
        if not line:
            continue
        return line[: _TITLE_CAP - 1] + "…" if len(line) > _TITLE_CAP else line
    return "Spawned reply"


def _build_user_prompt(reply_text: str) -> str:
    body = reply_text[:_REPLY_CHAR_CAP]
    if len(reply_text) > _REPLY_CHAR_CAP:
        body += "\n[… truncated]"
    return (
        f"Classify the following assistant reply:\n\n<assistant-reply>\n{body}\n</assistant-reply>"
    )


def _extract_json_block(text: str) -> dict[str, Any] | None:
    """Pull the first balanced ``{…}`` block out of an LLM response and
    JSON-parse it. Mirrors ``title_suggester._extract_json_block``."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = text[start : i + 1]
                try:
                    parsed = json.loads(blob)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    return None
    return None


def _clean_str(v: Any, max_len: int) -> str | None:
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s[:max_len] if s else None


def _validate_result(parsed: dict[str, Any]) -> SpawnClassifyResult | None:
    """Validate + normalise the model's JSON output into a
    ``SpawnClassifyResult``. Returns None when the shape is
    fundamentally wrong (missing keys, wrong types, constraint
    violations) so the caller can retry."""
    shape_raw = parsed.get("shape")
    if not isinstance(shape_raw, str):
        logger.warning("spawn_classifier: shape is not a string: %r", shape_raw)
        return None
    try:
        shape = SpawnShape(shape_raw)
    except ValueError:
        logger.warning("spawn_classifier: unknown shape %r", shape_raw)
        return None

    reason = _clean_str(parsed.get("reason"), 120) or "LLM classified"
    suggested_raw = parsed.get("suggested")

    if shape is SpawnShape.single_chat:
        if not isinstance(suggested_raw, dict):
            return None
        title = _clean_str(suggested_raw.get("title"), 60)
        description = _clean_str(suggested_raw.get("description"), 200)
        if not title:
            return None
        return SpawnClassifyResult(
            shape=shape,
            reason=reason,
            suggested_single=SingleChatPayload(title=title, description=description or ""),
        )

    if shape is SpawnShape.multi_chat:
        if not isinstance(suggested_raw, list) or len(suggested_raw) < 2:
            return None
        items: list[MultiChatPayload] = []
        for entry in suggested_raw[:_MULTI_CHAT_CAP]:
            if not isinstance(entry, dict):
                continue
            title = _clean_str(entry.get("title"), 60)
            description = _clean_str(entry.get("description"), 200)
            if title:
                items.append(MultiChatPayload(title=title, description=description or ""))
        if len(items) < 2:
            return None
        return SpawnClassifyResult(shape=shape, reason=reason, suggested_multi=items)

    if shape is SpawnShape.checklist:
        if not isinstance(suggested_raw, list) or len(suggested_raw) < 2:
            return None
        cl_items: list[ChecklistPayload] = []
        for entry in suggested_raw:
            if not isinstance(entry, dict):
                continue
            label = _clean_str(entry.get("label"), 80)
            notes = _clean_str(entry.get("notes"), 200)
            if label:
                cl_items.append(ChecklistPayload(label=label, notes=notes or ""))
        if len(cl_items) < 2:
            return None
        return SpawnClassifyResult(shape=shape, reason=reason, suggested_checklist=cl_items)

    return None  # unreachable given SpawnShape exhaustion


async def _run_query(
    reply_text: str,
    *,
    model: str,
    query_fn: Any | None = None,
) -> str:
    """Drive the SDK one-shot call. Isolated for the ``query_fn`` test
    seam — mirrors ``title_suggester._run_query`` exactly."""
    if query_fn is None:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
            query,
        )

        options = ClaudeAgentOptions(
            model=model,
            system_prompt=_SYSTEM_PROMPT,
            permission_mode="default",
            max_turns=1,
            setting_sources=None,
        )
        prompt = _build_user_prompt(reply_text)
        chunks: list[str] = []
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
        return "".join(chunks)

    raw = await query_fn(reply_text)
    return str(raw)


async def classify_reply(
    reply_text: str,
    *,
    model: str,
    query_fn: Any | None = None,
) -> SpawnClassifyResult:
    """Classify ``reply_text`` into a spawn shape. Always returns a
    ``SpawnClassifyResult`` — never raises. On LLM failure or parse
    error the fallback single_chat result is returned.

    ``query_fn`` is the test seam: a coroutine ``(reply_text) -> str``
    returning the raw LLM response. Pass None in production to drive
    the real SDK.

    Two attempts are made before falling back, matching the pattern in
    ``title_suggester.suggest_titles``."""
    for attempt in range(2):
        try:
            text = await _run_query(reply_text, model=model, query_fn=query_fn)
        except Exception as exc:  # noqa: BLE001
            logger.warning("classify_reply attempt %d failed: %r", attempt + 1, exc)
            continue
        parsed = _extract_json_block(text)
        if parsed is None:
            logger.warning("classify_reply attempt %d: unparseable JSON", attempt + 1)
            continue
        result = _validate_result(parsed)
        if result is None:
            logger.warning("classify_reply attempt %d: shape validation failed", attempt + 1)
            continue
        return result
    logger.warning("classify_reply: all attempts exhausted, returning fallback")
    return _fallback(reply_text)
