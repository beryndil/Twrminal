"""Unit tests — :mod:`bearings.agent.options` builder.

Covers each arch §5 deferred shift the 1.1 a1 audit confirmed lands
in item 1.2:

* Shift #2 (beta headers) — ``betas`` is empty when no advisor; carries
  :data:`ADVISOR_TOOL_BETA_HEADER` when advisor is wired.
* Shift #4 (effort levels) — every spec ``effort_level`` value maps to
  the SDK literal table.
* Shift #5 (fallback_model) — every short-name executor maps to its
  tier-down; full-form SDK IDs pass through verbatim.
* Shift #6 (subagent auto-select) — researcher carries ``model='inherit'``;
  spec §3 priority-30 rule handles the haiku-for-Explore intent at
  the routing layer (this test verifies the *subagent's* model is
  inherit, not pinned).

Plus :class:`SubagentSpec` validation and module surface.
"""

from __future__ import annotations

import pytest

from bearings.agent.options import (
    OptionsKwargs,
    SubagentSpec,
    build_options_kwargs,
)
from bearings.agent.routing import RoutingDecision
from bearings.config.constants import (
    ADVISOR_TOOL_BETA_HEADER,
    EFFORT_LEVEL_TO_SDK,
    EXECUTOR_FALLBACK_MODEL,
)


def _decision(
    *,
    executor: str = "sonnet",
    advisor: str | None = "opus",
    advisor_max_uses: int = 5,
    effort: str = "auto",
    source: str = "default",
) -> RoutingDecision:
    return RoutingDecision(
        executor_model=executor,
        advisor_model=advisor,
        advisor_max_uses=advisor_max_uses,
        effort_level=effort,
        source=source,
        reason="test",
        matched_rule_id=None,
    )


# ---------------------------------------------------------------------------
# Shift #2 — beta headers
# ---------------------------------------------------------------------------


def test_betas_empty_when_no_advisor() -> None:
    kwargs = build_options_kwargs(_decision(advisor=None))
    assert kwargs.betas == ()


def test_betas_carries_advisor_header_when_advisor_wired() -> None:
    kwargs = build_options_kwargs(_decision(advisor="opus"))
    assert kwargs.betas == (ADVISOR_TOOL_BETA_HEADER,)


# ---------------------------------------------------------------------------
# Shift #4 — effort level translation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec_label", "expected_sdk"),
    [
        ("auto", None),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("xhigh", "max"),
    ],
)
def test_effort_translation(spec_label: str, expected_sdk: str | None) -> None:
    kwargs = build_options_kwargs(_decision(effort=spec_label))
    assert kwargs.effort == expected_sdk


def test_effort_table_covers_every_known_label() -> None:
    """Self-consistency: every spec label maps to a value in the table."""
    from bearings.config.constants import KNOWN_EFFORT_LEVELS

    assert set(EFFORT_LEVEL_TO_SDK) == set(KNOWN_EFFORT_LEVELS)


# ---------------------------------------------------------------------------
# Shift #5 — fallback_model resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("executor", "expected_fallback"),
    [
        ("sonnet", "haiku"),
        ("opus", "sonnet"),
        ("haiku", "haiku"),
    ],
)
def test_fallback_model_for_short_names(executor: str, expected_fallback: str) -> None:
    kwargs = build_options_kwargs(_decision(executor=executor))
    assert kwargs.fallback_model == expected_fallback


def test_fallback_model_for_full_id_passes_through() -> None:
    kwargs = build_options_kwargs(_decision(executor="claude-sonnet-4-5"))
    assert kwargs.fallback_model == "claude-sonnet-4-5"


def test_fallback_table_covers_every_known_short_name() -> None:
    """Self-consistency: every short-name executor has a fallback row."""
    from bearings.config.constants import KNOWN_EXECUTOR_MODELS

    # ``opusplan`` is a routing alias resolved to ``opus`` upstream;
    # not a directly-pinnable executor model, so absence from
    # EXECUTOR_FALLBACK_MODEL is acceptable.
    pinnable = KNOWN_EXECUTOR_MODELS - {"opusplan"}
    assert pinnable <= set(EXECUTOR_FALLBACK_MODEL)


# ---------------------------------------------------------------------------
# Shift #6 — subagent auto-select (researcher inherits parent's model)
# ---------------------------------------------------------------------------


def test_researcher_subagent_carries_inherit_model() -> None:
    kwargs = build_options_kwargs(_decision())
    [researcher] = [s for s in kwargs.subagents if s.name == "researcher"]
    assert researcher.model == "inherit"
    # Description + prompt non-empty per arch §5 #6 + SubagentSpec
    # validators.
    assert researcher.description
    assert researcher.prompt


def test_researcher_subagent_tools_are_read_only() -> None:
    """Per arch §5 #6 + SubagentSpec docs: researcher is read-only."""
    kwargs = build_options_kwargs(_decision())
    [researcher] = [s for s in kwargs.subagents if s.name == "researcher"]
    assert "Write" not in researcher.tools
    assert "Edit" not in researcher.tools
    assert "Bash" not in researcher.tools


# ---------------------------------------------------------------------------
# Other deferred-shift adjacent fields
# ---------------------------------------------------------------------------


def test_advisor_max_uses_passes_through() -> None:
    kwargs = build_options_kwargs(_decision(advisor="opus", advisor_max_uses=3))
    assert kwargs.advisor_max_uses == 3


def test_advisor_max_uses_passes_through_even_when_no_advisor() -> None:
    """Per options.py docs the max_uses rides through even with no
    advisor — it's moot but carrying it through simplifies downstream
    "advisor was wired" reasoning."""
    kwargs = build_options_kwargs(_decision(advisor=None, advisor_max_uses=5))
    assert kwargs.advisor_max_uses == 5


def test_include_partial_messages_is_always_true() -> None:
    """Arch §5 #7: include_partial_messages is invariant for v1 so
    text/thinking/tool-output deltas stream through the SDK."""
    kwargs = build_options_kwargs(_decision())
    assert kwargs.include_partial_messages is True


def test_executor_model_passes_through() -> None:
    kwargs = build_options_kwargs(_decision(executor="opus"))
    assert kwargs.model == "opus"


# ---------------------------------------------------------------------------
# SubagentSpec validation
# ---------------------------------------------------------------------------


def test_subagent_spec_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="name"):
        SubagentSpec(name="", description="d", prompt="p", model="inherit")


def test_subagent_spec_rejects_empty_description() -> None:
    with pytest.raises(ValueError, match="description"):
        SubagentSpec(name="x", description="", prompt="p", model="inherit")


def test_subagent_spec_rejects_empty_prompt() -> None:
    with pytest.raises(ValueError, match="prompt"):
        SubagentSpec(name="x", description="d", prompt="", model="inherit")


def test_subagent_spec_accepts_inherit_model() -> None:
    spec = SubagentSpec(name="x", description="d", prompt="p", model="inherit")
    assert spec.model == "inherit"


def test_subagent_spec_accepts_full_sdk_id() -> None:
    spec = SubagentSpec(name="x", description="d", prompt="p", model="claude-sonnet-4-5")
    assert spec.model == "claude-sonnet-4-5"


def test_subagent_spec_rejects_arbitrary_short_name() -> None:
    """Short names pass through ``RoutingDecision`` validation; the
    subagent spec only accepts ``inherit`` or full IDs (per
    SubagentSpec docs — short-name validation is the routing
    layer's concern)."""
    with pytest.raises(ValueError, match="model"):
        SubagentSpec(name="x", description="d", prompt="p", model="sonnet")


# ---------------------------------------------------------------------------
# OptionsKwargs frozenness
# ---------------------------------------------------------------------------


def test_options_kwargs_is_frozen() -> None:
    kwargs = build_options_kwargs(_decision())
    with pytest.raises(Exception):
        kwargs.model = "haiku"  # type: ignore[misc]


def test_options_kwargs_subagents_is_tuple() -> None:
    """Frozen carriers use immutable collections so a downstream
    consumer can't mutate the shared instance."""
    kwargs = build_options_kwargs(_decision())
    assert isinstance(kwargs.subagents, tuple)
    assert isinstance(kwargs.betas, tuple)


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


def test_module_all_export_set() -> None:
    from bearings.agent import options as options_mod

    assert set(options_mod.__all__) == {
        "CanUseToolCallback",
        "OptionsKwargs",
        "SubagentSpec",
        "build_options_kwargs",
        "compose_session_options",
    }


def test_options_kwargs_is_dataclass_instance() -> None:
    """:class:`OptionsKwargs` is a frozen dataclass per
    options.py docs."""
    kwargs = build_options_kwargs(_decision())
    assert isinstance(kwargs, OptionsKwargs)
