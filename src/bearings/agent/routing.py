"""Routing-decision dataclass + ``evaluate()`` (spec §App A + §3).

This module lays down the immutable :class:`RoutingDecision` carrier
that :class:`bearings.agent.session.SessionConfig` embeds (per arch
§4.8) plus the pure :func:`evaluate` function that walks the routing
rule chain (spec §3) to produce a :class:`RoutingDecision` from a
first user message and a snapshot of the rule tables.

The ``apply_quota_guard`` companion lives in
:mod:`bearings.agent.quota` because the quota poller (the only impure
piece of the routing layer) lives there too — keeping the I/O class
and its pure-function partner colocated.

Validation lives in :meth:`RoutingDecision.__post_init__`. The set of
acceptable ``executor_model`` short names, ``effort_level`` labels, and
``source`` enum values are pulled from
:mod:`bearings.config.constants` per the item-0.5 "no inline literals"
gate. Long-form SDK model IDs (e.g. ``claude-sonnet-4-5``) are accepted
via the
:data:`bearings.config.constants.EXECUTOR_MODEL_FULL_ID_PREFIX` test —
the SDK resolves the long-form on its own, so the validator's job is to
catch typos like ``"sonet"`` or ``"oppus"`` at construction time
without enumerating every future model ID.

:func:`evaluate` is decided-and-documented as a pure function:

* No DB calls — caller pre-loads ``tags_with_rules`` /
  ``system_rules`` via :mod:`bearings.db.routing` helpers.
* No I/O — quota state is passed as a (possibly ``None``)
  :class:`bearings.agent.quota.QuotaSnapshot`.
* No clock reads — the function does not stamp timestamps. Callers
  that need a "decision captured at T" reference embed it via the
  enclosing per-message persistence path (item 1.9).

References:

* ``docs/model-routing-v1-spec.md`` §App A — frozen dataclass shape.
* ``docs/model-routing-v1-spec.md`` §3 — evaluation algorithm verbatim.
* ``docs/architecture-v1.md`` §4.1 — the same shape repeated as the
  arch-doc handoff to the implementer.
* ``docs/architecture-v1.md`` §4.4 — pure-function signatures.
* ``docs/architecture-v1.md`` §4.8 — :class:`SessionConfig` embedding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bearings.config.constants import (
    DEFAULT_ADVISOR_MAX_USES_SONNET,
    EXECUTOR_MODEL_FULL_ID_PREFIX,
    KNOWN_EFFORT_LEVELS,
    KNOWN_EXECUTOR_MODELS,
    KNOWN_ROUTING_SOURCES,
)

if TYPE_CHECKING:
    from bearings.agent.quota import QuotaSnapshot
    from bearings.db.routing import RoutingRule, SystemRoutingRule


@dataclass(frozen=True)
class RoutingDecision:
    """Spec §App A — the immutable result of a routing evaluation.

    Field semantics are spec-verbatim (see also arch §4.1):

    * ``executor_model`` — short-name from
      :data:`bearings.config.constants.KNOWN_EXECUTOR_MODELS` or a full
      SDK model ID (any string starting with ``claude-``).
    * ``advisor_model`` — short-name or full ID; ``None`` means no
      advisor on this turn.
    * ``advisor_max_uses`` — 0-to-N. Per spec §App A "ignored if
      ``advisor_model`` is None"; this validator allows 0 with a non-
      ``None`` advisor model (means "advisor declared but disabled
      this turn") so the routing layer can carry rule-table defaults
      through unchanged.
    * ``effort_level`` — one of
      :data:`bearings.config.constants.KNOWN_EFFORT_LEVELS`. The
      translation to SDK ``effort`` literal is owned by
      ``agent/options.py:build_options`` (item 1.2) via
      :data:`bearings.config.constants.EFFORT_LEVEL_TO_SDK`.
    * ``source`` — one of
      :data:`bearings.config.constants.KNOWN_ROUTING_SOURCES`.
    * ``reason`` — free-text, surfaced in the routing-badge tooltip.
    * ``matched_rule_id`` — the tag/system rule that fired (or
      ``None`` if no rule matched and the default applied).
    * ``evaluated_rules`` — ordered ids of every rule the evaluator
      tested; used by ``Inspector Routing`` per spec §6.
    * ``quota_state_at_decision`` — snapshot of overall + sonnet
      quota at the moment of evaluation; spec §App A keys
      ``overall_used_pct`` / ``sonnet_used_pct``.
    """

    executor_model: str
    advisor_model: str | None
    advisor_max_uses: int
    effort_level: str
    source: str
    reason: str
    matched_rule_id: int | None
    evaluated_rules: list[int] = field(default_factory=list)
    quota_state_at_decision: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.executor_model:
            raise ValueError("RoutingDecision.executor_model must be non-empty")
        if not _is_known_model(self.executor_model):
            raise ValueError(
                f"RoutingDecision.executor_model {self.executor_model!r} "
                f"is neither a known short name {sorted(KNOWN_EXECUTOR_MODELS)} "
                f"nor a full SDK ID prefixed with "
                f"{EXECUTOR_MODEL_FULL_ID_PREFIX!r}"
            )
        if self.advisor_model is not None and not _is_known_model(self.advisor_model):
            raise ValueError(
                f"RoutingDecision.advisor_model {self.advisor_model!r} is not a "
                f"known short name and does not begin with "
                f"{EXECUTOR_MODEL_FULL_ID_PREFIX!r}"
            )
        if self.effort_level not in KNOWN_EFFORT_LEVELS:
            raise ValueError(
                f"RoutingDecision.effort_level {self.effort_level!r} is not in "
                f"{sorted(KNOWN_EFFORT_LEVELS)}"
            )
        if self.advisor_max_uses < 0:
            raise ValueError(
                f"RoutingDecision.advisor_max_uses must be ≥ 0 (got {self.advisor_max_uses})"
            )
        if self.source not in KNOWN_ROUTING_SOURCES:
            raise ValueError(
                f"RoutingDecision.source {self.source!r} is not in {sorted(KNOWN_ROUTING_SOURCES)}"
            )


def _is_known_model(name: str) -> bool:
    """Return ``True`` if ``name`` is a known short name or full SDK ID."""
    return name in KNOWN_EXECUTOR_MODELS or name.startswith(EXECUTOR_MODEL_FULL_ID_PREFIX)


# ---------------------------------------------------------------------------
# evaluate() — spec §3 evaluation algorithm
# ---------------------------------------------------------------------------


def _walk_tag_rules(
    tags_with_rules: list[tuple[int, list[RoutingRule]]],
    message: str,
    evaluated_ids: list[int],
    quota_state: dict[str, float],
) -> RoutingDecision | None:
    """Walk enabled tag rules in priority order; return first match or None."""
    flat: list[RoutingRule] = []
    for _tag_id, rules in tags_with_rules:
        flat.extend(r for r in rules if r.enabled)
    flat.sort(key=lambda r: (r.priority, r.id))
    for rule in flat:
        evaluated_ids.append(rule.id)
        if _rule_matches(rule.match_type, rule.match_value, message):
            return _decision_from_tag_rule(
                rule=rule, evaluated_ids=evaluated_ids, quota_state=quota_state
            )
    return None


def _walk_system_rules(
    system_rules: list[SystemRoutingRule],
    message: str,
    evaluated_ids: list[int],
    quota_state: dict[str, float],
) -> RoutingDecision | None:
    """Walk enabled system rules in priority order; return first match or None."""
    enabled = sorted((r for r in system_rules if r.enabled), key=lambda r: (r.priority, r.id))
    for rule in enabled:
        evaluated_ids.append(rule.id)
        if _rule_matches(rule.match_type, rule.match_value, message):
            return _decision_from_system_rule(
                rule=rule, evaluated_ids=evaluated_ids, quota_state=quota_state
            )
    return None


def evaluate(
    message: str,
    tags_with_rules: list[tuple[int, list[RoutingRule]]],
    system_rules: list[SystemRoutingRule],
    quota_snapshot: QuotaSnapshot | None,
) -> RoutingDecision:
    """Spec §3 — walk the rule chain, return a :class:`RoutingDecision`.

    Algorithm (spec §3 verbatim):

    1. Collect all enabled rules from all tags applied to the session,
       in priority order across tags (lower priority number = checked
       first).
    2. Walk the list, evaluating each rule against the first user
       message.
    3. First match wins. Capture executor / advisor / max_uses /
       effort / reason; mark ``source = 'tag_rule'``.
    4. If no tag rule matches, evaluate enabled system rules in
       priority order. First match wins; mark
       ``source = 'system_rule'``.
    5. If no system rule matches either (which shouldn't happen given
       the seeded ``always`` fallback, but fail safe anyway), use the
       absolute default: Sonnet 4.6 executor + Opus 4.6 advisor +
       ``auto`` effort, ``source = 'default'``.

    The :func:`bearings.agent.quota.apply_quota_guard` companion
    folds quota-aware downgrades on top — callers that want the
    quota-aware decision invoke ``apply_quota_guard(evaluate(...),
    snapshot)`` (the preview endpoint, the new-session form, the
    session_assembly swap-in).

    Pure-function contract:

    * No DB calls. ``tags_with_rules`` is the
      ``[(tag_id, [rules])]`` shape returned by
      :func:`bearings.db.routing.list_for_tags`; ``system_rules`` is
      :func:`bearings.db.routing.list_system_rules`. The caller
      pre-loads.
    * Disabled rules in the input *are* filtered here as well —
      callers that pass ``enabled_only=False`` (the editor preview,
      the override-rate aggregator) get the same evaluation as
      callers that pre-filtered. This is a defence-in-depth: spec §3
      step 1 says "all enabled rules", so the function enforces.
    * The ``evaluated_rules`` field of the returned decision lists
      every rule the walker actually *tested* — i.e. up to and
      including the matching rule, not the entire input set. This is
      what the "Why this model?" debug surface (spec §6 +
      ``Inspector Routing``) renders as the evaluation chain.
    * Invalid match patterns (a malformed ``regex`` ``match_value``,
      an unparsable ``length_gt`` integer) cause the *individual rule*
      to be skipped (per spec §3 "Invalid regexes disable the rule")
      rather than aborting the whole walk.
    """
    quota_state = {} if quota_snapshot is None else quota_snapshot.quota_state_dict()
    evaluated_ids: list[int] = []

    # Step 1-3: collect and walk enabled tag rules.
    tag_match = _walk_tag_rules(tags_with_rules, message, evaluated_ids, quota_state)
    if tag_match is not None:
        return tag_match

    # Step 4: system rules.
    sys_match = _walk_system_rules(system_rules, message, evaluated_ids, quota_state)
    if sys_match is not None:
        return sys_match

    # Step 5: absolute default. Spec §3: "shouldn't happen given the
    # seeded ``always`` fallback, but fail safe anyway".
    return RoutingDecision(
        executor_model="sonnet",
        advisor_model="opus",
        advisor_max_uses=DEFAULT_ADVISOR_MAX_USES_SONNET,
        effort_level="auto",
        source="default",
        reason=(
            "absolute default — no tag rule, no system rule, no seeded fallback "
            "(workhorse Sonnet + Opus advisor + auto effort)"
        ),
        matched_rule_id=None,
        evaluated_rules=evaluated_ids,
        quota_state_at_decision=quota_state,
    )


def _decision_from_tag_rule(
    *,
    rule: RoutingRule,
    evaluated_ids: list[int],
    quota_state: dict[str, float],
) -> RoutingDecision:
    """Project a matched tag rule onto a :class:`RoutingDecision`."""
    return RoutingDecision(
        executor_model=rule.executor_model,
        advisor_model=rule.advisor_model,
        advisor_max_uses=rule.advisor_max_uses,
        effort_level=rule.effort_level,
        source="tag_rule",
        reason=rule.reason,
        matched_rule_id=rule.id,
        evaluated_rules=evaluated_ids,
        quota_state_at_decision=quota_state,
    )


def _decision_from_system_rule(
    *,
    rule: SystemRoutingRule,
    evaluated_ids: list[int],
    quota_state: dict[str, float],
) -> RoutingDecision:
    """Project a matched system rule onto a :class:`RoutingDecision`."""
    return RoutingDecision(
        executor_model=rule.executor_model,
        advisor_model=rule.advisor_model,
        advisor_max_uses=rule.advisor_max_uses,
        effort_level=rule.effort_level,
        source="system_rule",
        reason=rule.reason,
        matched_rule_id=rule.id,
        evaluated_rules=evaluated_ids,
        quota_state_at_decision=quota_state,
    )


def _match_keyword(match_value: str, message: str) -> bool:
    """Case-insensitive comma-separated keyword match; any term hits."""
    terms = [t.strip().lower() for t in match_value.split(",") if t.strip()]
    if not terms:
        return False
    message_lower = message.lower()
    return any(term in message_lower for term in terms)


def _match_regex(match_value: str, message: str) -> bool:
    """IGNORECASE regex match; invalid regex returns False (rule disabled)."""
    try:
        return re.search(match_value, message, flags=re.IGNORECASE) is not None
    except re.error:
        return False


def _match_length(match_value: str, message: str, *, gt: bool) -> bool:
    """Integer length threshold match; unparsable match_value returns False."""
    try:
        threshold = int(match_value)
    except ValueError:
        return False
    return len(message) > threshold if gt else len(message) < threshold


def _rule_matches(match_type: str, match_value: str | None, message: str) -> bool:
    """Spec §3 ``Match types`` — return ``True`` if ``message`` matches.

    Match semantics (spec §3 verbatim):

    * ``always`` — unconditional True regardless of ``match_value``.
    * ``keyword`` — case-insensitive substring match against the
      message; ``match_value`` is a comma-separated list, any term
      hits. Empty terms (e.g. trailing comma) are skipped.
    * ``regex`` — Python ``re.IGNORECASE`` regex against the message.
      Invalid regex disables the rule (returns ``False``) per spec §3
      "Invalid regexes disable the rule".
    * ``length_gt`` / ``length_lt`` — integer compare against
      ``len(message)``. Unparsable ``match_value`` returns ``False``
      (defence-in-depth — DB-layer validation should already reject,
      but malformed legacy rows shouldn't crash routing).
    """
    if match_type == "always":
        return True
    if not match_value:
        return False
    if match_type == "keyword":
        return _match_keyword(match_value, message)
    if match_type == "regex":
        return _match_regex(match_value, message)
    if match_type == "length_gt":
        return _match_length(match_value, message, gt=True)
    if match_type == "length_lt":
        return _match_length(match_value, message, gt=False)
    # Unknown match_type — DB-layer validation should reject, but
    # fail-safe at the runtime boundary.
    return False  # pragma: no cover — defence-in-depth fallthrough


__all__ = ["RoutingDecision", "evaluate"]
