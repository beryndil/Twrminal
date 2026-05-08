"""Quota guard unit tests (item 1.8; spec §4).

Pure-function tests against :func:`bearings.agent.quota.apply_quota_guard`.
Done-when bar: ≥10 quota guard tests; this file lands 16 covering each
downgrade-ladder transition, threshold edge cases, and the
no-snapshot fail-open path.
"""

from __future__ import annotations

import time

import pytest

from bearings.agent.quota import (
    QuotaSnapshot,
    apply_quota_guard,
    empty_snapshot,
)
from bearings.agent.routing import RoutingDecision


def _decision(
    *,
    executor_model: str = "sonnet",
    advisor_model: str | None = "opus",
    advisor_max_uses: int = 5,
    effort_level: str = "auto",
    source: str = "system_rule",
    reason: str = "test",
    matched_rule_id: int | None = 1,
) -> RoutingDecision:
    return RoutingDecision(
        executor_model=executor_model,
        advisor_model=advisor_model,
        advisor_max_uses=advisor_max_uses,
        effort_level=effort_level,
        source=source,
        reason=reason,
        matched_rule_id=matched_rule_id,
    )


def _snapshot(
    *,
    overall: float | None = None,
    sonnet: float | None = None,
) -> QuotaSnapshot:
    return QuotaSnapshot(
        captured_at=int(time.time()),
        overall_used_pct=overall,
        sonnet_used_pct=sonnet,
        overall_resets_at=None,
        sonnet_resets_at=None,
        raw_payload="{}",
    )


# ---------------------------------------------------------------------------
# No-op paths
# ---------------------------------------------------------------------------


def test_none_snapshot_returns_decision_unchanged() -> None:
    """No quota info → fail open, no downgrade."""
    decision = _decision(executor_model="opus", advisor_model="opus")
    result = apply_quota_guard(decision, None)
    assert result is decision


def test_below_threshold_does_not_downgrade() -> None:
    """Buckets below 80% → no downgrade, but quota_state populated."""
    decision = _decision(executor_model="opus", advisor_model="opus")
    snapshot = _snapshot(overall=0.5, sonnet=0.4)
    result = apply_quota_guard(decision, snapshot)
    assert result.executor_model == "opus"
    assert result.advisor_model == "opus"
    assert result.source == decision.source
    assert result.quota_state_at_decision == {
        "overall_used_pct": 0.5,
        "sonnet_used_pct": 0.4,
    }


def test_quota_state_dict_zero_pct_not_coerced() -> None:
    """quota_state_dict must preserve 0.0 — not conflate it with None.

    Regression for finding feature-3-007: the old ``x or 0.0`` form
    treated both ``None`` and ``0.0`` as falsy, which happened to produce
    the correct number but lost intent.  The explicit
    ``x if x is not None else 0.0`` form is required.
    """
    snapshot = _snapshot(overall=0.0, sonnet=0.0)
    result = snapshot.quota_state_dict()
    assert result == {"overall_used_pct": 0.0, "sonnet_used_pct": 0.0}


def test_no_op_when_already_at_floor() -> None:
    """Haiku executor + no advisor + tripped buckets → still haiku."""
    decision = _decision(executor_model="haiku", advisor_model=None)
    snapshot = _snapshot(overall=0.95, sonnet=0.95)
    result = apply_quota_guard(decision, snapshot)
    assert result.executor_model == "haiku"
    assert result.advisor_model is None


# ---------------------------------------------------------------------------
# Step 1: overall-bucket downgrades
# ---------------------------------------------------------------------------


def test_overall_high_downgrades_opus_executor_to_sonnet() -> None:
    """``overall >= 0.80`` → executor opus → sonnet."""
    decision = _decision(executor_model="opus", advisor_model=None)
    snapshot = _snapshot(overall=0.85)
    result = apply_quota_guard(decision, snapshot)
    assert result.executor_model == "sonnet"
    assert result.source == "quota_downgrade"
    assert "85" in result.reason


def test_overall_high_downgrades_opusplan_executor_to_sonnet() -> None:
    """opusplan (the §1 alias for executor=opus) also downgrades."""
    decision = _decision(executor_model="opusplan", advisor_model=None)
    snapshot = _snapshot(overall=0.81)
    result = apply_quota_guard(decision, snapshot)
    assert result.executor_model == "sonnet"
    assert result.source == "quota_downgrade"


def test_overall_high_disables_opus_advisor() -> None:
    """``overall >= 0.80`` → advisor opus → None (advisor disabled)."""
    decision = _decision(executor_model="sonnet", advisor_model="opus")
    snapshot = _snapshot(overall=0.90)
    result = apply_quota_guard(decision, snapshot)
    assert result.advisor_model is None
    assert result.source == "quota_downgrade"


def test_overall_high_downgrades_both_executor_and_advisor() -> None:
    """Opus+Opus pair: executor → sonnet, advisor disabled."""
    decision = _decision(executor_model="opus", advisor_model="opus")
    snapshot = _snapshot(overall=0.82)
    result = apply_quota_guard(decision, snapshot)
    assert result.executor_model == "sonnet"
    assert result.advisor_model is None
    assert result.source == "quota_downgrade"


def test_overall_threshold_inclusive_at_exactly_80() -> None:
    """Spec §4: ``>= 0.80`` is inclusive — 0.80 itself trips the guard."""
    decision = _decision(executor_model="opus", advisor_model="opus")
    snapshot = _snapshot(overall=0.80)
    result = apply_quota_guard(decision, snapshot)
    assert result.executor_model == "sonnet"
    assert result.advisor_model is None


def test_overall_just_below_threshold_does_not_trip() -> None:
    """0.799 → no downgrade."""
    decision = _decision(executor_model="opus", advisor_model="opus")
    snapshot = _snapshot(overall=0.799)
    result = apply_quota_guard(decision, snapshot)
    assert result.executor_model == "opus"
    assert result.advisor_model == "opus"


# ---------------------------------------------------------------------------
# Step 2: sonnet-bucket downgrades
# ---------------------------------------------------------------------------


def test_sonnet_high_downgrades_sonnet_executor_to_haiku() -> None:
    """``sonnet >= 0.80`` AND executor==sonnet → haiku."""
    decision = _decision(executor_model="sonnet", advisor_model="opus")
    snapshot = _snapshot(overall=0.30, sonnet=0.85)
    result = apply_quota_guard(decision, snapshot)
    assert result.executor_model == "haiku"
    assert result.source == "quota_downgrade"
    # Spec §4: keep advisor (advisor uses overall bucket).
    assert result.advisor_model == "opus"


def test_sonnet_high_does_not_affect_haiku_executor() -> None:
    """A haiku executor is unaffected by the sonnet bucket."""
    decision = _decision(executor_model="haiku", advisor_model="opus")
    snapshot = _snapshot(overall=0.50, sonnet=0.95)
    result = apply_quota_guard(decision, snapshot)
    assert result.executor_model == "haiku"
    assert result.advisor_model == "opus"


def test_sonnet_high_does_not_affect_opus_executor() -> None:
    """An opus executor is unaffected by the sonnet bucket alone."""
    decision = _decision(executor_model="opus", advisor_model=None)
    snapshot = _snapshot(overall=0.30, sonnet=0.95)
    result = apply_quota_guard(decision, snapshot)
    assert result.executor_model == "opus"


# ---------------------------------------------------------------------------
# Combined ladder behaviour
# ---------------------------------------------------------------------------


def test_both_buckets_high_chains_opus_to_sonnet_to_haiku() -> None:
    """Both buckets ≥0.80 → opus → sonnet (step 1) → haiku (step 2)."""
    decision = _decision(executor_model="opus", advisor_model="opus")
    snapshot = _snapshot(overall=0.85, sonnet=0.85)
    result = apply_quota_guard(decision, snapshot)
    assert result.executor_model == "haiku"
    assert result.advisor_model is None
    assert result.source == "quota_downgrade"


def test_only_sonnet_bucket_high_with_opus_executor_leaves_opus() -> None:
    """Only sonnet bucket high → opus executor untouched (step 1 not tripped)."""
    decision = _decision(executor_model="opus", advisor_model="opus")
    snapshot = _snapshot(overall=0.50, sonnet=0.95)
    result = apply_quota_guard(decision, snapshot)
    assert result.executor_model == "opus"
    assert result.advisor_model == "opus"


# ---------------------------------------------------------------------------
# Empty / partial snapshots
# ---------------------------------------------------------------------------


def test_empty_snapshot_does_not_downgrade() -> None:
    """An ``empty_snapshot`` (both buckets None) → no downgrade."""
    decision = _decision(executor_model="opus", advisor_model="opus")
    result = apply_quota_guard(decision, empty_snapshot(captured_at=1))
    assert result.executor_model == "opus"
    assert result.advisor_model == "opus"


def test_only_overall_bucket_known_still_downgrades() -> None:
    """Sonnet pct None but overall high → step 1 still fires."""
    decision = _decision(executor_model="opus", advisor_model="opus")
    snapshot = _snapshot(overall=0.85, sonnet=None)
    result = apply_quota_guard(decision, snapshot)
    assert result.executor_model == "sonnet"
    assert result.advisor_model is None


# ---------------------------------------------------------------------------
# Quota state propagation
# ---------------------------------------------------------------------------


def test_downgrade_populates_quota_state_field() -> None:
    """Post-guard ``quota_state_at_decision`` carries the snapshot picture."""
    decision = _decision(executor_model="opus", advisor_model="opus")
    snapshot = _snapshot(overall=0.85, sonnet=0.40)
    result = apply_quota_guard(decision, snapshot)
    assert result.quota_state_at_decision == {
        "overall_used_pct": 0.85,
        "sonnet_used_pct": 0.40,
    }


@pytest.mark.parametrize("pct", [0.0, 0.5, 0.799999])
def test_below_threshold_pct_values_do_not_trip(pct: float) -> None:
    """Boundary table: nothing below 0.80 triggers the guard."""
    decision = _decision(executor_model="opus", advisor_model="opus")
    snapshot = _snapshot(overall=pct, sonnet=pct)
    result = apply_quota_guard(decision, snapshot)
    assert result.executor_model == "opus"
    assert result.advisor_model == "opus"
