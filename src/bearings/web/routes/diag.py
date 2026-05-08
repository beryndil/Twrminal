"""Diagnostic introspection routes (item 1.10).

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/diag.py`` exposes
internal-runtime state for debugging:

* ``GET /api/diag/server`` — version + uptime + pid + db-configured + billing-mode.
* ``GET /api/diag/sessions`` — per-runner snapshot.
* ``GET /api/diag/drivers`` — per-auto-driver-run row.
* ``GET /api/diag/quota`` — quota poller status.

Localhost-only per project ``CLAUDE.md`` ("Bearings is single-user
per project CLAUDE.md") — no auth in v1. The 1.3 audit carry-forward
applies: diag MUST NOT expose checkpoint state via SDK
``enable_file_checkpointing`` primitives — Bearings checkpoints (item
1.3) are the table-fork semantic per arch §5 row 12 and live behind
``web/routes/checkpoints.py``. This module surfaces only runner /
driver-run / quota state.
"""

from __future__ import annotations

import os
import pathlib
import time

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, status

from bearings import __version__
from bearings.agent.diag import (
    collect_drivers,
    collect_quota,
    collect_runners,
    collect_server,
)
from bearings.agent.quota import QuotaPoller
from bearings.agent.runner import SessionRunner
from bearings.config.constants import DEFAULT_BILLING_MODE
from bearings.db import auto_driver_runs as auto_driver_runs_db
from bearings.web.models.diag import (
    DriverDiagListOut,
    DriverDiagOut,
    QuotaDiagOut,
    RunnerDiagListOut,
    RunnerDiagOut,
    ServerDiagOut,
)

router = APIRouter()


def _runners_map(request: Request) -> dict[str, SessionRunner]:
    """Extract the runner map from the registry; ``{}`` if absent."""
    factory = getattr(request.app.state, "runner_factory", None)
    if factory is None:
        return {}
    inner = getattr(factory, "_runners", None)
    if not isinstance(inner, dict):
        return {}
    # Defensive copy so the diag handler does not hold a reference to
    # the registry's mutable inner state across awaits.
    return {str(k): v for k, v in inner.items() if isinstance(v, SessionRunner)}


def _db_optional(request: Request) -> aiosqlite.Connection | None:
    """Pull the optional DB connection (``None`` is tolerated for diag)."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        return None
    return db  # type: ignore[no-any-return]


def _start_time_monotonic(request: Request) -> float:
    """Read the app's monotonic construction time."""
    started = getattr(request.app.state, "start_time_monotonic", None)
    if started is None:  # pragma: no cover — set by create_app
        return time.monotonic()
    return float(started)


def _build_mtime() -> float | None:
    """Return the mtime of ``bearings/__init__.py`` as a Unix timestamp.

    Used as a proxy for the server build time; ``None`` when the path
    cannot be resolved (e.g. namespace packages or editable installs
    whose ``__file__`` is absent).
    """
    import bearings as _pkg

    pkg_file = getattr(_pkg, "__file__", None)
    if pkg_file is None:  # pragma: no cover
        return None
    try:
        return pathlib.Path(pkg_file).stat().st_mtime
    except OSError:  # pragma: no cover
        return None


@router.get("/api/diag/server", response_model=ServerDiagOut, operation_id="get-server-diag")
async def get_server(request: Request) -> ServerDiagOut:
    """Process-level diagnostics."""
    uptime_s = max(0.0, time.monotonic() - _start_time_monotonic(request))
    billing_mode: str = getattr(request.app.state, "billing_mode", DEFAULT_BILLING_MODE)
    diag = collect_server(
        version=__version__,
        uptime_s=uptime_s,
        pid=os.getpid(),
        db_configured=_db_optional(request) is not None,
        billing_mode=billing_mode,
        build_mtime=_build_mtime(),
    )
    return ServerDiagOut(
        version=diag.version,
        uptime_s=diag.uptime_s,
        pid=diag.pid,
        db_configured=diag.db_configured,
        billing_mode=diag.billing_mode,
        build_mtime=diag.build_mtime,
    )


@router.get("/api/diag/sessions", response_model=RunnerDiagListOut, operation_id="get-runner-diag")
async def get_sessions(request: Request) -> RunnerDiagListOut:
    """Per-runner snapshot."""
    runners = _runners_map(request)
    diags = collect_runners(runners)
    return RunnerDiagListOut(
        runners=[
            RunnerDiagOut(
                session_id=d.session_id,
                is_running=d.is_running,
                is_awaiting_user=d.is_awaiting_user,
                queue_length=d.queue_length,
                ring_buffer_size=d.ring_buffer_size,
                subscriber_count=d.subscriber_count,
            )
            for d in diags
        ]
    )


@router.get("/api/diag/drivers", response_model=DriverDiagListOut, operation_id="get-driver-diag")
async def get_drivers(request: Request) -> DriverDiagListOut:
    """Per-auto-driver-run snapshot.

    Reads only ``running`` / ``paused`` rows from ``auto_driver_runs``
    so the wire response reflects active runs (terminal rows live in
    the table for audit but are not "active" diagnostics).
    """
    db = _db_optional(request)
    if db is None:
        # No DB → no driver introspection possible. Return empty.
        return DriverDiagListOut(drivers=[])
    rows = await auto_driver_runs_db.list_active(db)
    diags = collect_drivers(list(rows))
    return DriverDiagListOut(
        drivers=[
            DriverDiagOut(
                checklist_id=d.checklist_id,
                run_id=d.run_id,
                state=d.state,
                current_item_id=d.current_item_id,
                items_completed=d.items_completed,
                items_failed=d.items_failed,
                items_blocked=d.items_blocked,
                items_skipped=d.items_skipped,
                legs_spawned=d.legs_spawned,
            )
            for d in diags
        ]
    )


@router.get("/api/diag/quota", response_model=QuotaDiagOut, operation_id="get-quota-diag")
async def get_quota_diag(request: Request) -> QuotaDiagOut:
    """Quota-poller status."""
    poller = getattr(request.app.state, "quota_poller", None)
    if poller is not None and not isinstance(poller, QuotaPoller):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="quota_poller on app.state is not a QuotaPoller",
        )
    diag = collect_quota(poller)
    return QuotaDiagOut(
        poller_configured=diag.poller_configured,
        has_snapshot=diag.has_snapshot,
        captured_at=diag.captured_at,
        overall_used_pct=diag.overall_used_pct,
        sonnet_used_pct=diag.sonnet_used_pct,
    )


__all__ = ["router"]
