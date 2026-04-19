"""Layered system-prompt assembler.

Order: base → tag memories (one per attached tag with a
`tag_memories` row, in the canonical pinned-first / sort_order / id
order) → session instructions (if non-null).

Pure SQL reads — no writes, safe to call per-turn. `AgentSession`
calls this before every SDK turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import aiosqlite

from twrminal.agent.base_prompt import BASE_PROMPT

LayerKind = Literal["base", "tag_memory", "session"]


@dataclass(frozen=True)
class Layer:
    name: str
    kind: LayerKind
    content: str


@dataclass(frozen=True)
class AssembledPrompt:
    layers: list[Layer]
    text: str


def estimate_tokens(text: str) -> int:
    """Rough token count for UI display. Uses ~4-chars-per-token as a
    proxy — the real figure comes from the tokenizer on the Claude
    side, but this is good enough for the Context-tab badge and
    avoids pulling a heavyweight tokenizer dep.

    Empty strings count as zero; anything else is at least 1 so the
    UI never shows an all-zero row for non-empty content.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def _finalize(layers: list[Layer]) -> AssembledPrompt:
    parts = [f"<!-- layer: {layer.kind}[{layer.name}] -->\n{layer.content}" for layer in layers]
    return AssembledPrompt(layers=layers, text="\n\n".join(parts))


async def assemble_prompt(conn: aiosqlite.Connection, session_id: str) -> AssembledPrompt:
    layers: list[Layer] = [Layer(name="base", kind="base", content=BASE_PROMPT)]

    async with conn.execute(
        "SELECT session_instructions FROM sessions WHERE id = ?",
        (session_id,),
    ) as cursor:
        session_row = await cursor.fetchone()
    if session_row is None:
        return _finalize(layers)

    session_instructions = session_row["session_instructions"]

    async with conn.execute(
        "SELECT t.name AS name, tm.content AS content "
        "FROM session_tags st "
        "JOIN tags t ON t.id = st.tag_id "
        "JOIN tag_memories tm ON tm.tag_id = t.id "
        "WHERE st.session_id = ? "
        "ORDER BY t.pinned DESC, t.sort_order ASC, t.id ASC",
        (session_id,),
    ) as cursor:
        async for row in cursor:
            layers.append(Layer(name=row["name"], kind="tag_memory", content=row["content"]))

    if session_instructions:
        layers.append(Layer(name="session", kind="session", content=session_instructions))

    return _finalize(layers)
