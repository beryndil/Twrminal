"""Quota endpoints (spec §9 quota surface).

Endpoints (spec §9 verbatim):

* ``GET  /api/quota/current``  — latest quota snapshot.
* ``POST /api/quota/refresh``  — force-refresh from ``/usage``.
* ``GET  /api/quota/history?days=30`` — for the headroom chart.

Per arch §1.1.5 the route handlers stay thin; the quota domain code
(:class:`bearings.agent.quota.QuotaPoller`,
:func:`bearings.agent.quota.load_latest` /
:func:`bearings.agent.quota.load_history`) does the work.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from bearings.agent.quota import (
    QuotaSnapshot,
    load_history,
    load_latest,
)
from bearings.config.constants import USAGE_HEADROOM_WINDOW_DAYS
from bearings.web.models.errors import DetailError
from bearings.web.models.quota import QuotaSnapshotOut
from bearings.web.routes._deps import _db, _quota_poller

router = APIRouter()


def _to_out(snapshot: QuotaSnapshot) -> QuotaSnapshotOut:
    return QuotaSnapshotOut(
        captured_at=snapshot.captured_at,
        overall_used_pct=snapshot.overall_used_pct,
        sonnet_used_pct=snapshot.sonnet_used_pct,
        overall_resets_at=snapshot.overall_resets_at,
        sonnet_resets_at=snapshot.sonnet_resets_at,
        raw_payload=snapshot.raw_payload,
    )


@router.get(
    "/api/quota/current",
    response_model=QuotaSnapshotOut,
    responses={404: {"model": DetailError, "description": "No quota snapshot recorded yet."}},
    operation_id="get-quota-current",
)
async def get_current(request: Request) -> QuotaSnapshotOut:
    """Most recent quota snapshot; 404 if the poller has never succeeded.

    The poller's in-memory ``latest`` is preferred; the DB fallback
    catches the case where the poller hasn't been started in this
    process (e.g. a test app, or a fresh restart before the first
    refresh tick).
    """
    poller = _quota_poller(request)
    if poller is not None and poller.latest is not None:
        return _to_out(poller.latest)
    db = _db(request)
    snapshot = await load_latest(db)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no quota snapshot recorded yet",
        )
    return _to_out(snapshot)


@router.post(
    "/api/quota/refresh",
    response_model=QuotaSnapshotOut,
    operation_id="refresh-quota",
)
async def refresh(request: Request) -> QuotaSnapshotOut:
    """Force one immediate poll; 502 if the upstream is unreachable.

    The endpoint requires a configured poller (the fetcher is
    poller-owned). 503 when no poller is on ``app.state`` — this is
    distinct from the 502-on-fetcher-failure case which means the
    poller exists but couldn't reach upstream.
    """
    poller = _quota_poller(request)
    if poller is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="quota_poller not configured on app.state",
        )
    snapshot = await poller.refresh()
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="upstream /usage poll failed",
        )
    return _to_out(snapshot)


@router.get(
    "/api/quota/history",
    response_model=list[QuotaSnapshotOut],
    operation_id="get-quota-history",
)
async def get_history(
    request: Request,
    days: int = Query(
        default=USAGE_HEADROOM_WINDOW_DAYS,
        gt=0,
        le=365,
        description="rolling window in days (1-365)",
    ),
) -> list[QuotaSnapshotOut]:
    """Snapshots within ``days`` calendar days, oldest-first."""
    db = _db(request)
    rows = await load_history(db, days=days)
    return [_to_out(r) for r in rows]


__all__ = ["router"]
