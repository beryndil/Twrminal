# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/usage.py`` (spec §9 usage endpoints).

Phase 3 (analytics) additions
------------------------------
* ``cache_creation_tokens`` added to :class:`UsageByModelRow` and
  :class:`UsageByTagRow` — Phase 0 landed the column on ``messages``;
  Phase 3 exposes it on the wire.
* :class:`TurnOut` — one row of ``GET /api/usage/turns``, surfacing the
  Phase 1 ``turns`` table directly (per-turn token accounting from the
  Claude Agent SDK).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class UsageByModelRow(BaseModel):
    """One row of ``GET /api/usage/by_model?period=week``.

    Per spec §8 "Quota efficiency" the by_model surface aggregates
    per-model token totals plus advisor calls + cache reads. The
    aggregation slices ``messages`` rows by their per-message routing
    columns (item 1.9 wires the writes).

    ``cache_creation_tokens`` is summed from ``messages.cache_creation_tokens``
    (landed in Phase 0) and exposed here from Phase 3 onward.
    Advisor rows always carry ``cache_creation_tokens=0`` since
    cache-creation costs attach to the executor turn.
    """

    model_config = ConfigDict(extra="forbid")

    model: str
    role: str  # "executor" or "advisor"
    input_tokens: int
    output_tokens: int
    advisor_calls: int
    cache_read_tokens: int
    cache_creation_tokens: int
    sessions: int


class UsageByTagRow(BaseModel):
    """One row of ``GET /api/usage/by_tag?period=week``.

    Tags are the user-facing classification surface; this slice rolls
    up the per-message totals into per-tag aggregates so the inspector
    can attribute spend to a tag.

    ``cache_creation_tokens`` is the sum of ``messages.cache_creation_tokens``
    across all messages in the window for sessions tagged with this tag.
    """

    model_config = ConfigDict(extra="forbid")

    tag_id: int
    tag_name: str
    executor_input_tokens: int
    executor_output_tokens: int
    advisor_input_tokens: int
    advisor_output_tokens: int
    advisor_calls: int
    cache_creation_tokens: int
    sessions: int


class TurnOut(BaseModel):
    """One row of ``GET /api/usage/turns``.

    Exposes the Phase 1 ``turns`` table — one row per Claude Agent SDK
    turn, carrying the per-model token counts reported by the API.

    Per spec §3.2, token counts from different models must not be
    aggregated without grouping by model first.  Callers must group
    by ``model`` before summing ``input_tokens`` + ``output_tokens``.

    ``timestamp`` is unix milliseconds (spec §4.1 convention).
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    turn_index: int
    timestamp: int  # unix ms
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


class OverrideRateOut(BaseModel):
    """One row of ``GET /api/usage/override_rates?days=14`` per spec §9."""

    model_config = ConfigDict(extra="forbid")

    rule_kind: str
    rule_id: int
    fired_count: int
    overridden_count: int
    rate: float
    review: bool


__all__ = ["OverrideRateOut", "TurnOut", "UsageByModelRow", "UsageByTagRow"]
