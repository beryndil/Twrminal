"""Unit tests for `bearings.agent.checklist_sentinels`.

Sentinels are the completion-signal grammar the autonomous checklist
driver uses to interpret the final assistant message of each turn.
Every edge case here directly affects whether the driver correctly
advances to the next item, cuts over to a handoff leg, or appends
followup work — so the tests are exhaustive on the happy path AND
the malformed-input path.

Design context: see `TODO.md` § "Autonomous checklist execution" and
the module docstring on `checklist_sentinels.py`.
"""

from __future__ import annotations

from bearings.agent.checklist_sentinels import (
    Followup,
    parse,
)

# --- done -----------------------------------------------------------


def test_parse_empty_text_returns_no_signals() -> None:
    result = parse("")
    assert result.item_done is False
    assert result.handoff_plug is None
    assert result.followups == []


def test_parse_plain_prose_returns_no_signals() -> None:
    result = parse("I worked on the item. It's complete now.\nMoving on.")
    assert result.item_done is False
    assert result.handoff_plug is None
    assert result.followups == []


def test_parse_done_marker_sets_item_done() -> None:
    result = parse("Fixed the bug.\nCHECKLIST_ITEM_DONE")
    assert result.item_done is True


def test_parse_done_marker_tolerates_leading_whitespace() -> None:
    # Leading whitespace on the marker line is tolerated so the agent
    # can indent the sentinel inside a code fence without breaking the
    # parse.
    result = parse("   CHECKLIST_ITEM_DONE")
    assert result.item_done is True


def test_parse_done_marker_requires_exact_match() -> None:
    # Anything other than the exact string (after strip) is NOT a done
    # marker. Prevents false positives where the agent writes about
    # the marker without emitting it.
    result = parse("The sentinel is CHECKLIST_ITEM_DONE when complete.")
    assert result.item_done is False


def test_parse_done_marker_duplicate_is_idempotent() -> None:
    result = parse("CHECKLIST_ITEM_DONE\nOh and also:\nCHECKLIST_ITEM_DONE")
    assert result.item_done is True


# --- handoff --------------------------------------------------------


def test_parse_handoff_block_captures_plug_body() -> None:
    body = (
        "CHECKLIST_HANDOFF\n"
        "Made progress on the schema. Migration 0030 drafted.\n"
        "Next: finish the API handler.\n"
        "CHECKLIST_HANDOFF_END"
    )
    result = parse(body)
    assert result.handoff_plug == (
        "Made progress on the schema. Migration 0030 drafted.\nNext: finish the API handler."
    )
    assert result.item_done is False


def test_parse_handoff_preserves_indentation_inside_body() -> None:
    # The plug should come back verbatim (no strip of inner lines) so
    # code blocks the agent includes survive the round-trip.
    body = "CHECKLIST_HANDOFF\n```python\n    def f():\n        pass\n```\nCHECKLIST_HANDOFF_END"
    result = parse(body)
    assert result.handoff_plug is not None
    assert "    def f():" in result.handoff_plug
    assert "        pass" in result.handoff_plug


def test_parse_unterminated_handoff_is_discarded() -> None:
    # A handoff START without a matching END is ignored — better to
    # continue the item than to spawn a leg with a half-written plug.
    body = "CHECKLIST_HANDOFF\nI'm approaching context limit but I forgot the END marker.\n"
    result = parse(body)
    assert result.handoff_plug is None


def test_parse_handoff_and_item_done_resolves_to_done() -> None:
    # The agent cannot be both "done" and "needs a handoff." Done wins
    # so the driver advances rather than spawning a wasted leg.
    body = "CHECKLIST_HANDOFF\nPartial plug.\nCHECKLIST_HANDOFF_END\nCHECKLIST_ITEM_DONE"
    result = parse(body)
    assert result.item_done is True
    assert result.handoff_plug is None


# --- followups ------------------------------------------------------


def test_parse_blocking_followup_yields_blocking_flag() -> None:
    body = (
        "CHECKLIST_FOLLOWUP block=yes\n"
        "Add rate-limiting middleware before the auth path lands.\n"
        "CHECKLIST_FOLLOWUP_END"
    )
    result = parse(body)
    assert result.followups == [
        Followup(
            label="Add rate-limiting middleware before the auth path lands.",
            blocking=True,
        )
    ]


def test_parse_non_blocking_followup_yields_non_blocking_flag() -> None:
    body = (
        "CHECKLIST_FOLLOWUP block=no\n"
        "Doc improvement: update README after feature lands.\n"
        "CHECKLIST_FOLLOWUP_END"
    )
    result = parse(body)
    assert len(result.followups) == 1
    assert result.followups[0].blocking is False


def test_parse_multiple_followups_preserve_order() -> None:
    body = (
        "CHECKLIST_FOLLOWUP block=yes\n"
        "first — blocking.\n"
        "CHECKLIST_FOLLOWUP_END\n"
        "some prose\n"
        "CHECKLIST_FOLLOWUP block=no\n"
        "second — non-blocking.\n"
        "CHECKLIST_FOLLOWUP_END"
    )
    result = parse(body)
    assert [f.label for f in result.followups] == [
        "first — blocking.",
        "second — non-blocking.",
    ]
    assert [f.blocking for f in result.followups] == [True, False]


def test_parse_followup_without_block_attr_is_skipped() -> None:
    # `block=` is required. Ambiguous blocking semantics must not be
    # silently defaulted — better to drop the followup than to append
    # something to the wrong parent.
    body = "CHECKLIST_FOLLOWUP\nmissing block=, should be dropped.\nCHECKLIST_FOLLOWUP_END"
    result = parse(body)
    assert result.followups == []


def test_parse_followup_with_invalid_block_value_is_skipped() -> None:
    body = "CHECKLIST_FOLLOWUP block=maybe\ninvalid block value.\nCHECKLIST_FOLLOWUP_END"
    result = parse(body)
    assert result.followups == []


def test_parse_followup_with_empty_label_is_skipped() -> None:
    # A followup block containing only whitespace is meaningless —
    # drop it rather than create a blank checklist item.
    body = "CHECKLIST_FOLLOWUP block=yes\n   \nCHECKLIST_FOLLOWUP_END"
    result = parse(body)
    assert result.followups == []


def test_parse_unterminated_followup_is_discarded() -> None:
    body = "CHECKLIST_FOLLOWUP block=yes\nforgot the end marker\n"
    result = parse(body)
    assert result.followups == []


def test_parse_followup_tolerates_extra_attributes() -> None:
    # Future-proofing: `priority=high` or similar shouldn't break the
    # current parse of `block=`. Only `block=` is recognized today.
    body = "CHECKLIST_FOLLOWUP block=yes priority=high\nforward-compat test\nCHECKLIST_FOLLOWUP_END"
    result = parse(body)
    assert len(result.followups) == 1
    assert result.followups[0].blocking is True


# --- combinations ---------------------------------------------------


def test_parse_done_plus_non_blocking_followup_coexist() -> None:
    # "I finished item N and also noted a doc task for later" — both
    # legitimate, both survive parsing.
    body = (
        "Fixed the thing.\n"
        "CHECKLIST_FOLLOWUP block=no\n"
        "later: update the CHANGELOG.\n"
        "CHECKLIST_FOLLOWUP_END\n"
        "CHECKLIST_ITEM_DONE"
    )
    result = parse(body)
    assert result.item_done is True
    assert len(result.followups) == 1
    assert result.followups[0].blocking is False


def test_parse_handoff_plus_blocking_followup_coexist() -> None:
    # "I need to hand off, and btw this child must run before the
    # parent can complete" — both survive.
    body = (
        "CHECKLIST_FOLLOWUP block=yes\n"
        "prereq: install the dep first\n"
        "CHECKLIST_FOLLOWUP_END\n"
        "CHECKLIST_HANDOFF\n"
        "state snapshot goes here\n"
        "CHECKLIST_HANDOFF_END"
    )
    result = parse(body)
    assert result.handoff_plug == "state snapshot goes here"
    assert len(result.followups) == 1
    assert result.followups[0].blocking is True
    assert result.item_done is False


def test_parse_crlf_line_endings() -> None:
    # Agents rarely emit CRLF, but `splitlines()` normalizes — make
    # sure the marker match isn't defeated by a trailing \r.
    body = "CHECKLIST_ITEM_DONE\r\n"
    result = parse(body)
    assert result.item_done is True


# --- CHECKLIST_BLOCKED (sugar over block=yes followup) -------------


def test_parse_checklist_blocked_creates_blocking_followup() -> None:
    """CHECKLIST_BLOCKED is sugar for CHECKLIST_FOLLOWUP block=yes —
    same downstream effect (driver creates a blocking child item,
    recurses), but the keyword carries the intent unambiguously."""
    body = (
        "I cannot proceed.\n"
        "CHECKLIST_BLOCKED\n"
        "Permission profile is misconfigured\n"
        "CHECKLIST_BLOCKED_END"
    )
    result = parse(body)
    assert len(result.followups) == 1
    assert result.followups[0] == Followup(
        label="Permission profile is misconfigured", blocking=True
    )
    assert result.item_done is False
    assert result.handoff_plug is None


def test_parse_checklist_blocked_multiline_label() -> None:
    """Multi-line blocker descriptions join with newlines, same as
    multi-line followup labels. The label IS the agent's description
    of what's broken — keep it intact."""
    body = (
        "CHECKLIST_BLOCKED\n"
        "Database migration 0027 hasn't run.\n"
        "Need to ship that before this work can continue.\n"
        "CHECKLIST_BLOCKED_END"
    )
    result = parse(body)
    assert len(result.followups) == 1
    label = result.followups[0].label
    assert "migration 0027" in label
    assert "before this work can continue" in label


def test_parse_unterminated_blocked_block_is_discarded() -> None:
    """Same rule as unterminated handoff/followup: if the agent didn't
    close the block, treat it as accidental and don't act on it."""
    body = "CHECKLIST_BLOCKED\nstuff that needs fixing"
    result = parse(body)
    assert result.followups == []


def test_parse_blocked_and_done_coexist_blocking_first() -> None:
    """Agent emits CHECKLIST_BLOCKED + CHECKLIST_ITEM_DONE in the same
    turn. The followup survives (driver will drive it before honoring
    the done signal — same blocking-first rule as block=yes)."""
    body = "CHECKLIST_BLOCKED\nNeed this fixed first\nCHECKLIST_BLOCKED_END\nCHECKLIST_ITEM_DONE"
    result = parse(body)
    assert result.item_done is True
    assert len(result.followups) == 1
    assert result.followups[0].blocking is True
