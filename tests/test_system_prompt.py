"""Tests for ``bearings.agent.system_prompt.build_system_prompt``.

Per Slice A2 of ``~/.claude/plans/wiring-agent-loop.md``: the
assembler is the only place
:data:`bearings.agent.bearings_mcp.CLOSE_SESSION_INSTRUCTION` is
spliced into the executor's system prompt. These tests pin the
splice order + the empty-input semantics so a future per-tag
memory layer can hook in without displacing the close-session
prompt.
"""

from __future__ import annotations

from bearings.agent.bearings_mcp import CLOSE_SESSION_INSTRUCTION
from bearings.agent.system_prompt import build_system_prompt


def test_close_session_instruction_always_present() -> None:
    """The Bearings core surface always lands, even with no inputs."""
    prompt = build_system_prompt(session_instructions=None)
    assert CLOSE_SESSION_INSTRUCTION in prompt


def test_session_instructions_precede_close_session_instruction() -> None:
    """Per-session steering reads first; the close-session prompt
    appends after it."""
    prompt = build_system_prompt(
        session_instructions="You are an executor; finish the user's task.",
    )
    instructions_idx = prompt.index("You are an executor")
    close_idx = prompt.index(CLOSE_SESSION_INSTRUCTION)
    assert instructions_idx < close_idx


def test_extras_append_after_close_session_instruction() -> None:
    """Caller extras land *after* the close-session prompt — the
    splice order matters because future per-tag memories will hook in
    here."""
    prompt = build_system_prompt(
        session_instructions=None,
        extras=("Per-tag memory body.",),
    )
    close_idx = prompt.index(CLOSE_SESSION_INSTRUCTION)
    extra_idx = prompt.index("Per-tag memory body.")
    assert close_idx < extra_idx


def test_blank_session_instructions_drops_steering_layer() -> None:
    """An empty / whitespace-only ``session_instructions`` does NOT
    render as a blank paragraph above the close-session prompt."""
    prompt = build_system_prompt(session_instructions="   \n\n  ")
    assert prompt.startswith(CLOSE_SESSION_INSTRUCTION)


def test_whitespace_only_extras_are_dropped() -> None:
    """Extras that strip to empty are filtered out (no double blank
    paragraphs in the assembled prompt)."""
    prompt = build_system_prompt(
        session_instructions=None,
        extras=("", "   ", "\n\n"),
    )
    # Only the close-session instruction remains.
    assert prompt == CLOSE_SESSION_INSTRUCTION


def test_blocks_joined_by_blank_line() -> None:
    """Each layer is separated by a blank line (\\n\\n) so SDK
    tokenization treats them as distinct paragraphs."""
    prompt = build_system_prompt(
        session_instructions="Layer 1.",
        extras=("Layer 3.",),
    )
    assert "Layer 1.\n\n" in prompt
    assert "\n\nLayer 3." in prompt


def test_session_instructions_are_stripped_before_splicing() -> None:
    """Leading/trailing whitespace on session_instructions does not
    bleed into the assembled prompt as extra blank lines."""
    prompt = build_system_prompt(
        session_instructions="\n\n  Important context.  \n\n",
    )
    assert prompt.startswith("Important context.\n\n")


def test_returns_non_empty_with_minimum_inputs() -> None:
    """Even with everything blank/None, the close-session instruction
    contributes a non-empty prompt."""
    assert build_system_prompt(session_instructions=None, extras=()) != ""
