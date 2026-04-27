"""Prompt builders for the autonomous checklist driver.

These are pure functions: they take the driver's per-leg context as
arguments and return strings. No driver state is touched, so they
sit outside the mixin chain.
"""

from __future__ import annotations

from typing import Any

_SENTINEL_DOC = (
    "When the item is complete, emit CHECKLIST_ITEM_DONE on "
    "its own line. Bias hard toward making the call yourself: "
    "decisions, scope choices, judgment calls, 'pick one of "
    "three tracks' items are agent work. Read the context, "
    "weigh the tradeoffs, write a short rationale, pick. The "
    "user can override by unchecking; bailing on a decision "
    "you could have made wastes the run.\n"
    "If you are approaching context limit, emit\n"
    "CHECKLIST_HANDOFF\n"
    "<your handoff plug>\n"
    "CHECKLIST_HANDOFF_END\n"
    "If a precondition is broken and an agent could fix it "
    "(broken migration, missing config, failing test that "
    "blocks the real work), emit\n"
    "CHECKLIST_BLOCKED\n"
    "<what's broken and what needs fixing>\n"
    "CHECKLIST_BLOCKED_END\n"
    "A blocker spawns a fix-it session; once that completes, "
    "you are resumed in this same chat to finish the work. "
    "Do NOT use BLOCKED for items you could just do yourself "
    "— that's a different kind of bailing.\n"
    "For other followups: CHECKLIST_FOLLOWUP block=yes|no / "
    "CHECKLIST_FOLLOWUP_END. block=yes makes it a child that "
    "must complete before this item. block=no appends to the "
    "end of the checklist.\n"
    "If the item is GENUINELY outside your reach and Dave must "
    "act personally — pay a bill (his payment method), plug in "
    "hardware (physical access), supply a 2FA code (his phone), "
    "use credentials only he has, or make a decision he has "
    "explicitly reserved — emit\n"
    "CHECKLIST_ITEM_BLOCKED category=<one of: physical_action, "
    "payment, external_credential, identity_or_2fa, human_judgment>\n"
    "<short reason text>\n"
    "TRIED:\n"
    "- <attempt 1 and why it could not succeed without Dave>\n"
    "- <attempt 2 ...>\n"
    "CHECKLIST_ITEM_BLOCKED_END\n"
    "Before flagging blocked, ATTEMPT THE WORK. 'I don't know "
    "how' is not blocked — that's needs-more-thinking, keep "
    "working. 'This is risky' is not blocked — make the call "
    "yourself. 'I'm not sure' is not blocked — try first. The "
    "TRIED: log MUST list real attempts; an empty TRIED block "
    "rejects the sentinel and the run keeps you working. "
    "ITEM_BLOCKED is for what only Dave's body, accounts, "
    "payment method, or reserved-judgment can resolve. Bias "
    "hard against using it; an unjustified blocked-flag is a "
    "more expensive failure mode than a genuine attempt."
)


def build_kickoff_prompt(
    item: dict[str, Any],
    leg: int,  # noqa: ARG001 — kept in the signature for symmetry with the previous Driver._kickoff_prompt method; future leg-aware variants will use it.
    plug: str | None,
) -> str:
    """Per-leg kickoff prompt. This is what the agent sees as its
    first user turn on each leg. The sentinel grammar is described
    inline so the agent doesn't need to be separately briefed.

    The text is deliberately terse — the agent already has the
    checklist-context system-prompt layer from ``prompt.py`` when
    the leg session has ``checklist_item_id`` set, so repeating the
    parent-list context here would be noise."""
    if plug is not None:
        return (
            f"You are continuing checklist item {item['id']}: "
            f"{item['label']}\n\n"
            "Previous leg handoff plug:\n"
            "---\n"
            f"{plug}\n"
            "---\n\n"
            "Resume from the plug and complete the item.\n\n"
            f"{_SENTINEL_DOC}"
        )
    return f"Work on checklist item {item['id']}: {item['label']}\n\n{_SENTINEL_DOC}"


def build_continuation_prompt(
    item: dict[str, Any],
    resolved_blocker_labels: list[str],
) -> str:
    """Re-entry prompt for visit-existing parent resume after a
    blocker fix. Keeps the message short — the agent already has
    the full sentinel doc from the kickoff and full memory of
    what it was trying — and names the resolved blockers so the
    agent knows the fixes landed and can verify before continuing.

    Used only after ``CHECKLIST_BLOCKED`` (or
    ``CHECKLIST_FOLLOWUP block=yes``) resolves. Spawn-fresh mode
    doesn't reach this branch — fresh legs use the kickoff
    prompt with ``plug=None``."""
    if len(resolved_blocker_labels) == 1:
        blocker_summary = (
            f"the blocker you raised has been resolved:\n  - {resolved_blocker_labels[0]}"
        )
    else:
        bullets = "\n".join(f"  - {label}" for label in resolved_blocker_labels)
        blocker_summary = f"the blockers you raised have been resolved:\n{bullets}"
    return (
        f"Returning to checklist item {item['id']}: {item['label']}.\n\n"
        f"While you were paused, {blocker_summary}\n\n"
        "Verify the fix(es) landed as expected, then continue the "
        "original work. When done, emit CHECKLIST_ITEM_DONE."
    )


def build_nudge_prompt(*, under_pressure: bool) -> str:
    """Body for the silent-exit nudge turn.

    - ``under_pressure=True``: leg is past
      ``handoff_threshold_percent``. Lead with the handoff ask
      (most likely cause), but accept DONE / BLOCKED if the
      agent actually meant one of those.
    - ``under_pressure=False``: leg is below threshold. The
      agent probably finished the work and forgot the sentinel,
      OR ended its turn talking to the user when it should have
      handed off. Lead with the DONE ask, accept HANDOFF /
      BLOCKED if applicable.
    """
    if under_pressure:
        return (
            "You're approaching the context window limit on this "
            "leg. Do NOT continue working on the checklist item "
            "this turn. Instead, emit a handoff plug so a "
            "successor leg (fresh context) can finish:\n\n"
            "CHECKLIST_HANDOFF\n"
            "<what you've done, what's left, files touched, "
            "anything the successor MUST NOT redo>\n"
            "CHECKLIST_HANDOFF_END\n\n"
            "If you're actually done with the item, emit "
            "CHECKLIST_ITEM_DONE instead. Do one or the other, "
            "nothing else."
        )
    return (
        "Your last turn ended without a checklist sentinel. "
        "The autonomous driver needs one to advance. Pick the "
        "one that matches reality and emit it now:\n\n"
        "- If the item is complete, emit CHECKLIST_ITEM_DONE "
        "on its own line.\n"
        "- If you need a fresh context window to continue, "
        "emit CHECKLIST_HANDOFF / <plug> / "
        "CHECKLIST_HANDOFF_END.\n"
        "- If a precondition is broken and you can't proceed, "
        "emit CHECKLIST_BLOCKED / <what's broken> / "
        "CHECKLIST_BLOCKED_END.\n\n"
        "Do not continue the work in this reply — emit the "
        "sentinel and stop."
    )
