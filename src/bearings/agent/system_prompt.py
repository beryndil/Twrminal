"""Pure system-prompt assembler for the executor session.

Per Slice A2 of ``~/.claude/plans/wiring-agent-loop.md``: the worker
loop (sdk_loop.py) calls :func:`build_system_prompt` to produce the
text it splats onto :attr:`ClaudeAgentOptions.system_prompt`. The
assembler is pure — no I/O, no clock reads — so unit tests can pin
the splice order without booting the SDK.

Layered composition (most-general first; more-specific layers append
after):

1. **Per-session steering** — ``session_instructions`` from the
   ``sessions`` row. Empty / ``None`` means the operator left the
   per-session steering blank.
2. **Bearings core surface** — :data:`bearings.agent.bearings_mcp.CLOSE_SESSION_INSTRUCTION`.
   Always appended so the agent always knows about the
   ``mcp__bearings__close_session`` tool. Order: after session
   steering so the operator's instructions are read first; before
   any caller extras so a future per-tag layer can augment without
   displacing the close-session prompt.
3. **Caller extras** — additional blocks the worker provides at
   composition time (e.g. a future per-tag memory or per-template
   prepend). Empty by default.

Blocks are joined by a blank line so the SDK's downstream
tokenization treats each as a separate paragraph in the system
context.
"""

from __future__ import annotations

from bearings.agent.bearings_mcp import CLOSE_SESSION_INSTRUCTION


def build_system_prompt(
    *,
    session_instructions: str | None,
    extras: tuple[str, ...] = (),
) -> str:
    """Assemble the executor's system-prompt text.

    Args:
        session_instructions: The session row's
            ``session_instructions`` column. When ``None`` or
            empty-after-strip, the per-session steering layer is
            omitted entirely (rather than rendering a blank
            paragraph).
        extras: Additional system-prompt blocks to append after the
            default surface. Each entry is treated as a single
            block; whitespace-only entries are dropped.

    Returns:
        The composed system-prompt string. Always non-empty (the
        Bearings core surface contributes at minimum).
    """
    parts: list[str] = []
    if session_instructions is not None:
        stripped = session_instructions.strip()
        if stripped:
            parts.append(stripped)
    parts.append(CLOSE_SESSION_INSTRUCTION)
    for extra in extras:
        block = extra.strip()
        if block:
            parts.append(block)
    return "\n\n".join(parts)


__all__ = ["build_system_prompt"]
