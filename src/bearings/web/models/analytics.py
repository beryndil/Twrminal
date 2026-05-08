# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/analytics.py``.

Per ``docs/architecture-v1.md`` §1.1.5 the wire DTOs live alongside the
route module.  These shapes mirror the five :mod:`bearings.db.analytics`
dataclasses for the read path, and define request bodies for the logging
path (``POST /api/analytics/turns`` and
``POST /api/analytics/plug-blocks/batch``).

Phase 1 ships the schema and these models; the route module that binds
them arrives in a later phase.  All field names follow the JSON
conventions from ``BEARINGS_ANALYTICS_v1.md`` §9.

The ``mypy: disable-error-code=explicit-any`` pragma matches the narrow
carve-out other ``web/models/*`` modules make for Pydantic's
metaclass-exposed ``Any`` surface.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from bearings.config.constants import (
    KNOWN_ANALYTICS_BLOCK_TYPES,
    KNOWN_ANALYTICS_WARNING_TYPES,
    PLUG_RED_THRESHOLD_TOKENS,
    PLUG_YELLOW_THRESHOLD_TOKENS,
)

# ---------------------------------------------------------------------------
# Logging endpoint request shapes (§9.1)
# ---------------------------------------------------------------------------

_BLOCK_TYPE_VALUES: list[str] = sorted(KNOWN_ANALYTICS_BLOCK_TYPES)
_WARNING_TYPE_VALUES: list[str] = sorted(KNOWN_ANALYTICS_WARNING_TYPES)


class TurnIn(BaseModel):
    """Request body for ``POST /api/analytics/turns`` (§9.1).

    Records one Claude API turn's token consumption.  All token fields
    default to 0 so callers can omit fields absent from the SDK response
    (e.g. cache tokens on non-caching models).

    ``model`` is mandatory and must be non-empty — every token count row
    carries the model so aggregation queries can group by model before
    summing (spec §3.2 tokenizer constraint).
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    turn_index: int = Field(ge=0)
    model: str = Field(min_length=1)
    input_tokens: int = Field(ge=0, default=0)
    output_tokens: int = Field(ge=0, default=0)
    cache_read_tokens: int = Field(ge=0, default=0)
    cache_creation_tokens: int = Field(ge=0, default=0)


class PlugBlockIn(BaseModel):
    """One plug block descriptor inside a ``POST /api/analytics/plug-blocks/batch`` body."""

    model_config = ConfigDict(extra="forbid")

    hash: str = Field(min_length=64, max_length=64, description="sha256 hex digest")
    block_type: str = Field(description=f"One of: {_BLOCK_TYPE_VALUES}")
    content: str = Field(min_length=1)
    source_path: str | None = None


class PlugBlocksBatchIn(BaseModel):
    """Request body for ``POST /api/analytics/plug-blocks/batch`` (§9.1).

    Records the full set of plug blocks injected into a session at
    creation time.  ``model`` is the session's configured executor model,
    used to token-count each block on first insert (spec §5.3).
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    blocks: list[PlugBlockIn] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Read endpoint response shapes (§9.2)
# ---------------------------------------------------------------------------


class BucketWindowOut(BaseModel):
    """One usage window (5-hour or weekly) inside :class:`BucketCurrentOut`."""

    model_config = ConfigDict(extra="forbid")

    used: int
    limit: int
    percent: float = Field(ge=0.0, le=100.0)


class BucketCurrentOut(BaseModel):
    """Response for ``GET /api/analytics/bucket/current`` (§9.2)."""

    model_config = ConfigDict(extra="forbid")

    five_hour: BucketWindowOut | None = None
    weekly: BucketWindowOut | None = None
    as_of: int = Field(description="unix ms timestamp of the snapshot")


class TagAttributionOut(BaseModel):
    """One row of ``GET /api/analytics/attribution`` (§9.2).

    ``tokens_by_model`` is a dict mapping model name → total tokens for
    that model within the requested window.  Callers must NOT sum across
    model keys without normalisation — the spec's §3.2 constraint
    (different tokenizers) means cross-model sums are misleading.
    ``share_total`` is the fraction of all tokens in the window consumed
    by this tag's sessions, computed after grouping by model.
    """

    model_config = ConfigDict(extra="forbid")

    tag: str
    tokens_by_model: dict[str, int]
    share_total: float = Field(ge=0.0, le=1.0)
    burn_rate_per_min: float = Field(ge=0.0)


class RedundancySessionRef(BaseModel):
    """Session reference inside a :class:`RedundancyBlockOut` row."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    timestamp: int
    tags: list[str]


class RedundancyBlockOut(BaseModel):
    """One row of ``GET /api/analytics/redundancy`` (§9.2)."""

    model_config = ConfigDict(extra="forbid")

    hash: str
    block_type: str
    token_count: int
    token_count_model: str
    repeat_count: int
    total_cost_tokens: int
    sessions: list[RedundancySessionRef]
    source_path: str | None = None


class PlugBlockOut(BaseModel):
    """Response for ``GET /api/analytics/plug-blocks/{hash}`` (§9.2).

    ``content`` is the raw block text.  ``versions`` is populated only
    by the ``/versions`` sub-endpoint (§9.2); on the base endpoint it
    is omitted (``None``).
    """

    model_config = ConfigDict(extra="forbid")

    id: int
    hash: str
    block_type: str
    content: str
    token_count: int
    token_count_model: str
    first_seen: int
    last_seen: int
    source_path: str | None = None


class PlugSummaryBlockOut(BaseModel):
    """One block entry inside :class:`SessionPlugSummaryOut`."""

    model_config = ConfigDict(extra="forbid")

    hash: str
    block_type: str
    tokens: int


class SessionPlugSummaryOut(BaseModel):
    """Response for ``GET /api/analytics/sessions/{id}/plug-summary`` (§9.2).

    ``status`` is derived from ``total_tokens`` vs the configured
    thresholds (``PLUG_YELLOW_THRESHOLD_TOKENS`` /
    ``PLUG_RED_THRESHOLD_TOKENS``).
    """

    model_config = ConfigDict(extra="forbid")

    total_tokens: int
    status: str = Field(
        description="'green' | 'yellow' | 'red' — derived from token count vs thresholds"
    )
    blocks: list[PlugSummaryBlockOut]

    @staticmethod
    def compute_status(total_tokens: int) -> str:
        """Return the plug status string for ``total_tokens``.

        Thresholds from ``BEARINGS_ANALYTICS_v1.md`` §8.1 via
        ``config.constants``.  Uses the module-level constants so a
        future settings-override layer can swap them without touching
        this model.
        """
        if total_tokens >= PLUG_RED_THRESHOLD_TOKENS:
            return "red"
        if total_tokens >= PLUG_YELLOW_THRESHOLD_TOKENS:
            return "yellow"
        return "green"


# ---------------------------------------------------------------------------
# Action endpoint shapes (§9.3)
# ---------------------------------------------------------------------------


class SuppressWarningIn(BaseModel):
    """Request body for ``POST /api/analytics/warnings/suppress`` (§9.3)."""

    model_config = ConfigDict(extra="forbid")

    block_hash: str = Field(min_length=64, max_length=64)
    warning_type: str = Field(description=f"One of: {_WARNING_TYPE_VALUES}")


class DraftNewSessionIn(BaseModel):
    """Request body for ``POST /api/analytics/draft-new-session`` (§9.3)."""

    model_config = ConfigDict(extra="forbid")

    source_session_id: str = Field(min_length=1)
    carry_tags: list[str] = Field(default_factory=list)


class DraftNewSessionOut(BaseModel):
    """Response for ``POST /api/analytics/draft-new-session`` (§9.3)."""

    model_config = ConfigDict(extra="forbid")

    draft_plug: str
    estimated_tokens: int
    draft_cost_tokens: dict[str, int]


class SessionFromDraftIn(BaseModel):
    """Request body for ``POST /api/analytics/sessions/from-draft`` (§9.3)."""

    model_config = ConfigDict(extra="forbid")

    draft_plug: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    working_directory: str = Field(min_length=1)


class SessionFromDraftOut(BaseModel):
    """Response for ``POST /api/analytics/sessions/from-draft`` (§9.3)."""

    model_config = ConfigDict(extra="forbid")

    session_id: str


__all__ = [
    "BucketCurrentOut",
    "BucketWindowOut",
    "DraftNewSessionIn",
    "DraftNewSessionOut",
    "PlugBlockIn",
    "PlugBlockOut",
    "PlugBlocksBatchIn",
    "PlugSummaryBlockOut",
    "RedundancyBlockOut",
    "RedundancySessionRef",
    "SessionFromDraftIn",
    "SessionFromDraftOut",
    "SessionPlugSummaryOut",
    "SuppressWarningIn",
    "TagAttributionOut",
    "TurnIn",
]
