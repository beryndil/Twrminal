"""Checklist-sentinel parser — pure functions over assistant-message bodies.

Per ``docs/architecture-v1.md`` §1.1.4 ``agent/sentinel.py`` is the
checklist-sentinel parser (renamed from v0.17.x's
``checklist_sentinels.py``); per ``docs/behavior/checklists.md``
§"Sentinels (auto-pause / failure / completion)" the autonomous driver
consumes structured sentinels emitted by the working agent inside its
assistant text. The behavior doc names six observable sentinel kinds:

* ``item_done`` — driver checks the item, advances, ticks
  ``items_completed``.
* ``handoff`` — driver kills the runner + spawns a successor leg with
  the agent's plug as the first prompt; ticks ``legs_spawned``.
* ``followup_blocking`` — append a child item under the current item;
  driver recurses before completing the parent.
* ``followup_nonblocking`` — append at end of checklist; current item
  completes; new item picked up later.
* ``item_blocked`` — leave unchecked, paired chat stays open, ticks
  ``items_blocked``, run advances regardless of failure-policy.
* ``item_failed`` — sentinel-flagged failure; driver halts (halt
  policy) or advances (skip policy) and ticks ``items_failed``.

The behavior doc mandates: "Malformed or incomplete sentinels are
ignored. The driver does not act on a half-emitted block."

Wire format
-----------

Decided-and-documented (the behavior doc is silent on the exact
syntax; only that the markers are "structured sentinels … inside
assistant text"). The format is XML-ish self-closing or open/close
tags carrying the kind on a ``kind=`` attribute:

* ``<bearings:sentinel kind="item_done" />``
* ``<bearings:sentinel kind="item_failed">…<reason>…</reason>…</bearings:sentinel>``
* ``<bearings:sentinel kind="handoff"><plug>…</plug></bearings:sentinel>``
* ``<bearings:sentinel kind="followup_blocking"><label>…</label></bearings:sentinel>``
* ``<bearings:sentinel kind="followup_nonblocking"><label>…</label></bearings:sentinel>``
* ``<bearings:sentinel kind="item_blocked"><category>…</category>``
  ``<text>…</text></bearings:sentinel>``

Rationale for the XML-ish form:

1. The closing ``</bearings:sentinel>`` is unambiguous in a markdown
   stream — code fences and inline backticks don't contain it
   accidentally. Brace-delimited JSON (``{"sentinel": …}``) collides
   with everyday code samples.
2. The kind attribute is lexically simple to validate against
   :data:`bearings.config.constants.KNOWN_SENTINEL_KINDS`.
3. A half-emitted block (no closing tag, no closing ``/>``) is
   visibly malformed under regex; the parser's "incomplete sentinels
   are ignored" rule is enforced by demanding a complete tag.

Public surface:

* :class:`SentinelFinding` — frozen dataclass mirroring one parsed
  sentinel with kind + payload fields.
* :func:`parse` — pure function: given an assistant-message body,
  return an ordered list of findings.
* :func:`first_terminal` — convenience: pick the first
  terminal-by-semantic finding (``item_done`` /
  ``item_failed`` / ``item_blocked`` / ``handoff``) — the followup
  kinds are non-terminal under the driver's outer loop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bearings.config.constants import (
    ITEM_OUTCOME_BLOCKED,
    KNOWN_ITEM_OUTCOMES,
    KNOWN_SENTINEL_KINDS,
    SENTINEL_KIND_FOLLOWUP_BLOCKING,
    SENTINEL_KIND_FOLLOWUP_NONBLOCKING,
    SENTINEL_KIND_HANDOFF,
    SENTINEL_KIND_ITEM_BLOCKED,
    SENTINEL_KIND_ITEM_DONE,
    SENTINEL_KIND_ITEM_FAILED,
)


@dataclass(frozen=True)
class SentinelFinding:
    """One parsed sentinel.

    ``kind`` is one of :data:`KNOWN_SENTINEL_KINDS`.

    Per-kind payload semantics:

    * ``item_done`` / ``handoff`` (open form) — ``plug`` carries the
      handoff plug body; empty for ``item_done``.
    * ``followup_blocking`` / ``followup_nonblocking`` — ``label``
      carries the new child / sibling label; required.
    * ``item_blocked`` — ``category`` and ``reason`` carry the
      observable amber-pip reason. ``category`` defaults to ``blocked``
      from :data:`KNOWN_ITEM_OUTCOMES`.
    * ``item_failed`` — ``reason`` carries the failure diagnosis the
      driver records.
    """

    kind: str
    plug: str | None = None
    label: str | None = None
    category: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in KNOWN_SENTINEL_KINDS:
            raise ValueError(
                f"SentinelFinding.kind {self.kind!r} not in {sorted(KNOWN_SENTINEL_KINDS)}"
            )
        if self.category is not None and self.category not in KNOWN_ITEM_OUTCOMES:
            raise ValueError(
                f"SentinelFinding.category {self.category!r} not in {sorted(KNOWN_ITEM_OUTCOMES)}"
            )


# Self-closing form: <bearings:sentinel kind="item_done" />
_SELF_CLOSING_RE = re.compile(
    r"""<bearings:sentinel\s+kind\s*=\s*"(?P<kind>[a-z_]+)"\s*/>""",
    re.IGNORECASE,
)

# Open/close form: <bearings:sentinel kind="…">…</bearings:sentinel>
# DOTALL so the body can span multiple lines (handoff plugs commonly
# do). Non-greedy on the body so adjacent sentinels don't merge.
_OPEN_CLOSE_RE = re.compile(
    r"""<bearings:sentinel\s+kind\s*=\s*"(?P<kind>[a-z_]+)"\s*>(?P<body>.*?)</bearings:sentinel>""",
    re.IGNORECASE | re.DOTALL,
)

# Inner-payload tags inside the body of an open/close sentinel. Each
# captures the raw inner text for one named field. Multiple fields per
# sentinel are matched independently — the parser combines them.
_PLUG_RE = re.compile(r"<plug>(?P<v>.*?)</plug>", re.IGNORECASE | re.DOTALL)
_LABEL_RE = re.compile(r"<label>(?P<v>.*?)</label>", re.IGNORECASE | re.DOTALL)
_CATEGORY_RE = re.compile(r"<category>(?P<v>.*?)</category>", re.IGNORECASE | re.DOTALL)
_REASON_RE = re.compile(r"<reason>(?P<v>.*?)</reason>", re.IGNORECASE | re.DOTALL)
_TEXT_RE = re.compile(r"<text>(?P<v>.*?)</text>", re.IGNORECASE | re.DOTALL)

# Terminal kinds — the outer driver loop treats these as "this leg's
# turn produced a definitive outcome for the current item". Followups
# are non-terminal: they append work and the leg continues.
_TERMINAL_KINDS: frozenset[str] = frozenset(
    {
        SENTINEL_KIND_ITEM_DONE,
        SENTINEL_KIND_HANDOFF,
        SENTINEL_KIND_ITEM_BLOCKED,
        SENTINEL_KIND_ITEM_FAILED,
    }
)


def parse(body: str) -> list[SentinelFinding]:
    """Return every sentinel parsed from ``body``, in document order.

    Both self-closing and open/close forms are recognised. Per
    behavior/checklists.md "Malformed or incomplete sentinels are
    ignored" — an unknown ``kind`` attribute, a missing closing tag on
    a multi-line form, or a body whose required inner field is missing
    (e.g. a ``followup_blocking`` with no ``<label>``) is silently
    dropped. The empty-input case returns an empty list.

    The parser is robust to multiple sentinels in one message and to
    incidental angle-bracket text around them (the regexes anchor on
    the literal ``<bearings:sentinel`` prefix).
    """
    if not body:
        return []
    findings: list[tuple[int, SentinelFinding]] = []

    for match in _SELF_CLOSING_RE.finditer(body):
        kind = match.group("kind").lower()
        if kind not in KNOWN_SENTINEL_KINDS:
            continue
        # Self-closing form is only valid for kinds that have no
        # required payload — currently item_done.
        if kind != SENTINEL_KIND_ITEM_DONE:
            continue
        findings.append((match.start(), SentinelFinding(kind=kind)))

    for match in _OPEN_CLOSE_RE.finditer(body):
        kind = match.group("kind").lower()
        if kind not in KNOWN_SENTINEL_KINDS:
            continue
        body_text = match.group("body")
        finding = _build_finding(kind=kind, body=body_text)
        if finding is not None:
            findings.append((match.start(), finding))

    findings.sort(key=lambda pair: pair[0])
    return [finding for _, finding in findings]


def first_terminal(findings: list[SentinelFinding]) -> SentinelFinding | None:
    """First terminal-kind finding, or ``None`` if there isn't one.

    Used by the driver to decide "did this turn produce a definitive
    outcome for the current item?" — followup kinds (which append work
    but don't close the item) return ``None`` here.
    """
    for finding in findings:
        if finding.kind in _TERMINAL_KINDS:
            return finding
    return None


def _build_followup_finding(kind: str, body: str) -> SentinelFinding | None:
    """Build a followup-kind finding; ``None`` when the label tag is missing."""
    label = _extract(body, _LABEL_RE)
    return None if not label else SentinelFinding(kind=kind, label=label)


def _build_blocked_finding(body: str) -> SentinelFinding | None:
    """Build an item-blocked finding; ``None`` when the category is unknown."""
    category = _extract(body, _CATEGORY_RE) or ITEM_OUTCOME_BLOCKED
    if category not in KNOWN_ITEM_OUTCOMES:
        return None
    text = _extract(body, _TEXT_RE) or _extract(body, _REASON_RE)
    return SentinelFinding(kind=SENTINEL_KIND_ITEM_BLOCKED, category=category, reason=text)


def _build_finding(*, kind: str, body: str) -> SentinelFinding | None:
    """Translate one open/close-form match to a finding; ``None`` if malformed.

    Per-kind required-field validation lives here so the parser drops
    half-emitted sentinels per the behavior doc.
    """
    if kind == SENTINEL_KIND_ITEM_DONE:
        return SentinelFinding(kind=kind)
    if kind == SENTINEL_KIND_HANDOFF:
        plug = _extract(body, _PLUG_RE)
        return SentinelFinding(kind=kind, plug=plug or "")
    if kind in {SENTINEL_KIND_FOLLOWUP_BLOCKING, SENTINEL_KIND_FOLLOWUP_NONBLOCKING}:
        return _build_followup_finding(kind, body)
    if kind == SENTINEL_KIND_ITEM_BLOCKED:
        return _build_blocked_finding(body)
    if kind == SENTINEL_KIND_ITEM_FAILED:
        return SentinelFinding(kind=kind, reason=_extract(body, _REASON_RE))
    return None  # pragma: no cover — guarded by KNOWN_SENTINEL_KINDS check above


def _extract(body: str, pattern: re.Pattern[str]) -> str | None:
    """Return the inner text of the first ``pattern`` match, stripped.

    ``None`` when the pattern doesn't match. An empty match (matched
    but inner text is whitespace) is reported as an empty string,
    not ``None`` — the caller distinguishes "missing tag" from "empty
    tag" because some kinds treat an empty body as still-valid.
    """
    match = pattern.search(body)
    if match is None:
        return None
    return match.group("v").strip()


__all__ = [
    "SentinelFinding",
    "first_terminal",
    "parse",
]
