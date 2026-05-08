"""Prometheus metrics endpoint — ``GET /metrics``.

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/metrics.py``
exposes the Prometheus scrape surface; rendering lives in
:mod:`bearings.metrics.collector` per arch §1.1.7. The route is
**not** under the ``/api`` prefix — Prometheus convention is
``/metrics`` at the server root, and external scrapers expect that
shape.

Live-state gauges are filled from ``app.state`` immediately before
rendering so the wire response reflects the current runtime. The
counter surfaces (routing decisions, advisor calls) update via the
agent layer at write time, not here.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, Response, status

from bearings.agent.quota import QuotaPoller
from bearings.agent.runner import SessionRunner
from bearings.config.constants import METRICS_CONTENT_TYPE
from bearings.metrics import BearingsMetrics, render_metrics

router = APIRouter()


def _metrics(request: Request) -> BearingsMetrics:
    """Pull the metrics bundle off ``app.state`` (503 if absent)."""
    bundle = getattr(request.app.state, "metrics", None)
    if bundle is None:  # pragma: no cover — set by create_app
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="metrics bundle not configured on app.state",
        )
    if not isinstance(bundle, BearingsMetrics):  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="metrics bundle on app.state is not a BearingsMetrics",
        )
    return bundle


def _runners(request: Request) -> dict[str, SessionRunner]:
    """Extract the runner map from the in-process registry, if any."""
    factory = getattr(request.app.state, "runner_factory", None)
    if factory is None:
        return {}
    inner = getattr(factory, "_runners", None)
    if not isinstance(inner, dict):
        return {}
    return {str(k): v for k, v in inner.items() if isinstance(v, SessionRunner)}


def _refresh_live_gauges(metrics: BearingsMetrics, request: Request) -> None:
    """Populate the live-state gauges from current ``app.state``."""
    state = request.app.state

    # Uptime — monotonic-clock since app construction.
    started = getattr(state, "start_time_monotonic", None)
    if started is not None:
        metrics.uptime_seconds.set(max(0.0, time.monotonic() - float(started)))

    # Active runners + queued prompts (best-effort — empty if the
    # registry is not introspectable, which is the test path).
    runners = _runners(request)
    metrics.active_runners.set(len(runners))
    queued = sum(runner.prompt_queue_depth for runner in runners.values())
    metrics.queued_prompts.set(queued)

    # Active drivers from the registry (None-able; tests inject a
    # fresh registry, production wires it in ``create_app``).
    registry = getattr(state, "auto_driver_registry", None)
    if registry is not None and hasattr(registry, "active_checklists"):
        metrics.active_drivers.set(len(registry.active_checklists()))
    else:  # pragma: no cover — set by create_app
        metrics.active_drivers.set(0)

    # Quota gauges from the latest poller snapshot.
    poller = getattr(state, "quota_poller", None)
    if isinstance(poller, QuotaPoller):
        snap = poller.latest
        if snap is not None:
            if snap.overall_used_pct is not None:
                metrics.quota_overall_used_pct.set(snap.overall_used_pct)
            if snap.sonnet_used_pct is not None:
                metrics.quota_sonnet_used_pct.set(snap.sonnet_used_pct)


@router.get("/metrics", operation_id="get-metrics")
async def get_metrics(request: Request) -> Response:
    """Render Prometheus 0.0.4 text exposition for the active app."""
    bundle = _metrics(request)
    _refresh_live_gauges(bundle, request)
    body = render_metrics(bundle)
    return Response(content=body, media_type=METRICS_CONTENT_TYPE)


__all__ = ["router"]
