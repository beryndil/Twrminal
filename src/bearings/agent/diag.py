"""Diagnostic introspection helpers.

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/diag.py`` exposes
internal-runtime state for debugging; this agent module owns the
state-collection helpers so the route handler stays under the §40-line
cap. Pure functions (no DB writes, no external I/O) — each one takes
the relevant runtime primitive (runner map, AutoDriverRun row,
quota-poller) and returns a frozen dataclass.

1.3 audit carry-forward
-----------------------

Diag MUST NOT expose checkpoint state via SDK
``enable_file_checkpointing`` primitives. Bearings checkpoints (item
1.3) are the table-fork semantic per arch §5 row 12; they live behind
``web/routes/checkpoints.py``. This module intentionally surfaces only
runner / driver-run / quota state.
"""

from __future__ import annotations

from dataclasses import dataclass

from bearings.agent.quota import QuotaPoller, QuotaSnapshot
from bearings.agent.runner import SessionRunner
from bearings.config.constants import (
    DIAG_DRIVER_SAMPLE_LIMIT,
    DIAG_RUNNER_SAMPLE_LIMIT,
)
from bearings.db.auto_driver_runs import AutoDriverRun


@dataclass(frozen=True)
class ServerDiag:
    """Process-level diagnostics."""

    version: str
    uptime_s: float
    pid: int
    db_configured: bool
    billing_mode: str


@dataclass(frozen=True)
class RunnerDiag:
    """Per-runner diagnostics; one entry per active session runner."""

    session_id: str
    is_running: bool
    is_awaiting_user: bool
    queue_length: int
    ring_buffer_size: int
    subscriber_count: int


@dataclass(frozen=True)
class DriverDiag:
    """Per-auto-driver-run diagnostics; one entry per active run row."""

    checklist_id: str
    run_id: int
    state: str
    current_item_id: int | None
    items_completed: int
    items_failed: int
    items_blocked: int
    items_skipped: int
    legs_spawned: int


@dataclass(frozen=True)
class QuotaDiag:
    """Quota poller status."""

    poller_configured: bool
    has_snapshot: bool
    captured_at: int | None
    overall_used_pct: float | None
    sonnet_used_pct: float | None


def collect_server(
    *,
    version: str,
    uptime_s: float,
    pid: int,
    db_configured: bool,
    billing_mode: str,
) -> ServerDiag:
    """Assemble the :class:`ServerDiag` snapshot from primitives."""
    return ServerDiag(
        version=version,
        uptime_s=uptime_s,
        pid=pid,
        db_configured=db_configured,
        billing_mode=billing_mode,
    )


def collect_runners(runners: dict[str, SessionRunner]) -> list[RunnerDiag]:
    """Collect per-runner diagnostics from a session-id→runner map.

    Accepts a plain mapping rather than the concrete in-process
    registry so this module stays in the agent layer (arch §3 — no
    upward import to ``bearings.web``). The route layer extracts the
    map from the registry it knows about and passes it in.
    """
    out: list[RunnerDiag] = []
    # Sorted for deterministic wire-shape ordering.
    for session_id in sorted(runners.keys())[:DIAG_RUNNER_SAMPLE_LIMIT]:
        runner = runners[session_id]
        status = runner.status
        out.append(
            RunnerDiag(
                session_id=session_id,
                is_running=status.is_running,
                is_awaiting_user=status.is_awaiting_user,
                queue_length=runner.prompt_queue_depth,
                ring_buffer_size=runner.ring_buffer_size,
                subscriber_count=runner.subscriber_count,
            )
        )
    return out


def collect_drivers(runs: list[AutoDriverRun]) -> list[DriverDiag]:
    """Project a list of :class:`AutoDriverRun` rows into wire shape.

    The route layer reads the durable run rows from
    :mod:`bearings.db.auto_driver_runs` and passes them in; this
    helper stays sync + IO-free per the §40-line cap.
    """
    out: list[DriverDiag] = []
    for row in runs[:DIAG_DRIVER_SAMPLE_LIMIT]:
        out.append(
            DriverDiag(
                checklist_id=row.checklist_id,
                run_id=row.id,
                state=row.state,
                current_item_id=row.current_item_id,
                items_completed=row.items_completed,
                items_failed=row.items_failed,
                items_blocked=row.items_blocked,
                items_skipped=row.items_skipped,
                legs_spawned=row.legs_spawned,
            )
        )
    return out


def collect_quota(poller: QuotaPoller | None) -> QuotaDiag:
    """Collect quota-poller diagnostics."""
    if poller is None:
        return QuotaDiag(
            poller_configured=False,
            has_snapshot=False,
            captured_at=None,
            overall_used_pct=None,
            sonnet_used_pct=None,
        )
    snap: QuotaSnapshot | None = poller.latest
    if snap is None:
        return QuotaDiag(
            poller_configured=True,
            has_snapshot=False,
            captured_at=None,
            overall_used_pct=None,
            sonnet_used_pct=None,
        )
    return QuotaDiag(
        poller_configured=True,
        has_snapshot=True,
        captured_at=snap.captured_at,
        overall_used_pct=snap.overall_used_pct,
        sonnet_used_pct=snap.sonnet_used_pct,
    )


__all__ = [
    "DriverDiag",
    "QuotaDiag",
    "RunnerDiag",
    "ServerDiag",
    "collect_drivers",
    "collect_quota",
    "collect_runners",
    "collect_server",
]
