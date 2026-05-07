"""Health endpoint — ``GET /api/health``.

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/health.py`` is
the readiness/liveness endpoint. Behavior docs are silent on the
shape; see ``src/bearings/config/constants.py`` §"Health" for the
decided-and-documented contract:

* HTTP status is always 200 when the server is alive (per the
  systemd / external-monitor convention).
* The JSON ``status`` field carries the deeper readiness signal —
  ``ok`` when the DB probe succeeds, ``degraded`` otherwise.
"""

from __future__ import annotations

import time

import aiosqlite
from fastapi import APIRouter, Request

from bearings import __version__
from bearings.agent.health import build_health
from bearings.web.models.health import HealthOut

router = APIRouter()


def _db(request: Request) -> aiosqlite.Connection | None:
    """Pull the optional DB connection off ``app.state`` (None tolerated)."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        return None
    return db  # type: ignore[no-any-return]


def _start_time(request: Request) -> float:
    """Read the app's wall-clock construction time from ``app.state``.

    ``create_app`` writes :func:`time.monotonic` at construction so
    the uptime calculation is monotonic-safe (system-clock jumps do
    not fold the uptime negative).
    """
    started = getattr(request.app.state, "start_time_monotonic", None)
    if started is None:  # pragma: no cover — set by create_app
        return time.monotonic()
    return float(started)


def _data_dir(request: Request) -> str:
    """Read the resolved data-directory path from ``app.state`` (empty string when absent)."""
    return str(getattr(request.app.state, "data_dir", "") or "")


@router.get("/api/health", response_model=HealthOut)
async def get_health(request: Request) -> HealthOut:
    """Return the health snapshot — 200 always; readiness in body."""
    db = _db(request)
    uptime_s = max(0.0, time.monotonic() - _start_time(request))
    snapshot = await build_health(
        db_connection=db,
        version=__version__,
        uptime_s=uptime_s,
        data_dir=_data_dir(request),
    )
    return HealthOut(
        status=snapshot.status,
        version=snapshot.version,
        uptime_s=snapshot.uptime_s,
        db_ok=snapshot.db_ok,
        data_dir=snapshot.data_dir,
    )


__all__ = ["router"]
