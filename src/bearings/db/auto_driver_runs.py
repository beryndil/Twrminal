"""``auto_driver_runs`` table queries — durable mirror of the auto-driver state.

Per ``docs/architecture-v1.md`` §1.1.3 (table inventory) and §1.1.4
(``Driver`` class lives in ``agent/auto_driver.py``), the in-memory
state machine on the agent side has a durable mirror here so that a
server restart can rehydrate a still-running driver per
``docs/behavior/checklists.md`` §"When the user starts / pauses / stops
a run" — "If the server restarts mid-run, the run is rehydrated on
next boot".

Public surface:

* :class:`AutoDriverRun` — frozen row mirror with validation.
* :func:`create` — insert a fresh run row in the requested initial
  state (typically ``running`` from a Start request).
* :func:`get`, :func:`get_active`, :func:`list_for_checklist` — reads.
* :func:`update_state` — transition between
  :data:`bearings.config.constants.KNOWN_AUTO_DRIVER_STATES`.
* :func:`update_counters` — bump the live counters the status line
  surfaces (items_completed / items_failed / items_blocked /
  items_skipped / legs_spawned / items_attempted / current_item_id).
* :func:`finalize` — terminal stamp (state ∈ {finished, errored},
  outcome string, finished_at).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import aiosqlite

from bearings.config.constants import (
    AUTO_DRIVER_FAILURE_POLICY_HALT,
    AUTO_DRIVER_STATE_ERRORED,
    AUTO_DRIVER_STATE_FINISHED,
    AUTO_DRIVER_STATE_IDLE,
    AUTO_DRIVER_STATE_PAUSED,
    AUTO_DRIVER_STATE_RUNNING,
    KNOWN_AUTO_DRIVER_FAILURE_POLICIES,
    KNOWN_AUTO_DRIVER_STATES,
)
from bearings.db._id import now_iso

# State transition table — keyed by current state, value is the set of
# permitted next states. Mirrors the user-observable state machine:
# idle → running (Start). running → paused / finished / errored.
# paused → running (resume) / finished. finished/errored are terminal.
# A self-loop (running → running) is permitted so the counter-update
# path can refresh updated_at without a state change.
_TRANSITIONS: dict[str, frozenset[str]] = {
    AUTO_DRIVER_STATE_IDLE: frozenset({AUTO_DRIVER_STATE_RUNNING}),
    AUTO_DRIVER_STATE_RUNNING: frozenset(
        {
            AUTO_DRIVER_STATE_RUNNING,
            AUTO_DRIVER_STATE_PAUSED,
            AUTO_DRIVER_STATE_FINISHED,
            AUTO_DRIVER_STATE_ERRORED,
        }
    ),
    AUTO_DRIVER_STATE_PAUSED: frozenset(
        {
            AUTO_DRIVER_STATE_PAUSED,
            AUTO_DRIVER_STATE_RUNNING,
            AUTO_DRIVER_STATE_FINISHED,
        }
    ),
    AUTO_DRIVER_STATE_FINISHED: frozenset(),
    AUTO_DRIVER_STATE_ERRORED: frozenset(),
}


@dataclass(frozen=True)
class AutoDriverRun:
    """Row mirror for the ``auto_driver_runs`` table.

    Every counter starts at 0 on a fresh run; ``current_item_id`` is
    ``None`` until the driver picks the first item. ``outcome`` /
    ``outcome_reason`` / ``finished_at`` are NULL while the run is
    still running or paused.
    """

    id: int
    checklist_id: str
    state: str
    failure_policy: str
    visit_existing: bool
    items_completed: int
    items_failed: int
    items_blocked: int
    items_skipped: int
    items_attempted: int
    legs_spawned: int
    current_item_id: int | None
    outcome: str | None
    outcome_reason: str | None
    started_at: str
    updated_at: str
    finished_at: str | None

    def __post_init__(self) -> None:
        if not self.checklist_id:
            raise ValueError("AutoDriverRun.checklist_id must be non-empty")
        if self.state not in KNOWN_AUTO_DRIVER_STATES:
            raise ValueError(
                f"AutoDriverRun.state {self.state!r} not in {sorted(KNOWN_AUTO_DRIVER_STATES)}"
            )
        if self.failure_policy not in KNOWN_AUTO_DRIVER_FAILURE_POLICIES:
            raise ValueError(
                f"AutoDriverRun.failure_policy {self.failure_policy!r} not in "
                f"{sorted(KNOWN_AUTO_DRIVER_FAILURE_POLICIES)}"
            )
        for name, value in (
            ("items_completed", self.items_completed),
            ("items_failed", self.items_failed),
            ("items_blocked", self.items_blocked),
            ("items_skipped", self.items_skipped),
            ("items_attempted", self.items_attempted),
            ("legs_spawned", self.legs_spawned),
        ):
            if value < 0:
                raise ValueError(f"AutoDriverRun.{name} must be ≥ 0 (got {value})")


def can_transition(current: str, target: str) -> bool:
    """Return ``True`` iff ``current`` → ``target`` is a permitted edge.

    Pure helper exposed for the agent-side ``Driver`` class so it can
    pre-validate a transition before issuing the DB write. The DB write
    in :func:`update_state` re-validates so a buggy caller still fails
    safely.
    """
    if current not in KNOWN_AUTO_DRIVER_STATES:
        return False
    if target not in KNOWN_AUTO_DRIVER_STATES:
        return False
    return target in _TRANSITIONS.get(current, frozenset())


async def create(
    connection: aiosqlite.Connection,
    *,
    checklist_id: str,
    failure_policy: str = AUTO_DRIVER_FAILURE_POLICY_HALT,
    visit_existing: bool = False,
    initial_state: str = AUTO_DRIVER_STATE_RUNNING,
) -> AutoDriverRun:
    """Insert a fresh ``auto_driver_runs`` row.

    Default ``initial_state`` is ``running`` because the canonical
    create-call path is "user pressed Start" (per behavior/checklists.md
    §"Run-control surface" the Start control transitions the driver
    out of idle); tests sometimes want ``idle`` to exercise the
    state machine pre-Start, hence the keyword override.
    """
    if initial_state not in KNOWN_AUTO_DRIVER_STATES:
        raise ValueError(
            f"create: initial_state {initial_state!r} not in {sorted(KNOWN_AUTO_DRIVER_STATES)}"
        )
    if failure_policy not in KNOWN_AUTO_DRIVER_FAILURE_POLICIES:
        raise ValueError(
            f"create: failure_policy {failure_policy!r} not in "
            f"{sorted(KNOWN_AUTO_DRIVER_FAILURE_POLICIES)}"
        )
    timestamp = now_iso()
    cursor = await connection.execute(
        "INSERT INTO auto_driver_runs "
        "(checklist_id, state, failure_policy, visit_existing, started_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            checklist_id,
            initial_state,
            failure_policy,
            1 if visit_existing else 0,
            timestamp,
            timestamp,
        ),
    )
    new_id = cursor.lastrowid
    await cursor.close()
    await connection.commit()
    if new_id is None:  # pragma: no cover
        raise RuntimeError("auto_driver_runs.create: aiosqlite returned a None lastrowid")
    return AutoDriverRun(
        id=int(new_id),
        checklist_id=checklist_id,
        state=initial_state,
        failure_policy=failure_policy,
        visit_existing=visit_existing,
        items_completed=0,
        items_failed=0,
        items_blocked=0,
        items_skipped=0,
        items_attempted=0,
        legs_spawned=0,
        current_item_id=None,
        outcome=None,
        outcome_reason=None,
        started_at=timestamp,
        updated_at=timestamp,
        finished_at=None,
    )


async def get(connection: aiosqlite.Connection, run_id: int) -> AutoDriverRun | None:
    """Fetch a run by id; ``None`` if absent."""
    cursor = await connection.execute(
        _SELECT_RUN_COLUMNS + " WHERE id = ?",
        (run_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return None if row is None else _row_to_run(row)


async def get_active(
    connection: aiosqlite.Connection,
    checklist_id: str,
) -> AutoDriverRun | None:
    """Most recent ``running`` or ``paused`` run for ``checklist_id``.

    The user observes "the run resumes" rather than "two runs in
    parallel" — only one active run per checklist at a time. The query
    orders by ``started_at DESC`` so a still-running row beats an older
    paused one if the schema somehow holds both (shouldn't, but the
    ordering is defensive).
    """
    cursor = await connection.execute(
        _SELECT_RUN_COLUMNS
        + " WHERE checklist_id = ? AND state IN (?, ?) ORDER BY started_at DESC LIMIT 1",
        (checklist_id, AUTO_DRIVER_STATE_RUNNING, AUTO_DRIVER_STATE_PAUSED),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return None if row is None else _row_to_run(row)


async def list_active(
    connection: aiosqlite.Connection,
) -> list[AutoDriverRun]:
    """Every ``running`` / ``paused`` run, newest-first.

    Item 1.10 diag surface — exposes the full active-driver fleet
    without taking a per-checklist round trip. The partial index
    ``idx_auto_driver_runs_state`` covers the WHERE clause.
    """
    cursor = await connection.execute(
        _SELECT_RUN_COLUMNS + " WHERE state IN (?, ?) ORDER BY started_at DESC, id DESC",
        (AUTO_DRIVER_STATE_RUNNING, AUTO_DRIVER_STATE_PAUSED),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_run(row) for row in rows]


async def list_for_checklist(
    connection: aiosqlite.Connection,
    checklist_id: str,
) -> list[AutoDriverRun]:
    """Every run for ``checklist_id``, newest-first."""
    cursor = await connection.execute(
        _SELECT_RUN_COLUMNS + " WHERE checklist_id = ? ORDER BY started_at DESC, id DESC",
        (checklist_id,),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_run(row) for row in rows]


async def update_state(
    connection: aiosqlite.Connection,
    run_id: int,
    *,
    state: str,
) -> AutoDriverRun | None:
    """Transition the run to ``state``; rejects illegal transitions.

    Per the state machine in :data:`_TRANSITIONS`. Returns ``None`` if
    the run row is absent; raises :class:`ValueError` on an illegal
    transition.
    """
    existing = await get(connection, run_id)
    if existing is None:
        return None
    if not can_transition(existing.state, state):
        raise ValueError(
            f"update_state: illegal transition {existing.state!r} → {state!r} for run {run_id}"
        )
    timestamp = now_iso()
    await connection.execute(
        "UPDATE auto_driver_runs SET state = ?, updated_at = ? WHERE id = ?",
        (state, timestamp, run_id),
    )
    await connection.commit()
    return replace(existing, state=state, updated_at=timestamp)


def _resolve_counter(current: int, new: int | None) -> int:
    """Return ``current`` when ``new`` is ``None``, otherwise ``new``."""
    return current if new is None else new


def _resolve_current_item(
    current: int | None,
    new_id: int | None,
    clear: bool,
) -> int | None:
    """Resolve the current_item_id sentinel logic.

    ``clear=True`` → None (driver is between items).
    ``new_id`` not None → new_id (driver picked a new item).
    Otherwise → preserve ``current`` unchanged.
    """
    if clear:
        return None
    return new_id if new_id is not None else current


async def update_counters(
    connection: aiosqlite.Connection,
    run_id: int,
    *,
    items_completed: int | None = None,
    items_failed: int | None = None,
    items_blocked: int | None = None,
    items_skipped: int | None = None,
    items_attempted: int | None = None,
    legs_spawned: int | None = None,
    current_item_id: int | None = None,
    clear_current_item: bool = False,
) -> AutoDriverRun | None:
    """Replace any subset of the live counters; returns the new run.

    Each counter argument left as ``None`` is preserved at its current
    value. ``current_item_id`` is special: passing an int sets it,
    passing ``None`` is preservation, and ``clear_current_item=True``
    explicitly NULLs the column (used when the driver finishes an item
    and is between picks). The boolean disambiguates "no change" from
    "clear" since both share the ``None`` sentinel.
    """
    existing = await get(connection, run_id)
    if existing is None:
        return None
    new_completed = _resolve_counter(existing.items_completed, items_completed)
    new_failed = _resolve_counter(existing.items_failed, items_failed)
    new_blocked = _resolve_counter(existing.items_blocked, items_blocked)
    new_skipped = _resolve_counter(existing.items_skipped, items_skipped)
    new_attempted = _resolve_counter(existing.items_attempted, items_attempted)
    new_legs = _resolve_counter(existing.legs_spawned, legs_spawned)
    new_current = _resolve_current_item(
        existing.current_item_id, current_item_id, clear_current_item
    )
    for name, value in (
        ("items_completed", new_completed),
        ("items_failed", new_failed),
        ("items_blocked", new_blocked),
        ("items_skipped", new_skipped),
        ("items_attempted", new_attempted),
        ("legs_spawned", new_legs),
    ):
        if value < 0:
            raise ValueError(f"update_counters.{name} must be ≥ 0 (got {value})")
    timestamp = now_iso()
    await connection.execute(
        "UPDATE auto_driver_runs SET items_completed = ?, items_failed = ?, "
        "items_blocked = ?, items_skipped = ?, items_attempted = ?, legs_spawned = ?, "
        "current_item_id = ?, updated_at = ? WHERE id = ?",
        (
            new_completed,
            new_failed,
            new_blocked,
            new_skipped,
            new_attempted,
            new_legs,
            new_current,
            timestamp,
            run_id,
        ),
    )
    await connection.commit()
    return replace(
        existing,
        items_completed=new_completed,
        items_failed=new_failed,
        items_blocked=new_blocked,
        items_skipped=new_skipped,
        items_attempted=new_attempted,
        legs_spawned=new_legs,
        current_item_id=new_current,
        updated_at=timestamp,
    )


async def finalize(
    connection: aiosqlite.Connection,
    run_id: int,
    *,
    state: str,
    outcome: str,
    outcome_reason: str | None = None,
) -> AutoDriverRun | None:
    """Stamp terminal state + outcome + finished_at.

    ``state`` must be a terminal state (``finished`` or ``errored``);
    every other value is rejected. ``outcome`` is the user-visible
    string the status line freezes on (per behavior/checklists.md
    §"Run-control surface" — "On terminal outcome ('Completed',
    'Halted: failure on item N', …) the line freezes").
    """
    if state not in {AUTO_DRIVER_STATE_FINISHED, AUTO_DRIVER_STATE_ERRORED}:
        raise ValueError(
            f"finalize: state must be a terminal state (finished/errored); got {state!r}"
        )
    if not outcome:
        raise ValueError("finalize: outcome must be non-empty")
    existing = await get(connection, run_id)
    if existing is None:
        return None
    if not can_transition(existing.state, state):
        raise ValueError(
            f"finalize: illegal transition {existing.state!r} → {state!r} for run {run_id}"
        )
    timestamp = now_iso()
    await connection.execute(
        "UPDATE auto_driver_runs SET state = ?, outcome = ?, outcome_reason = ?, "
        "updated_at = ?, finished_at = ? WHERE id = ?",
        (state, outcome, outcome_reason, timestamp, timestamp, run_id),
    )
    await connection.commit()
    return replace(
        existing,
        state=state,
        outcome=outcome,
        outcome_reason=outcome_reason,
        updated_at=timestamp,
        finished_at=timestamp,
    )


_SELECT_RUN_COLUMNS = (
    "SELECT id, checklist_id, state, failure_policy, visit_existing, items_completed, "
    "items_failed, items_blocked, items_skipped, items_attempted, legs_spawned, "
    "current_item_id, outcome, outcome_reason, started_at, updated_at, finished_at "
    "FROM auto_driver_runs"
)


def _row_to_run(row: aiosqlite.Row | tuple[object, ...]) -> AutoDriverRun:
    """Translate a raw SELECT tuple to a validated :class:`AutoDriverRun`."""
    return AutoDriverRun(
        id=int(str(row[0])),
        checklist_id=str(row[1]),
        state=str(row[2]),
        failure_policy=str(row[3]),
        visit_existing=bool(int(str(row[4]))),
        items_completed=int(str(row[5])),
        items_failed=int(str(row[6])),
        items_blocked=int(str(row[7])),
        items_skipped=int(str(row[8])),
        items_attempted=int(str(row[9])),
        legs_spawned=int(str(row[10])),
        current_item_id=None if row[11] is None else int(str(row[11])),
        outcome=None if row[12] is None else str(row[12]),
        outcome_reason=None if row[13] is None else str(row[13]),
        started_at=str(row[14]),
        updated_at=str(row[15]),
        finished_at=None if row[16] is None else str(row[16]),
    )


__all__ = [
    "AutoDriverRun",
    "can_transition",
    "create",
    "finalize",
    "get",
    "get_active",
    "list_for_checklist",
    "update_counters",
    "update_state",
]
