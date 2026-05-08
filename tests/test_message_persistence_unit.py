"""Unit tests for :mod:`bearings.agent.persistence` (item 1.9).

Covers the three pure-projection contracts in
``docs/model-routing-v1-spec.md`` §5 + §App A:

* ``ModelUsageBreakdown`` validation rejects negative token counters
  (the dataclass invariant guards against an SDK shape regression).
* ``extract_model_usage`` projects ``ResultMessage.model_usage``
  (``dict[str, Any] | None`` per
  ``claude_agent_sdk.types.ResultMessage``) onto the six spec §5
  numeric columns. Coverage:
    * No advisor → advisor totals are zero.
    * Short-name vs full-id matching against SDK keys.
    * Multiple per-model entries summing into the same role.
    * Unmatched keys still contribute to ``cache_read_tokens``.
    * Malformed payload values coerce to zero, not raise.
* ``persist_assistant_turn`` is a thin composition; the integration
  test exercises its end-to-end DB round-trip. Here we cover the
  pure projection only.
"""

from __future__ import annotations

import pytest

from bearings.agent.persistence import (
    ModelUsageBreakdown,
    extract_model_usage,
)
from bearings.agent.routing import RoutingDecision


def _decision(
    *,
    executor: str = "sonnet",
    advisor: str | None = "opus",
    source: str = "system_rule",
) -> RoutingDecision:
    """Tiny builder so each test reads cleanly."""
    return RoutingDecision(
        executor_model=executor,
        advisor_model=advisor,
        advisor_max_uses=5,
        effort_level="auto",
        source=source,
        reason="test fixture",
        matched_rule_id=None,
    )


def test_breakdown_rejects_negative_token_count() -> None:
    with pytest.raises(ValueError, match="executor_input_tokens"):
        ModelUsageBreakdown(
            executor_input_tokens=-1,
            executor_output_tokens=0,
            advisor_input_tokens=0,
            advisor_output_tokens=0,
            advisor_calls_count=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )


def test_extract_none_returns_all_zero_breakdown() -> None:
    """``model_usage=None`` (no SDK data — synthetic / replayed turn)
    yields a zero-valued breakdown, not ``None``."""
    breakdown = extract_model_usage(None, _decision())
    assert breakdown == ModelUsageBreakdown(
        executor_input_tokens=0,
        executor_output_tokens=0,
        advisor_input_tokens=0,
        advisor_output_tokens=0,
        advisor_calls_count=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
    )


def test_extract_short_name_matches_full_sdk_id_keys() -> None:
    """Routing decision uses ``"sonnet"`` short name; SDK keys use full ids."""
    model_usage = {
        "claude-sonnet-4-6": {
            "inputTokens": 1200,
            "outputTokens": 350,
            "cacheReadInputTokens": 800,
        },
        "claude-opus-4-6": {
            "inputTokens": 90,
            "outputTokens": 45,
            "cacheReadInputTokens": 20,
        },
    }
    breakdown = extract_model_usage(model_usage, _decision())
    assert breakdown.executor_input_tokens == 1200
    assert breakdown.executor_output_tokens == 350
    assert breakdown.advisor_input_tokens == 90
    assert breakdown.advisor_output_tokens == 45
    assert breakdown.advisor_calls_count == 1
    assert breakdown.cache_read_tokens == 820


def test_extract_no_advisor_yields_zero_advisor_totals() -> None:
    """``advisor_model=None`` → advisor totals are zero, count is zero."""
    model_usage = {
        "claude-opus-4-7": {
            "inputTokens": 500,
            "outputTokens": 200,
            "cacheReadInputTokens": 0,
        },
    }
    breakdown = extract_model_usage(
        model_usage,
        _decision(executor="opus", advisor=None),
    )
    assert breakdown.executor_input_tokens == 500
    assert breakdown.advisor_input_tokens == 0
    assert breakdown.advisor_output_tokens == 0
    assert breakdown.advisor_calls_count == 0


def test_extract_full_sdk_id_decision_requires_exact_match() -> None:
    """A ``RoutingDecision.executor_model`` that is itself a full SDK
    id only matches the exact-key entry — substring won't apply."""
    model_usage = {
        "claude-sonnet-4-6": {"inputTokens": 100, "outputTokens": 10},
        "claude-sonnet-4-7": {"inputTokens": 999, "outputTokens": 88},
    }
    breakdown = extract_model_usage(
        model_usage,
        _decision(executor="claude-sonnet-4-6", advisor=None),
    )
    # Only the 4-6 row counts; 4-7 is unmatched.
    assert breakdown.executor_input_tokens == 100
    assert breakdown.executor_output_tokens == 10


def test_extract_multiple_keys_per_role_sum() -> None:
    """SDK occasionally emits split entries (e.g. base + thinking
    variant); both attribute to the same role and sum."""
    model_usage = {
        "claude-sonnet-4-6": {"inputTokens": 100, "outputTokens": 50},
        "claude-sonnet-4-6-thinking": {
            "inputTokens": 200,
            "outputTokens": 75,
            "cacheReadInputTokens": 40,
        },
        "claude-opus-4-6": {
            "inputTokens": 30,
            "outputTokens": 15,
        },
    }
    breakdown = extract_model_usage(model_usage, _decision())
    assert breakdown.executor_input_tokens == 300
    assert breakdown.executor_output_tokens == 125
    assert breakdown.advisor_input_tokens == 30
    assert breakdown.advisor_output_tokens == 15
    assert breakdown.advisor_calls_count == 1
    assert breakdown.cache_read_tokens == 40


def test_extract_unmatched_keys_still_contribute_cache_read() -> None:
    """A key that matches neither role still adds to cache_read total."""
    model_usage = {
        "claude-haiku-4-5": {
            "inputTokens": 999,
            "outputTokens": 99,
            "cacheReadInputTokens": 200,
        },
    }
    breakdown = extract_model_usage(model_usage, _decision())
    assert breakdown.executor_input_tokens == 0
    assert breakdown.advisor_input_tokens == 0
    assert breakdown.advisor_calls_count == 0
    # Cache reads still surface in the rolled-up bucket so the
    # spec §5 cache_read_tokens column reflects every cache hit.
    assert breakdown.cache_read_tokens == 200


def test_extract_missing_keys_default_to_zero() -> None:
    """A per-model dict that omits ``output_tokens`` doesn't crash."""
    model_usage = {
        "claude-sonnet-4-6": {"inputTokens": 50},  # no output_tokens
    }
    breakdown = extract_model_usage(model_usage, _decision(advisor=None))
    assert breakdown.executor_input_tokens == 50
    assert breakdown.executor_output_tokens == 0


def test_extract_malformed_payload_skipped() -> None:
    """A non-mapping value in ``model_usage`` is silently skipped."""
    model_usage = {
        "claude-sonnet-4-6": "not-a-dict",  # malformed
        "claude-opus-4-6": {"inputTokens": 10, "outputTokens": 5},
    }
    breakdown = extract_model_usage(model_usage, _decision())
    assert breakdown.executor_input_tokens == 0
    assert breakdown.advisor_input_tokens == 10
    assert breakdown.advisor_calls_count == 1


def test_extract_non_int_token_value_coerces_to_zero() -> None:
    """Float / string / None token values coerce to ``0`` rather than raising."""
    model_usage = {
        "claude-sonnet-4-6": {
            "inputTokens": 3.5,  # float — invalid per spec
            "outputTokens": "100",  # numeric string — accepted
            "cacheReadInputTokens": None,
        },
    }
    breakdown = extract_model_usage(model_usage, _decision(advisor=None))
    assert breakdown.executor_input_tokens == 0
    assert breakdown.executor_output_tokens == 100
    assert breakdown.cache_read_tokens == 0


def test_extract_case_insensitive_role_match() -> None:
    """SDK keys with different casing still resolve via case-fold."""
    model_usage = {
        "CLAUDE-SONNET-4-6": {"inputTokens": 7, "outputTokens": 3},
    }
    breakdown = extract_model_usage(model_usage, _decision(advisor=None))
    assert breakdown.executor_input_tokens == 7


def test_extract_handles_real_sdk_payload_shape() -> None:
    """Pin the **actual** ``ResultMessage.model_usage`` shape the SDK emits.

    Regression: bearings's :data:`MODEL_USAGE_KEY_INPUT_TOKENS` etc. were
    snake_case (``input_tokens`` / ``output_tokens`` /
    ``cache_read_input_tokens``) for the lifetime of v1, but the SDK
    forwards the per-model dict verbatim from the CLI wire
    (``_internal/message_parser.py``: ``model_usage=data.get("modelUsage")``)
    and the wire uses **camelCase** (``inputTokens`` / ``outputTokens`` /
    ``cacheReadInputTokens`` / ``cacheCreationInputTokens`` / ``costUSD`` /
    ``webSearchRequests`` / ``contextWindow`` / ``maxOutputTokens``). The
    snake_case keys silently missed every payload, so every assistant
    turn persisted with ``executor_*_tokens=0`` and ``total_cost_usd=0``.

    The payload below is **verbatim** from a live SDK ``ResultMessage``
    (Opus 4.7, "say PONG" turn). If the SDK shape regresses this test
    fails before any session sees zero costs in production.
    """
    real_world_payload = {
        "claude-opus-4-7[1m]": {
            "inputTokens": 6,
            "outputTokens": 7,
            "cacheReadInputTokens": 17042,
            "cacheCreationInputTokens": 18267,
            "webSearchRequests": 0,
            "costUSD": 0.22203625,
            "contextWindow": 1000000,
            "maxOutputTokens": 64000,
        },
    }
    breakdown = extract_model_usage(
        real_world_payload,
        _decision(executor="opus", advisor=None),
    )
    assert breakdown.executor_input_tokens == 6
    assert breakdown.executor_output_tokens == 7
    assert breakdown.cache_read_tokens == 17042
