"""Sentinel grammar for autonomous checklist execution.

The autonomous driver spawns a fresh paired chat session per checklist
item and needs three signals back from the agent working that item:

1. **Done.** The item is complete — driver should mark it checked and
   advance to the next item.
2. **Handoff.** The agent is approaching the context window limit and
   is emitting a plug for a successor session ("leg") to continue with
   a fresh context window. Driver kills the current runner and spawns
   a new paired chat for the SAME item, injecting the plug.
3. **Followup.** The agent has discovered additional work that belongs
   on the checklist. A blocking followup becomes a child item whose
   completion gates the parent (driver recurses before completing the
   parent); a non-blocking followup gets appended at the end of the
   checklist and is picked up by the outer loop in due course.

Rather than wire MCP tools for this (which would add a server process
and per-tool approval plumbing), we use structured sentinels inside the
agent's assistant text. The driver scans the final assistant message
after each turn and acts on whatever it finds.

### Grammar

All sentinels appear **only** in the final assistant message of a
turn. They stand on their own lines. Leading/trailing whitespace on
the marker line is tolerated; everything else is strict.

Done (single line):
```
CHECKLIST_ITEM_DONE
```

Handoff (block — everything between markers is the plug text):
```
CHECKLIST_HANDOFF
<plug body, any number of lines>
CHECKLIST_HANDOFF_END
```

Followup (block — everything between markers is the item label):
```
CHECKLIST_FOLLOWUP block=yes
<label body, any number of lines>
CHECKLIST_FOLLOWUP_END
```

Item-blocked (block — flag this item as outside the agent's reach):
```
CHECKLIST_ITEM_BLOCKED category=physical_action
<short reason text>
TRIED:
- <attempt 1 and why it could not succeed without Dave>
- <attempt 2 ...>
CHECKLIST_ITEM_BLOCKED_END
```

`category=` is REQUIRED and must be one of `physical_action`,
`payment`, `external_credential`, `identity_or_2fa`, `human_judgment`.
The `TRIED:` block is REQUIRED and must list at least one attempt.
Anything else — missing category, unknown category, missing
TRIED:, empty TRIED: — rejects the sentinel and the run continues
asking the agent to attempt the work. This is the mechanical
guardrail against premature blocked-flagging.

`block=yes` means the parent item cannot complete until this child
item completes (driver recurses before finishing the parent).
`block=no` means append-to-end (parent can complete now; driver picks
up the followup later in the outer loop). The `block=` attribute is
required — a followup without it is treated as malformed and skipped
(better to drop a followup than silently get the blocking semantics
wrong).

### Conflict resolution

- Multiple `CHECKLIST_ITEM_DONE` lines → treat as one (done is
  idempotent).
- Multiple followup blocks → collected in order.
- An unterminated handoff or followup block → ignored. The driver
  treats a half-specified sentinel as "the agent didn't mean to emit
  that" and does not act. Better to continue the item than to commit
  to a handoff the agent didn't finish announcing.
- `CHECKLIST_ITEM_DONE` + `CHECKLIST_HANDOFF` both present → item_done
  wins. Handoff is for "I need more context window," which is
  contradicted by "I am done."
- `CHECKLIST_ITEM_DONE` + `CHECKLIST_ITEM_BLOCKED` both present →
  item_done wins, same rationale. Done is the most committal claim;
  if the agent is sure the item is finished, treat blocked as a
  retracted draft.
- Nested or overlapping blocks → we do not attempt to parse nested
  sentinels. The outer block wins and the inner tokens become part of
  the outer block's body. Agents should not nest these; if they do,
  the driver sees exactly what the final assistant message contained.

### Why strict lines, not XML / JSON

Agents reliably produce plain-line formats; XML and JSON both have
escape-hazard modes where a quotation mark or angle bracket inside
the plug body breaks the parse. A line-prefix grammar has no escape
hazard — the agent's plug can contain any characters except a line
that is exactly the terminator marker. That constraint is easy to
describe to the agent in a system prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- public sentinel strings ----------------------------------------
# Exported so the driver / prompt-assembly code that TELLS the agent
# to emit these can reference one source of truth. Any change here
# MUST update the agent-instruction string in the driver's kickoff
# prompt.

DONE_MARKER = "CHECKLIST_ITEM_DONE"
HANDOFF_START = "CHECKLIST_HANDOFF"
HANDOFF_END = "CHECKLIST_HANDOFF_END"
FOLLOWUP_START_PREFIX = "CHECKLIST_FOLLOWUP"
FOLLOWUP_END = "CHECKLIST_FOLLOWUP_END"
# Sugar over CHECKLIST_FOLLOWUP block=yes for the "I cannot proceed
# until X is fixed" case. Functionally identical — parses to a
# blocking Followup. Distinct keyword so the agent's intent is
# unambiguous in the message and the kickoff prompt can call it out
# as the right move under "stuck on a precondition." Added 2026-04-25
# for the fix-and-return slice.
BLOCKED_START = "CHECKLIST_BLOCKED"
BLOCKED_END = "CHECKLIST_BLOCKED_END"
# CHECKLIST_ITEM_BLOCKED — distinct from CHECKLIST_BLOCKED above.
# CHECKLIST_BLOCKED is sugar for "create a blocking child followup
# I need to do first." CHECKLIST_ITEM_BLOCKED means "this item is
# genuinely outside my reach and Dave must act" (pay a bill, plug in
# hardware, supply a 2FA code). Driver stamps blocked_at on the item,
# leaves the paired session open, and advances regardless of
# failure_policy. See ~/.claude/plans/crimson-flagging-checklist.md.
ITEM_BLOCKED_START_PREFIX = "CHECKLIST_ITEM_BLOCKED"
ITEM_BLOCKED_END = "CHECKLIST_ITEM_BLOCKED_END"
ITEM_BLOCKED_TRIED_MARKER = "TRIED:"
ITEM_BLOCKED_CATEGORIES = frozenset(
    {
        "physical_action",
        "payment",
        "external_credential",
        "identity_or_2fa",
        "human_judgment",
    }
)


@dataclass(frozen=True)
class ItemBlocked:
    """Structured payload from a `CHECKLIST_ITEM_BLOCKED` sentinel.

    `category` is one of the five whitelisted enum values
    (`ITEM_BLOCKED_CATEGORIES`). `reason` is the agent's short prose
    explanation. `tried` is the list of attempts the agent made
    before flagging blocked — REQUIRED to be non-empty. The driver
    treats an empty `tried` as a malformed sentinel and the run
    continues attempting the work.

    Mechanical guardrail against premature blocked-flagging: the
    parser rejects the sentinel when category isn't in the
    whitelist, when the `TRIED:` marker is missing, or when no
    bullet lines follow it. Callers see `result.item_blocked is None`
    in those cases and proceed as if the sentinel wasn't there."""

    category: str
    reason: str
    tried: tuple[str, ...]


@dataclass(frozen=True)
class Followup:
    """A followup item the agent wants appended to the checklist.

    `blocking=True` means the parent item cannot complete until this
    child completes — the driver recurses into the child (using
    `parent_item_id = <current item>`) before returning to the parent.
    `blocking=False` means append at the end of the checklist and
    process in the outer loop's normal order."""

    label: str
    blocking: bool


@dataclass
class ParsedSentinels:
    """Result of scanning one assistant-message body for sentinels.

    `item_done` and `handoff_plug` are mutually exclusive in practice
    — the parser resolves the conflict in favor of `item_done` and
    clears `handoff_plug` in that case (so the driver only needs to
    check `item_done` first). `followups` can coexist with either
    outcome — an item may legitimately be "done" while also noting a
    non-blocking followup, or may handoff while having already added
    a blocking child."""

    item_done: bool = False
    handoff_plug: str | None = None
    followups: list[Followup] = field(default_factory=list)
    # Set when a well-formed `CHECKLIST_ITEM_BLOCKED` block is parsed.
    # Mutually exclusive with `item_done` at the parser level: a
    # message claiming both is resolved in favor of `item_done`
    # (matching the existing `done` > `handoff` rule). Coexists
    # freely with handoff/followups — though a leg flagging blocked
    # is normally the leg's terminal action, the parser doesn't
    # impose that.
    item_blocked: ItemBlocked | None = None


def parse(text: str) -> ParsedSentinels:
    """Scan `text` for checklist sentinels and return what was found.

    The parser walks line-by-line. State machine has three modes:

    - **normal**: looking for any sentinel marker line.
    - **handoff**: accumulating plug lines until `HANDOFF_END`.
    - **followup**: accumulating label lines until `FOLLOWUP_END`.

    An unterminated block (mode != normal at end of input) is
    discarded — we do not emit a partial handoff or followup. See the
    module docstring for the rationale.
    """
    result = ParsedSentinels()

    # Agents very rarely emit CRLF, but normalize defensively — a
    # CR at end-of-line would break the exact-match equality tests
    # below. Splitlines() handles CRLF / LF / standalone CR uniformly.
    lines = text.splitlines()

    mode: str = "normal"
    buffer: list[str] = []
    pending_blocking: bool = False
    pending_item_blocked_category: str | None = None

    for line in lines:
        stripped = line.strip()
        if mode == "normal":
            if stripped == DONE_MARKER:
                result.item_done = True
                continue
            if stripped == HANDOFF_START:
                mode = "handoff"
                buffer = []
                continue
            if stripped.startswith(ITEM_BLOCKED_START_PREFIX) and (
                stripped == ITEM_BLOCKED_START_PREFIX
                or stripped[len(ITEM_BLOCKED_START_PREFIX)] in (" ", "\t")
            ):
                # The start line looks like
                # `CHECKLIST_ITEM_BLOCKED category=physical_action`.
                # The `category=` attribute is required and must be
                # one of the five whitelisted enum values. Anything
                # else is malformed and the block is skipped — the
                # driver then keeps the agent working rather than
                # accept a blocked-flag we can't classify.
                #
                # Guard the prefix check so `CHECKLIST_ITEM_BLOCKED_END`
                # (a future stray line in normal mode) doesn't match
                # the start prefix and open a new block. The character
                # immediately after the prefix must be whitespace or
                # end-of-line; `_END` would put `_` there and we'd
                # correctly fall through.
                category = _parse_item_blocked_start(stripped)
                if category is None:
                    continue
                mode = "item_blocked"
                buffer = []
                pending_item_blocked_category = category
                continue
            if stripped == BLOCKED_START:
                # CHECKLIST_BLOCKED is sugar for CHECKLIST_FOLLOWUP
                # block=yes — same downstream effect (driver creates
                # a blocking child item, recurses), with a name the
                # agent reaches for when stuck. The body lines until
                # CHECKLIST_BLOCKED_END become the child label, the
                # same way the followup body becomes the followup
                # label.
                mode = "blocked"
                buffer = []
                continue
            if stripped.startswith(FOLLOWUP_START_PREFIX):
                # The start line looks like
                # `CHECKLIST_FOLLOWUP block=yes` — the attribute is
                # required. Anything we can't parse as block=yes|no
                # is treated as malformed and the block is skipped.
                blocking = _parse_followup_start(stripped)
                if blocking is None:
                    # Malformed start. Stay in normal mode so a
                    # later well-formed block in the same message
                    # is still picked up.
                    continue
                mode = "followup"
                buffer = []
                pending_blocking = blocking
                continue
            # Any other line in normal mode is agent prose and is
            # ignored by the parser.
            continue
        if mode == "handoff":
            if stripped == HANDOFF_END:
                result.handoff_plug = "\n".join(buffer)
                mode = "normal"
                buffer = []
                continue
            # Preserve the line verbatim (not stripped) so the plug
            # keeps the agent's indentation. The markers are the
            # only lines the parser is strict about.
            buffer.append(line)
            continue
        if mode == "followup":
            if stripped == FOLLOWUP_END:
                label = "\n".join(buffer).strip()
                if label:
                    result.followups.append(Followup(label=label, blocking=pending_blocking))
                mode = "normal"
                buffer = []
                continue
            buffer.append(line)
            continue
        if mode == "blocked":
            if stripped == BLOCKED_END:
                label = "\n".join(buffer).strip()
                if label:
                    # Always blocking — that's the whole point of the
                    # CHECKLIST_BLOCKED sentinel. No `block=` attribute
                    # to parse since the keyword carries the semantics.
                    result.followups.append(Followup(label=label, blocking=True))
                mode = "normal"
                buffer = []
                continue
            buffer.append(line)
            continue
        if mode == "item_blocked":
            if stripped == ITEM_BLOCKED_END:
                parsed = _finalize_item_blocked(buffer, pending_item_blocked_category)
                if parsed is not None:
                    result.item_blocked = parsed
                mode = "normal"
                buffer = []
                pending_item_blocked_category = None
                continue
            buffer.append(line)
            continue

    # Unterminated block → discard. Resolve item_done vs handoff_plug
    # and item_done vs item_blocked in favor of done (matches the
    # existing `done` > `handoff` rule — done wins because it's the
    # most committal claim).
    if result.item_done and result.handoff_plug is not None:
        result.handoff_plug = None
    if result.item_done and result.item_blocked is not None:
        result.item_blocked = None
    return result


def _parse_item_blocked_start(line: str) -> str | None:
    """Parse `CHECKLIST_ITEM_BLOCKED category=<enum>` → category string.

    Returns None when `category=` is missing or the value isn't in
    the whitelist. The driver and parser treat None as "skip this
    block" — a malformed flag falls through to the agent continuing
    to work rather than accepting an unclassified blocked claim.

    Trailing attributes are tolerated for forward compatibility,
    matching the followup-start permissiveness."""
    rest = line[len(ITEM_BLOCKED_START_PREFIX) :].strip()
    if not rest:
        return None
    for token in rest.split():
        if token.startswith("category="):
            value = token[len("category=") :].strip().lower()
            if value in ITEM_BLOCKED_CATEGORIES:
                return value
            return None
    return None


def _finalize_item_blocked(buffer: list[str], category: str | None) -> ItemBlocked | None:
    """Turn the accumulated body lines into an `ItemBlocked` payload,
    or return None when the body is malformed.

    Body shape:
        <one or more reason lines>
        TRIED:
        - <attempt 1>
        - <attempt 2>
        ...

    The reason is everything before the `TRIED:` marker (joined with
    newlines, trimmed). The `tried` list is the lines after the
    marker; bullet markers (`- `, `* `, `• `) are stripped, blank
    lines are dropped. An empty reason or empty `tried` list rejects
    the sentinel — the guardrail against premature blocked-flagging
    requires real evidence the agent attempted the work."""
    if category is None:
        return None
    # Find the TRIED: marker. Tolerated leading whitespace because the
    # agent might indent it for readability; case-sensitive on the
    # marker itself to keep parsing tight.
    tried_index: int | None = None
    for i, raw in enumerate(buffer):
        if raw.strip() == ITEM_BLOCKED_TRIED_MARKER:
            tried_index = i
            break
    if tried_index is None:
        return None
    reason_lines = buffer[:tried_index]
    tried_lines = buffer[tried_index + 1 :]
    reason = "\n".join(reason_lines).strip()
    if not reason:
        return None
    tried: list[str] = []
    for raw in tried_lines:
        s = raw.strip()
        if not s:
            continue
        # Strip a leading bullet marker so callers see clean attempt
        # text. Multiple common bullets supported because agents
        # aren't picky about which one they use.
        for prefix in ("- ", "* ", "• ", "-\t", "*\t"):
            if s.startswith(prefix):
                s = s[len(prefix) :].strip()
                break
        if s:
            tried.append(s)
    if not tried:
        return None
    return ItemBlocked(category=category, reason=reason, tried=tuple(tried))


def _parse_followup_start(line: str) -> bool | None:
    """Parse `CHECKLIST_FOLLOWUP block=yes` → True, `block=no` → False.
    Returns None on malformed input so the caller can skip the block.

    Trailing attributes after `block=` are ignored — the only one we
    recognize today is `block`. Extra tokens like `priority=high`
    would be tolerated for future expansion without breaking the
    current parse."""
    # Trim the prefix and split the remainder on whitespace.
    rest = line[len(FOLLOWUP_START_PREFIX) :].strip()
    if not rest:
        return None
    tokens = rest.split()
    for token in tokens:
        if token.startswith("block="):
            value = token[len("block=") :].strip().lower()
            if value == "yes":
                return True
            if value == "no":
                return False
            return None
    return None
