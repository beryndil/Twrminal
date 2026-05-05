"""Per-turn assistant-message persistence (item 1.9).

Per ``docs/architecture-v1.md`` §1.1.4 + §5 #3 this module owns the
boundary at which a per-turn :class:`bearings.agent.routing.RoutingDecision`
plus the SDK's ``ResultMessage.model_usage`` per-model breakdown becomes
a row in the ``messages`` table. Per ``docs/model-routing-v1-spec.md``
§5 every assistant message carries:

* the routing-decision projection (``executor_model``, ``advisor_model``,
  ``effort_level``, ``routing_source``, ``routing_reason``,
  ``matched_rule_id``); and
* the per-model usage projection (``executor_input_tokens``,
  ``executor_output_tokens``, ``advisor_input_tokens``,
  ``advisor_output_tokens``, ``advisor_calls_count``,
  ``cache_read_tokens``).

The :func:`persist_assistant_turn` entry point composes both
projections and dispatches to :func:`bearings.db.messages.insert_assistant`,
which writes the row + bumps the session message-count in one
implicit transaction.

Pure-function contract for :func:`extract_model_usage`:

* No I/O — input is the raw ``ResultMessage.model_usage`` dict the SDK
  exposes (per ``claude_agent_sdk.types.ResultMessage`` queried
  2026-04-28: ``dict[str, Any] | None`` whose values are per-model
  dicts keyed by model id) plus the active
  :class:`bearings.agent.routing.RoutingDecision`.
* Short-name model resolution — the routing layer accepts
  ``"sonnet"``/``"haiku"``/``"opus"`` short names per
  :data:`bearings.config.constants.KNOWN_EXECUTOR_MODELS` while the
  SDK keys ``model_usage`` by full SDK ids (e.g.
  ``"claude-sonnet-4-6"``). The matcher folds case + does a substring
  test so ``"sonnet"`` matches every Sonnet variant the SDK
  surfaces. Full-id matches (``executor_model`` already
  ``"claude-…"``) take precedence and require an exact key hit.
* Multiple keys mapping to the same role aggregate via summation —
  the SDK occasionally emits both a base-model entry and a thinking-
  variant entry; both count toward the same role total.
* ``advisor_calls_count`` is the *number of distinct keys* the
  matcher attributes to the advisor role. Spec §5 names the field
  "advisor_calls_count" (per-turn count of advisor invocations); the
  SDK exposes per-model entries whose count mirrors invocation count
  for the advisor model. ``0`` when no advisor was used or no
  advisor entry is present in ``model_usage``.

Item 1.7 + 1.8 verification (data-flow continuity):

* ``RoutingDecision`` is computed in ``agent/session_assembly.py`` via
  :func:`bearings.agent.routing.evaluate` + :func:`bearings.agent.quota.apply_quota_guard`.
* It is embedded in :class:`bearings.agent.session.SessionConfig` and
  referenced by the runner's :class:`bearings.agent.runner.RunnerStatus`
  + the wire-side :class:`bearings.agent.events.RoutingBadge`.
* Item 1.9 closes the loop: at message-completion time the
  per-turn driver (item 1.10+ ``agent/turn_executor.py``) calls
  :func:`persist_assistant_turn` with the same ``RoutingDecision``
  the runner has been carrying — no decision is dropped between
  evaluation and persistence.

References:

* ``docs/model-routing-v1-spec.md`` §5 (per-message routing/usage
  columns), §7 (Inspector Usage breakdown — which fields the API
  surfaces), §App A (RoutingDecision shape).
* ``docs/architecture-v1.md`` §1.1.4 (module home), §4.7
  (MessageComplete usage carriers), §5 #3 (model_usage shape).
* ``docs/behavior/chat.md`` §"Per-message routing badge" (user-
  observable surface that depends on this row's columns).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import aiosqlite

from bearings.agent.routing import RoutingDecision
from bearings.config.constants import (
    EXECUTOR_MODEL_FULL_ID_PREFIX,
    MODEL_USAGE_KEY_CACHE_READ_TOKENS,
    MODEL_USAGE_KEY_INPUT_TOKENS,
    MODEL_USAGE_KEY_OUTPUT_TOKENS,
)
from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db
from bearings.db.messages import Message


@dataclass(frozen=True)
class ModelUsageBreakdown:
    """Spec §5 per-message usage projection (six numeric columns).

    Output of :func:`extract_model_usage`; input to
    :func:`persist_assistant_turn` (which spreads it onto the
    :func:`bearings.db.messages.insert_assistant` keyword args).

    Field semantics are spec-verbatim:

    * ``executor_input_tokens`` / ``executor_output_tokens`` — sum
      across every ``model_usage`` entry whose key matches the active
      ``RoutingDecision.executor_model``.
    * ``advisor_input_tokens`` / ``advisor_output_tokens`` — sum
      across every entry matching ``RoutingDecision.advisor_model``;
      ``0`` when ``advisor_model`` is ``None`` or no matching entry
      appears.
    * ``advisor_calls_count`` — number of distinct ``model_usage``
      keys attributed to the advisor role per spec §5 "0 if no
      advisor call".
    * ``cache_read_tokens`` — sum across every entry's
      ``cache_read_input_tokens`` (per
      :data:`bearings.config.constants.MODEL_USAGE_KEY_CACHE_READ_TOKENS`),
      across executor + advisor combined (the spec §5 column is a
      single bucket — the SDK reports cache reads per model but
      Bearings persists the rolled-up total per spec).

    All fields default to ``0`` when ``model_usage`` is ``None``
    (the SDK's ``None`` carrier per ``claude_agent_sdk.types.ResultMessage``)
    rather than ``None`` — spec §5 declares the columns nullable but
    the captured-from-live-SDK path always has a real number to
    write; ``None`` is reserved for the legacy backfill carrier shape.
    """

    executor_input_tokens: int
    executor_output_tokens: int
    advisor_input_tokens: int
    advisor_output_tokens: int
    advisor_calls_count: int
    cache_read_tokens: int

    def __post_init__(self) -> None:
        for field_name, value in (
            ("executor_input_tokens", self.executor_input_tokens),
            ("executor_output_tokens", self.executor_output_tokens),
            ("advisor_input_tokens", self.advisor_input_tokens),
            ("advisor_output_tokens", self.advisor_output_tokens),
            ("advisor_calls_count", self.advisor_calls_count),
            ("cache_read_tokens", self.cache_read_tokens),
        ):
            if value < 0:
                raise ValueError(f"ModelUsageBreakdown.{field_name} must be >= 0 (got {value})")


def extract_model_usage(
    model_usage: Mapping[str, object] | None,
    decision: RoutingDecision,
) -> ModelUsageBreakdown:
    """Project ``ResultMessage.model_usage`` onto the spec §5 columns.

    Args:
        model_usage: The SDK exposes ``ResultMessage.model_usage``
            as ``dict[str, Any] | None`` (verified via the installed
            ``claude_agent_sdk.types.ResultMessage`` 2026-04-28); we
            accept the looser ``Mapping[str, object]`` here so a
            mypy-strict caller can pass the SDK value without an
            extra ``cast``. Each per-model value is structurally a
            mapping carrying at least ``input_tokens`` /
            ``output_tokens`` / ``cache_read_input_tokens`` (per
            Anthropic Messages-API convention). Missing keys are
            treated as ``0`` rather than raising — the SDK has
            shipped key-set churn between minor versions and the
            spec §5 columns are an aggregate view, not a one-to-one
            mirror.
        decision: Active :class:`RoutingDecision` for the turn. The
            :attr:`RoutingDecision.executor_model` and
            :attr:`RoutingDecision.advisor_model` (possibly ``None``)
            short names route each ``model_usage`` key into either
            the executor or advisor bucket via a case-insensitive
            substring match (full-SDK-id forms take exact-match
            precedence — see module docstring).

    Returns:
        Frozen :class:`ModelUsageBreakdown` with the six spec §5
        numeric columns. All fields are ``>= 0``.
    """
    if not model_usage:
        return ModelUsageBreakdown(
            executor_input_tokens=0,
            executor_output_tokens=0,
            advisor_input_tokens=0,
            advisor_output_tokens=0,
            advisor_calls_count=0,
            cache_read_tokens=0,
        )

    executor_input = 0
    executor_output = 0
    advisor_input = 0
    advisor_output = 0
    advisor_calls = 0
    cache_read_total = 0

    for model_key, payload in model_usage.items():
        if not isinstance(payload, Mapping):
            # Defence-in-depth: if the SDK shape drifts to a non-mapping
            # value, skip rather than crash. The aggregator queries
            # in web/routes/usage.py already use ``COALESCE`` so a
            # zero contribution is safe.
            continue
        input_tokens = _coerce_int(payload.get(MODEL_USAGE_KEY_INPUT_TOKENS))
        output_tokens = _coerce_int(payload.get(MODEL_USAGE_KEY_OUTPUT_TOKENS))
        cache_read_total += _coerce_int(payload.get(MODEL_USAGE_KEY_CACHE_READ_TOKENS))

        role = _classify_role(
            model_key=model_key,
            executor_model=decision.executor_model,
            advisor_model=decision.advisor_model,
        )
        if role == "executor":
            executor_input += input_tokens
            executor_output += output_tokens
        elif role == "advisor":
            advisor_input += input_tokens
            advisor_output += output_tokens
            advisor_calls += 1
        # role == "unmatched" — the cache-read total still
        # accumulates so the column reflects every SDK-reported cache
        # hit, but the input/output split goes nowhere. This matches
        # spec §5 "executor_*_tokens" semantics: only attribute to a
        # role when the role is identified.

    return ModelUsageBreakdown(
        executor_input_tokens=executor_input,
        executor_output_tokens=executor_output,
        advisor_input_tokens=advisor_input,
        advisor_output_tokens=advisor_output,
        advisor_calls_count=advisor_calls,
        cache_read_tokens=cache_read_total,
    )


def _classify_role(
    *,
    model_key: str,
    executor_model: str,
    advisor_model: str | None,
) -> str:
    """Return ``"executor"``/``"advisor"``/``"unmatched"`` for ``model_key``.

    Match precedence:

    1. Full SDK id on the routing decision (string starts with
       ``claude-`` per
       :data:`bearings.config.constants.EXECUTOR_MODEL_FULL_ID_PREFIX`)
       requires an exact case-folded match against ``model_key``.
    2. Short name (``sonnet`` / ``haiku`` / ``opus``) does a
       case-folded substring test against ``model_key``. SDK keys
       like ``"claude-sonnet-4-6"`` match ``"sonnet"`` this way.
    3. Executor wins ties (a key matching both the executor and
       advisor short names is attributed to the executor — should
       not occur in practice because executor and advisor are
       distinct models, but the rule is documented for determinism).
    """
    folded_key = model_key.casefold()

    if _matches_role(folded_key, executor_model):
        return "executor"
    if advisor_model is not None and _matches_role(folded_key, advisor_model):
        return "advisor"
    return "unmatched"


def _matches_role(folded_key: str, role_model: str) -> bool:
    """Return ``True`` if ``folded_key`` matches ``role_model`` per the rules."""
    folded_role = role_model.casefold()
    if folded_role.startswith(EXECUTOR_MODEL_FULL_ID_PREFIX):
        return folded_key == folded_role
    return folded_role in folded_key


def _coerce_int(value: object) -> int:
    """Best-effort int coercion for an opaque ``model_usage`` payload value.

    The SDK declares each per-model dict as ``dict[str, Any]`` so the
    Python type system gives no guarantees about value shapes. This
    coercer accepts ints + numeric-string ints; anything else
    (``None``, ``float`` like ``3.5``, ``str`` like ``"abc"``)
    coerces to ``0``. The spec §5 columns are integer counts; a
    non-integer value reaching this function is a malformed payload
    and dropping its contribution is safer than raising.
    """
    if isinstance(value, bool):  # bool is int subclass — reject.
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


# ---------------------------------------------------------------------------
# Persistence entry point
# ---------------------------------------------------------------------------


async def persist_assistant_turn(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    content: str,
    decision: RoutingDecision,
    model_usage: Mapping[str, object] | None,
    total_cost_usd: float | None = None,
) -> Message:
    """Insert one assistant-role message row for the turn just completed.

    Composes :func:`extract_model_usage` (pure projection) +
    :func:`bearings.db.messages.insert_assistant` (DB write) so the
    per-turn driver (item 1.10+ ``agent/turn_executor.py``) has one
    call site for "the turn produced this content; persist it". When
    ``total_cost_usd`` is supplied (the SDK's
    ``ResultMessage.total_cost_usd`` rollup), also increments the
    session row's cumulative ``total_cost_usd`` via
    :func:`bearings.db.sessions.add_to_total_cost` so the UI's
    "Total cost (USD)" surface tracks every billed turn.

    Args:
        connection: Open aiosqlite connection (the same one the
            session_assembly used).
        session_id: The session that owns this turn.
        content: Final assistant-text body for the turn (post-stream
            concatenation; the runner's per-token deltas are not
            persisted individually — only the completed message
            body, per arch §4.7 ``MessageComplete``).
        decision: Active :class:`RoutingDecision` for the turn (per
            spec §5 every assistant row records the decision; the
            same ``RoutingDecision`` flowed in from
            ``agent/session_assembly.py`` via the runner).
        model_usage: Raw ``ResultMessage.model_usage`` dict (or
            ``None`` if the turn was a pure-cache hit / synthetic
            replay — every field projects to ``0`` in that case).
        total_cost_usd: SDK ``ResultMessage.total_cost_usd`` for the
            turn. ``None`` / ``0`` / negative is a no-op for the
            session-row rollup (cache-only turns or synthetic
            replays bill nothing). Defaults to ``None`` so existing
            test call sites that pass only ``model_usage`` keep
            working.

    Returns:
        The persisted :class:`bearings.db.messages.Message` row.
    """
    breakdown = extract_model_usage(model_usage, decision)
    message = await messages_db.insert_assistant(
        connection,
        session_id=session_id,
        content=content,
        executor_model=decision.executor_model,
        advisor_model=decision.advisor_model,
        effort_level=decision.effort_level,
        routing_source=decision.source,
        routing_reason=decision.reason,
        matched_rule_id=decision.matched_rule_id,
        executor_input_tokens=breakdown.executor_input_tokens,
        executor_output_tokens=breakdown.executor_output_tokens,
        advisor_input_tokens=breakdown.advisor_input_tokens,
        advisor_output_tokens=breakdown.advisor_output_tokens,
        advisor_calls_count=breakdown.advisor_calls_count,
        cache_read_tokens=breakdown.cache_read_tokens,
    )
    if total_cost_usd is not None:
        await sessions_db.add_to_total_cost(connection, session_id, total_cost_usd)
    return message


class MessagePersistence(Protocol):
    """Arch §4.x — pure-IO interface for ``turn_executor.execute_turn`` (item 1.10+).

    Lets the per-turn driver depend on a Protocol rather than the
    concrete :func:`persist_assistant_turn` import, so unit tests of
    ``execute_turn`` can pass an in-memory fake. The production
    binding is :func:`persist_assistant_turn` itself (a stand-alone
    coroutine — Python's structural typing accepts a free function
    against this single-method Protocol via ``__call__``).
    """

    async def __call__(
        self,
        connection: aiosqlite.Connection,
        *,
        session_id: str,
        content: str,
        decision: RoutingDecision,
        model_usage: Mapping[str, object] | None,
        total_cost_usd: float | None = None,
    ) -> Message: ...


__all__ = [
    "MessagePersistence",
    "ModelUsageBreakdown",
    "extract_model_usage",
    "persist_assistant_turn",
]
