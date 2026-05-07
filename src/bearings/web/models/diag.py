# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/diag.py`` (item 1.10)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ServerDiagOut(BaseModel):
    """Response shape for ``GET /api/diag/server``."""

    model_config = ConfigDict(extra="forbid")

    version: str
    uptime_s: float
    pid: int
    db_configured: bool
    billing_mode: str


class RunnerDiagOut(BaseModel):
    """One entry in ``GET /api/diag/sessions``."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    is_running: bool
    is_awaiting_user: bool
    queue_length: int
    ring_buffer_size: int
    subscriber_count: int


class RunnerDiagListOut(BaseModel):
    """Response shape for ``GET /api/diag/sessions``."""

    model_config = ConfigDict(extra="forbid")

    runners: list[RunnerDiagOut]


class DriverDiagOut(BaseModel):
    """One entry in ``GET /api/diag/drivers``."""

    model_config = ConfigDict(extra="forbid")

    checklist_id: str
    run_id: int
    state: str
    current_item_id: int | None
    items_completed: int
    items_failed: int
    items_blocked: int
    items_skipped: int
    legs_spawned: int


class DriverDiagListOut(BaseModel):
    """Response shape for ``GET /api/diag/drivers``."""

    model_config = ConfigDict(extra="forbid")

    drivers: list[DriverDiagOut]


class QuotaDiagOut(BaseModel):
    """Response shape for ``GET /api/diag/quota``."""

    model_config = ConfigDict(extra="forbid")

    poller_configured: bool
    has_snapshot: bool
    captured_at: int | None
    overall_used_pct: float | None
    sonnet_used_pct: float | None


__all__ = [
    "DriverDiagListOut",
    "DriverDiagOut",
    "QuotaDiagOut",
    "RunnerDiagListOut",
    "RunnerDiagOut",
    "ServerDiagOut",
]
