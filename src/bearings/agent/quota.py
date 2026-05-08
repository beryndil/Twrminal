"""Quota poller + ``apply_quota_guard`` — spec §4.

Per ``docs/architecture-v1.md`` §1.1.4 + §4.3 this module owns:

* :class:`QuotaSnapshot` — the frozen carrier mirroring a row of the
  ``quota_snapshots`` table (spec §4 schema verbatim).
* :func:`apply_quota_guard` — pure function consumed by
  :mod:`bearings.agent.session_assembly` and the
  ``/api/routing/preview`` endpoint to fold quota-aware downgrades on
  top of an existing :class:`bearings.agent.routing.RoutingDecision`.
* :func:`record_snapshot`, :func:`load_latest`,
  :func:`load_history` — DB read/write helpers for the
  ``quota_snapshots`` table. Colocated rather than under
  :mod:`bearings.db` because the quota poller is the only writer and
  the guard the only reader; cohesion outweighs the DB/agent split for
  this single-table surface.
* :class:`QuotaPoller` — async background task that polls the
  Anthropic ``/v1/usage`` (or local Claude Code ``/usage``) endpoint
  on a fixed cadence, persists a snapshot, and reports the latest
  shape via :meth:`QuotaPoller.latest`.

Design notes:

* The guard's downgrade ladder is decided-and-documented as
  spec-verbatim. Spec §4 reads:
  - ``overall_used_pct >= 0.80`` → executor=opus → sonnet,
    advisor=opus → None.
  - ``sonnet_used_pct >= 0.80 and executor == 'sonnet'`` →
    executor → haiku, keep advisor.
* ``apply_quota_guard`` is a pure function; the snapshot it consumes
  is the latest cached row, **not** a fresh poll, per spec §13 risk
  #3 ("5-minute polls mean the guard can be up to 5 minutes stale").
* :class:`QuotaSnapshot` permits ``None`` for both percentage fields
  per arch §4.3 — when the upstream ``/usage`` endpoint is
  unreachable we still persist a row carrying the ``raw_payload``
  for forward compatibility, so the guard sees the latest *attempt*
  rather than a silently fallthrough-to-no-guard state.
* :class:`QuotaPoller` accepts a fetcher callable so tests can
  inject deterministic snapshots without monkey-patching network I/O.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

import aiosqlite

from bearings.agent.routing import RoutingDecision
from bearings.config.constants import (
    DEFAULT_ADVISOR_MAX_USES_HAIKU,
    DEFAULT_ADVISOR_MAX_USES_SONNET,
    QUOTA_THRESHOLD_PCT,
    USAGE_POLL_INTERVAL_S,
)


@dataclass(frozen=True)
class QuotaSnapshot:
    """Spec §4 ``quota_snapshots`` row mirror.

    Field semantics:

    * ``captured_at`` — unix-seconds timestamp of the poll.
    * ``overall_used_pct`` / ``sonnet_used_pct`` — 0.0-1.0 floats, or
      ``None`` when the upstream endpoint did not report the bucket
      (e.g. plan upgrade in progress, transient 502, …). The guard
      treats ``None`` as "no information" — no downgrade, but also no
      fall-through to a stale-but-known prior snapshot.
    * ``overall_resets_at`` / ``sonnet_resets_at`` — unix-seconds when
      the bucket resets to 0; surfaced in the header tooltip per spec
      §4 "Hover: reset time".
    * ``raw_payload`` — JSON string carrying the full upstream payload
      so a future schema change (e.g. addition of a third bucket)
      lands as a one-line read change.
    """

    captured_at: int
    overall_used_pct: float | None
    sonnet_used_pct: float | None
    overall_resets_at: int | None
    sonnet_resets_at: int | None
    raw_payload: str

    def __post_init__(self) -> None:
        if self.captured_at < 0:
            raise ValueError(f"QuotaSnapshot.captured_at must be ≥ 0 (got {self.captured_at})")
        if self.overall_used_pct is not None and not 0.0 <= self.overall_used_pct <= 1.0:
            raise ValueError(
                f"QuotaSnapshot.overall_used_pct must be in [0.0, 1.0] "
                f"(got {self.overall_used_pct})"
            )
        if self.sonnet_used_pct is not None and not 0.0 <= self.sonnet_used_pct <= 1.0:
            raise ValueError(
                f"QuotaSnapshot.sonnet_used_pct must be in [0.0, 1.0] (got {self.sonnet_used_pct})"
            )

    def quota_state_dict(self) -> dict[str, float]:
        """Spec §App A ``RoutingDecision.quota_state_at_decision`` shape.

        Returns a dict with the two percentage keys, defaulting to
        ``0.0`` when the underlying field is ``None`` so consumers
        (analytics, the per-message persistence path) read a uniform
        type. The semantic of ``None`` ("no info") is lost in this
        projection; consumers needing it should inspect the snapshot
        directly via :func:`load_latest`.
        """
        return {
            "overall_used_pct": self.overall_used_pct if self.overall_used_pct is not None else 0.0,
            "sonnet_used_pct": self.sonnet_used_pct if self.sonnet_used_pct is not None else 0.0,
        }


# ---------------------------------------------------------------------------
# Pure guard function
# ---------------------------------------------------------------------------


def _threshold_tripped(pct: float | None) -> bool:
    """Return True when a quota percentage has hit the downgrade threshold."""
    return pct is not None and pct >= QUOTA_THRESHOLD_PCT


def _apply_sonnet_downgrade(
    executor: str,
    advisor: str | None,
    advisor_max_uses: int,
    sonnet_pct: float,
) -> tuple[str, str | None, int, str, str]:
    """Apply spec §4 step-2 sonnet-bucket downgrade; return updated fields."""
    pct_int = round(sonnet_pct * 100)
    return (
        "haiku",
        advisor,
        DEFAULT_ADVISOR_MAX_USES_HAIKU if advisor is not None else 0,
        "quota_downgrade",
        f"quota guard: sonnet used {pct_int}% — Sonnet → Haiku",
    )


def _apply_overall_downgrade(
    executor: str,
    advisor: str | None,
    advisor_max_uses: int,
    source: str,
    reason: str,
    pct_int: int,
) -> tuple[str, str | None, int, str, str]:
    """Apply spec §4 step-1 overall-bucket downgrades; return updated fields."""
    new_executor = executor
    new_advisor = advisor
    new_advisor_max_uses = advisor_max_uses
    new_source = source
    new_reason = reason

    if new_executor in {"opus", "opusplan"}:
        new_executor = "sonnet"
        new_advisor_max_uses = DEFAULT_ADVISOR_MAX_USES_SONNET
        new_source = "quota_downgrade"
        new_reason = f"quota guard: overall used {pct_int}% — Opus → Sonnet"

    if new_advisor == "opus":
        new_advisor = None
        if new_source != "quota_downgrade":
            new_source = "quota_downgrade"
            new_reason = f"quota guard: overall used {pct_int}% — advisor disabled"

    return new_executor, new_advisor, new_advisor_max_uses, new_source, new_reason


def apply_quota_guard(
    decision: RoutingDecision,
    snapshot: QuotaSnapshot | None,
) -> RoutingDecision:
    """Spec §4 quota guard — fold quota-aware downgrades on top of ``decision``.

    Algorithm (spec §4 verbatim):

    1. If ``overall_used_pct >= 0.80`` (the
       :data:`bearings.config.constants.QUOTA_THRESHOLD_PCT` constant):
       - If ``executor in {'opus', 'opusplan'}`` → executor → ``'sonnet'``.
       - If ``advisor == 'opus'`` → advisor → ``None`` (advisor disabled).
       - Mark ``source = 'quota_downgrade'``.
    2. If ``sonnet_used_pct >= 0.80`` and the *post-step-1* executor is
       ``'sonnet'`` → executor → ``'haiku'``. Advisor is preserved
       (advisor uses the overall bucket per spec §4 "keep advisor —
       advisor uses overall bucket, not Sonnet bucket").

    The snapshot's ``quota_state_at_decision`` is folded onto the
    returned decision so downstream analytics see the full state
    regardless of whether the guard fired.

    Returns the original ``decision`` unchanged when:

    * ``snapshot is None`` (no quota info — fail open per spec §4),
    * neither bucket trips its threshold,
    * the decision is already at the floor (executor already ``'haiku'``,
      advisor already ``None``).

    The downgrade ``reason`` carries a percentage for the routing
    badge tooltip (spec §6 yellow banner: "Routing downgraded to
    Sonnet (overall quota at 81%). [Use Opus anyway]").
    """
    if snapshot is None:
        return decision

    overall = snapshot.overall_used_pct
    sonnet = snapshot.sonnet_used_pct
    new_state = snapshot.quota_state_dict()

    new_executor, new_advisor, new_advisor_max_uses, new_source, new_reason = (
        decision.executor_model,
        decision.advisor_model,
        decision.advisor_max_uses,
        decision.source,
        decision.reason,
    )

    # Step 1: overall-bucket downgrades.
    if _threshold_tripped(overall):
        new_executor, new_advisor, new_advisor_max_uses, new_source, new_reason = (
            _apply_overall_downgrade(
                new_executor,
                new_advisor,
                new_advisor_max_uses,
                new_source,
                new_reason,
                round((overall or 0.0) * 100),
            )
        )

    # Step 2: sonnet-bucket downgrade (runs after step 1).
    if _threshold_tripped(sonnet) and new_executor == "sonnet":
        new_executor, new_advisor, new_advisor_max_uses, new_source, new_reason = (
            _apply_sonnet_downgrade(new_executor, new_advisor, new_advisor_max_uses, sonnet or 0.0)
        )

    if new_executor == decision.executor_model and new_advisor == decision.advisor_model:
        if decision.quota_state_at_decision == new_state:
            return decision
        return replace(decision, quota_state_at_decision=new_state)

    return replace(
        decision,
        executor_model=new_executor,
        advisor_model=new_advisor,
        advisor_max_uses=new_advisor_max_uses,
        source=new_source,
        reason=new_reason,
        quota_state_at_decision=new_state,
    )


# ---------------------------------------------------------------------------
# DB read/write — colocated; see module docstring rationale.
# ---------------------------------------------------------------------------


_SNAPSHOT_COLUMNS = (
    "SELECT captured_at, overall_used_pct, sonnet_used_pct, "
    "overall_resets_at, sonnet_resets_at, raw_payload FROM quota_snapshots"
)


def _row_to_snapshot(row: aiosqlite.Row | tuple[object, ...]) -> QuotaSnapshot:
    return QuotaSnapshot(
        captured_at=int(str(row[0])),
        overall_used_pct=None if row[1] is None else float(str(row[1])),
        sonnet_used_pct=None if row[2] is None else float(str(row[2])),
        overall_resets_at=None if row[3] is None else int(str(row[3])),
        sonnet_resets_at=None if row[4] is None else int(str(row[4])),
        raw_payload=str(row[5] or "{}"),
    )


async def record_snapshot(
    connection: aiosqlite.Connection,
    snapshot: QuotaSnapshot,
) -> None:
    """Persist a snapshot row. INSERT-only; never updates.

    The most recent row wins per spec §4 "The most recent snapshot is
    read by the quota guard during routing"; older rows feed the
    headroom 7-day chart per spec §10.
    """
    cursor = await connection.execute(
        "INSERT INTO quota_snapshots ("
        "captured_at, overall_used_pct, sonnet_used_pct, "
        "overall_resets_at, sonnet_resets_at, raw_payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            snapshot.captured_at,
            snapshot.overall_used_pct,
            snapshot.sonnet_used_pct,
            snapshot.overall_resets_at,
            snapshot.sonnet_resets_at,
            snapshot.raw_payload,
        ),
    )
    await cursor.close()
    await connection.commit()


async def load_latest(
    connection: aiosqlite.Connection,
) -> QuotaSnapshot | None:
    """Most recent snapshot or ``None`` if the table is empty."""
    cursor = await connection.execute(
        _SNAPSHOT_COLUMNS + " ORDER BY captured_at DESC LIMIT 1",
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return None if row is None else _row_to_snapshot(row)


async def load_history(
    connection: aiosqlite.Connection,
    *,
    days: int,
) -> list[QuotaSnapshot]:
    """Snapshots within the last ``days`` calendar days, oldest-first.

    The headroom chart (spec §10) renders oldest-on-left, newest-on-
    right, so the query orders ASC. The cutoff uses unix-seconds:
    ``now - days * 86400``.
    """
    if days <= 0:
        raise ValueError(f"load_history.days must be > 0 (got {days})")
    cutoff = int(time.time()) - days * 86_400
    cursor = await connection.execute(
        _SNAPSHOT_COLUMNS + " WHERE captured_at >= ? ORDER BY captured_at ASC",
        (cutoff,),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_snapshot(row) for row in rows]


# ---------------------------------------------------------------------------
# Background poller — the only impure piece of this module.
# ---------------------------------------------------------------------------


# Caller-provided fetcher returning a snapshot. Tests inject a static
# response; production wires a fetcher that calls Claude Code's local
# ``/usage`` endpoint or the Anthropic API.
QuotaFetcher = Callable[[], Awaitable[QuotaSnapshot]]


class QuotaPoller:
    """Background task polling ``/usage`` on a fixed cadence (spec §4).

    Lifecycle:

    * :meth:`start` — schedules the poll loop on the running event
      loop. Idempotent — re-invocation while already running is a
      no-op.
    * :meth:`refresh` — force one immediate poll, persist the
      snapshot, and update :attr:`latest`. Used by the
      ``POST /api/quota/refresh`` endpoint per spec §9.
    * :meth:`stop` — cancel the background loop. Idempotent. Used by
      the FastAPI lifespan shutdown event and by tests.
    * :meth:`latest` — last snapshot the poller successfully read,
      or ``None`` until the first poll completes.

    Errors raised by the fetcher are swallowed by the loop and logged
    via :func:`print` (so test runs surface them) — a poll failure
    must not crash the app, and the staleness is bounded to
    :data:`bearings.config.constants.USAGE_POLL_INTERVAL_S` per spec
    §13 risk #3.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        fetcher: QuotaFetcher,
        *,
        interval_s: float = float(USAGE_POLL_INTERVAL_S),
    ) -> None:
        if interval_s <= 0:
            raise ValueError(f"QuotaPoller.interval_s must be > 0 (got {interval_s})")
        self._connection = connection
        self._fetcher = fetcher
        self._interval_s = interval_s
        self._task: asyncio.Task[None] | None = None
        self._latest: QuotaSnapshot | None = None
        self._lock = asyncio.Lock()

    @property
    def latest(self) -> QuotaSnapshot | None:
        """Most recent snapshot the poller has read, or ``None``."""
        return self._latest

    def start(self) -> None:
        """Schedule the poll loop. No-op if already running."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="quota-poller")

    async def stop(self) -> None:
        """Cancel the poll loop and await its exit. Idempotent."""
        task = self._task
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self._task = None

    async def refresh(self) -> QuotaSnapshot | None:
        """Force one immediate poll. Returns the new snapshot or ``None`` on failure.

        The lock prevents two concurrent ``refresh`` calls (one from
        the loop, one from the API endpoint) from racing the
        ``record_snapshot`` write. Errors are surfaced — the
        ``POST /api/quota/refresh`` route translates a ``None`` return
        to a 502 so the caller sees the upstream failure.
        """
        async with self._lock:
            try:
                snapshot = await self._fetcher()
            except (RuntimeError, ValueError, ConnectionError, TimeoutError) as exc:
                # Bounded exception alphabet — fetcher contract
                # restricts what it raises; we don't catch
                # ``BaseException`` because that would mask
                # ``KeyboardInterrupt`` / ``SystemExit``.
                print(f"quota refresh failed: {exc}")
                return None
            await record_snapshot(self._connection, snapshot)
            self._latest = snapshot
            return snapshot

    async def _loop(self) -> None:
        """The poll loop body. Runs until cancelled."""
        # First poll fires immediately so the app comes up with a
        # snapshot rather than waiting one full interval. Subsequent
        # polls space at ``interval_s``.
        await self.refresh()
        while True:
            try:
                await asyncio.sleep(self._interval_s)
            except asyncio.CancelledError:  # pragma: no cover — exit path
                raise
            await self.refresh()


def make_static_fetcher(snapshot: QuotaSnapshot) -> QuotaFetcher:
    """Test helper: a fetcher that always returns the supplied snapshot.

    The frontend item 2.4's preview-banner integration tests inject
    one of these so a deterministic quota state drives the
    downgrade-banner rendering. The factory exists here (rather than
    inline in the test fixture) so the production fetcher type and
    the test fetcher type are the same Protocol — drift between them
    fails type-check at the call site.
    """

    async def _fetch() -> QuotaSnapshot:
        return snapshot

    return _fetch


def empty_snapshot(captured_at: int | None = None) -> QuotaSnapshot:
    """Return a "no info" snapshot — both buckets ``None``.

    Used by :class:`QuotaPoller` when the fetcher reports the
    upstream endpoint unreachable but the bookkeeping wants a row
    persisted (so the chart shows a gap rather than a missing
    sample). Also handy for tests asserting the guard's
    ``snapshot is None`` fall-open behaviour without constructing a
    full literal.
    """
    return QuotaSnapshot(
        captured_at=int(time.time()) if captured_at is None else captured_at,
        overall_used_pct=None,
        sonnet_used_pct=None,
        overall_resets_at=None,
        sonnet_resets_at=None,
        raw_payload=json.dumps({"empty": True}),
    )


__all__ = [
    "QuotaFetcher",
    "QuotaPoller",
    "QuotaSnapshot",
    "apply_quota_guard",
    "empty_snapshot",
    "load_history",
    "load_latest",
    "make_static_fetcher",
    "record_snapshot",
]
