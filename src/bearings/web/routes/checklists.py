"""Checklist + auto-driver routes.

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/checklists.py``
owns CRUD on checklist items, paired-chat link management, and the
auto-driver run-control surface (Start / Stop / Skip / Status).

Endpoints (per behavior/checklists.md "picking/linking/reordering/
run-control" categories):

Picking / item CRUD:
* ``POST   /api/checklists/{id}/items``          — create root or child
* ``GET    /api/checklists/{id}``                — overview (items + active run)
* ``GET    /api/checklists/{id}/items``          — flat list
* ``GET    /api/checklist-items/{item_id}``      — fetch one
* ``PATCH  /api/checklist-items/{item_id}``      — edit label/notes
* ``DELETE /api/checklist-items/{item_id}``      — cascade delete
* ``POST   /api/checklist-items/{item_id}/check``      — mark checked
* ``POST   /api/checklist-items/{item_id}/uncheck``    — clear check
* ``POST   /api/checklist-items/{item_id}/block``      — set blocked/failed/skipped outcome
* ``POST   /api/checklist-items/{item_id}/unblock``    — clear outcome

Linking:
* ``POST   /api/checklist-items/{item_id}/link``       — link to chat (also records leg)
* ``POST   /api/checklist-items/{item_id}/unlink``     — clear pair pointer
* ``GET    /api/checklist-items/{item_id}/legs``       — every leg

Reordering / nesting:
* ``POST   /api/checklist-items/{item_id}/move``       — set parent + sort_order
* ``POST   /api/checklist-items/{item_id}/indent``     — Tab nest under prev sibling
* ``POST   /api/checklist-items/{item_id}/outdent``    — Shift+Tab pop one level

Run-control:
* ``POST   /api/checklists/{id}/run/start``      — create run row (driver dispatch
                                                    is the registry's job; route
                                                    only persists state)
* ``POST   /api/checklists/{id}/run/stop``       — cooperative stop
* ``POST   /api/checklists/{id}/run/pause``      — alias of stop (per behavior doc)
* ``POST   /api/checklists/{id}/run/resume``     — re-Start from first unchecked
* ``POST   /api/checklists/{id}/run/skip-current`` — mark current skipped + advance
* ``GET    /api/checklists/{id}/run/status``     — read active-run row

Handler bodies stay thin per arch §1.1.5: argument parsing, single
domain call, response formatting.
"""

from __future__ import annotations

import asyncio
import logging
from typing import cast

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, status

from bearings.agent.auto_driver import Driver
from bearings.agent.auto_driver_runtime import AutoDriverRegistry, build_driver
from bearings.agent.auto_driver_types import DriverConfig, DriverRuntime
from bearings.config.constants import (
    AUTO_DRIVER_STATE_PAUSED,
    AUTO_DRIVER_STATE_RUNNING,
    KNOWN_AUTO_DRIVER_FAILURE_POLICIES,
    KNOWN_ITEM_OUTCOMES,
    KNOWN_PAIRED_CHAT_SPAWNED_BY,
    PAIRED_CHAT_SPAWNED_BY_USER,
)
from bearings.db import auto_driver_runs as runs_db
from bearings.db import checklists as checklists_db
from bearings.db.auto_driver_runs import AutoDriverRun
from bearings.db.checklists import ChecklistItem, PairedChatLeg
from bearings.web.models.checklists import (
    AutoDriverRunOut,
    ChecklistItemIn,
    ChecklistItemOut,
    ChecklistItemUpdate,
    ChecklistOverviewOut,
    LinkChatIn,
    MoveItemIn,
    OutcomeIn,
    PairedChatLegOut,
    StartRunIn,
)

router = APIRouter()

_LOG = logging.getLogger(__name__)


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state``."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return db  # type: ignore[no-any-return]


def _registry(request: Request) -> AutoDriverRegistry | None:
    """Pull the (optional) :class:`AutoDriverRegistry` off ``app.state``."""
    reg = getattr(request.app.state, "auto_driver_registry", None)
    if reg is None:
        return None
    if not isinstance(reg, AutoDriverRegistry):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auto_driver_registry on app.state is not an AutoDriverRegistry",
        )
    return reg


def _runtime(request: Request) -> DriverRuntime | None:
    """Pull the optional :class:`DriverRuntime` off ``app.state``.

    Returns ``None`` when no runtime is wired (test-only apps that omit
    a DB connection). ``start_run`` guards on it being non-``None``
    before dispatching a live driver task.
    """
    return cast(DriverRuntime | None, getattr(request.app.state, "driver_runtime", None))


def _to_item_out(item: ChecklistItem) -> ChecklistItemOut:
    return ChecklistItemOut(
        id=item.id,
        checklist_id=item.checklist_id,
        parent_item_id=item.parent_item_id,
        label=item.label,
        notes=item.notes,
        sort_order=item.sort_order,
        checked_at=item.checked_at,
        chat_session_id=item.chat_session_id,
        blocked_at=item.blocked_at,
        blocked_reason_category=item.blocked_reason_category,
        blocked_reason_text=item.blocked_reason_text,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _to_leg_out(leg: PairedChatLeg) -> PairedChatLegOut:
    return PairedChatLegOut(
        id=leg.id,
        checklist_item_id=leg.checklist_item_id,
        chat_session_id=leg.chat_session_id,
        leg_number=leg.leg_number,
        spawned_by=leg.spawned_by,
        created_at=leg.created_at,
        closed_at=leg.closed_at,
    )


def _to_run_out(run: AutoDriverRun) -> AutoDriverRunOut:
    return AutoDriverRunOut(
        id=run.id,
        checklist_id=run.checklist_id,
        state=run.state,
        failure_policy=run.failure_policy,
        visit_existing=run.visit_existing,
        items_completed=run.items_completed,
        items_failed=run.items_failed,
        items_blocked=run.items_blocked,
        items_skipped=run.items_skipped,
        items_attempted=run.items_attempted,
        legs_spawned=run.legs_spawned,
        current_item_id=run.current_item_id,
        outcome=run.outcome,
        outcome_reason=run.outcome_reason,
        started_at=run.started_at,
        updated_at=run.updated_at,
        finished_at=run.finished_at,
    )


# ---- picking / item CRUD ---------------------------------------------------


@router.post(
    "/api/checklists/{checklist_id}/items",
    status_code=status.HTTP_201_CREATED,
    response_model=ChecklistItemOut,
)
async def create_item(
    checklist_id: str,
    payload: ChecklistItemIn,
    request: Request,
) -> ChecklistItemOut:
    """Create a checklist item; ``parent_item_id`` is optional."""
    db = _db(request)
    try:
        item = await checklists_db.create(
            db,
            checklist_id=checklist_id,
            label=payload.label,
            parent_item_id=payload.parent_item_id,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _to_item_out(item)


@router.get("/api/checklists/{checklist_id}/items", response_model=list[ChecklistItemOut])
async def list_items(checklist_id: str, request: Request) -> list[ChecklistItemOut]:
    """Every item under ``checklist_id``."""
    db = _db(request)
    items = await checklists_db.list_for_checklist(db, checklist_id)
    return [_to_item_out(item) for item in items]


@router.get("/api/checklists/{checklist_id}", response_model=ChecklistOverviewOut)
async def get_overview(checklist_id: str, request: Request) -> ChecklistOverviewOut:
    """Bundled items + active run for one paint."""
    db = _db(request)
    items = await checklists_db.list_for_checklist(db, checklist_id)
    active = await runs_db.get_active(db, checklist_id)
    return ChecklistOverviewOut(
        checklist_id=checklist_id,
        items=[_to_item_out(item) for item in items],
        active_run=None if active is None else _to_run_out(active),
    )


@router.get("/api/checklist-items/{item_id}", response_model=ChecklistItemOut)
async def get_item(item_id: int, request: Request) -> ChecklistItemOut:
    """Fetch one item; 404 if absent."""
    db = _db(request)
    item = await checklists_db.get(db, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"item {item_id} not found"
        )
    return _to_item_out(item)


@router.patch("/api/checklist-items/{item_id}", response_model=ChecklistItemOut)
async def update_item(
    item_id: int,
    payload: ChecklistItemUpdate,
    request: Request,
) -> ChecklistItemOut:
    """Patch label / notes (either or both)."""
    db = _db(request)
    item: ChecklistItem | None = await checklists_db.get(db, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"item {item_id} not found"
        )
    try:
        if payload.label is not None:
            item = await checklists_db.update_label(db, item_id, label=payload.label)
        if payload.notes is not None or "notes" in payload.model_fields_set:
            item = await checklists_db.update_notes(db, item_id, notes=payload.notes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if item is None:  # pragma: no cover — guarded by 404 above
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vanished")
    return _to_item_out(item)


@router.delete(
    "/api/checklist-items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_item(item_id: int, request: Request) -> None:
    """Cascade-delete an item + subtree + paired_chats per FK."""
    db = _db(request)
    removed = await checklists_db.delete(db, item_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"item {item_id} not found"
        )


@router.post("/api/checklist-items/{item_id}/check", response_model=ChecklistItemOut)
async def check_item(item_id: int, request: Request) -> ChecklistItemOut:
    """Mark item checked (green)."""
    db = _db(request)
    item = await checklists_db.mark_checked(db, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"item {item_id} not found"
        )
    return _to_item_out(item)


@router.post("/api/checklist-items/{item_id}/uncheck", response_model=ChecklistItemOut)
async def uncheck_item(item_id: int, request: Request) -> ChecklistItemOut:
    """Clear ``checked_at``."""
    db = _db(request)
    item = await checklists_db.mark_unchecked(db, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"item {item_id} not found"
        )
    return _to_item_out(item)


@router.post("/api/checklist-items/{item_id}/block", response_model=ChecklistItemOut)
async def block_item(
    item_id: int,
    payload: OutcomeIn,
    request: Request,
) -> ChecklistItemOut:
    """Mark a non-completion outcome (blocked / failed / skipped)."""
    db = _db(request)
    if payload.category not in KNOWN_ITEM_OUTCOMES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(f"category {payload.category!r} not in {sorted(KNOWN_ITEM_OUTCOMES)}"),
        )
    try:
        item = await checklists_db.mark_outcome(
            db, item_id, category=payload.category, reason=payload.reason
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"item {item_id} not found"
        )
    return _to_item_out(item)


@router.post("/api/checklist-items/{item_id}/unblock", response_model=ChecklistItemOut)
async def unblock_item(item_id: int, request: Request) -> ChecklistItemOut:
    """Clear any non-completion outcome (back to not-yet-attempted)."""
    db = _db(request)
    item = await checklists_db.clear_outcome(db, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"item {item_id} not found"
        )
    return _to_item_out(item)


# ---- linking ---------------------------------------------------------------


@router.post("/api/checklist-items/{item_id}/link", response_model=ChecklistItemOut)
async def link_chat(
    item_id: int,
    payload: LinkChatIn,
    request: Request,
) -> ChecklistItemOut:
    """Link a chat session as the leaf's paired chat + record a leg."""
    db = _db(request)
    if payload.spawned_by not in KNOWN_PAIRED_CHAT_SPAWNED_BY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"spawned_by {payload.spawned_by!r} not in {sorted(KNOWN_PAIRED_CHAT_SPAWNED_BY)}"
            ),
        )
    try:
        item = await checklists_db.set_paired_chat(
            db, item_id, chat_session_id=payload.chat_session_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"item {item_id} not found"
        )
    await checklists_db.record_leg(
        db,
        checklist_item_id=item_id,
        chat_session_id=payload.chat_session_id,
        spawned_by=payload.spawned_by,
    )
    return _to_item_out(item)


@router.post("/api/checklist-items/{item_id}/unlink", response_model=ChecklistItemOut)
async def unlink_chat(item_id: int, request: Request) -> ChecklistItemOut:
    """Clear the pair pointer (chat keeps its history)."""
    db = _db(request)
    item = await checklists_db.clear_paired_chat(db, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"item {item_id} not found"
        )
    return _to_item_out(item)


@router.get("/api/checklist-items/{item_id}/legs", response_model=list[PairedChatLegOut])
async def list_item_legs(item_id: int, request: Request) -> list[PairedChatLegOut]:
    """Every leg recorded for ``item_id`` (oldest-first)."""
    db = _db(request)
    item = await checklists_db.get(db, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"item {item_id} not found"
        )
    legs = await checklists_db.list_legs(db, item_id)
    return [_to_leg_out(leg) for leg in legs]


# ---- reordering / nesting -------------------------------------------------


@router.post("/api/checklist-items/{item_id}/move", response_model=ChecklistItemOut)
async def move_item(
    item_id: int,
    payload: MoveItemIn,
    request: Request,
) -> ChecklistItemOut:
    """Reparent + optionally pin sort_order."""
    db = _db(request)
    try:
        item = await checklists_db.move_to_parent(
            db,
            item_id,
            parent_item_id=payload.parent_item_id,
            sort_order=payload.sort_order,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"item {item_id} not found"
        )
    return _to_item_out(item)


@router.post("/api/checklist-items/{item_id}/indent", response_model=ChecklistItemOut)
async def indent_item(item_id: int, request: Request) -> ChecklistItemOut:
    """Tab — nest under previous sibling."""
    db = _db(request)
    try:
        item = await checklists_db.indent(db, item_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"item {item_id} not found"
        )
    return _to_item_out(item)


@router.post("/api/checklist-items/{item_id}/outdent", response_model=ChecklistItemOut)
async def outdent_item(item_id: int, request: Request) -> ChecklistItemOut:
    """Shift+Tab — pop one level out."""
    db = _db(request)
    try:
        item = await checklists_db.outdent(db, item_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"item {item_id} not found"
        )
    return _to_item_out(item)


# ---- run-control ---------------------------------------------------------


@router.post(
    "/api/checklists/{checklist_id}/run/start",
    status_code=status.HTTP_201_CREATED,
    response_model=AutoDriverRunOut,
)
async def start_run(
    checklist_id: str,
    payload: StartRunIn,
    request: Request,
) -> AutoDriverRunOut:
    """Persist a ``running`` ``auto_driver_runs`` row.

    Per behavior/checklists.md the dispatch (live driver task spawn)
    is wired by the runtime registry; this route owns the durable
    state. If a live registry is on app.state and a previous run is
    active, we reject the start with 409 — one active run per
    checklist at a time.
    """
    db = _db(request)
    if payload.failure_policy not in KNOWN_AUTO_DRIVER_FAILURE_POLICIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"failure_policy {payload.failure_policy!r} not in "
                f"{sorted(KNOWN_AUTO_DRIVER_FAILURE_POLICIES)}"
            ),
        )
    active = await runs_db.get_active(db, checklist_id)
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"checklist {checklist_id} already has an active run "
                f"(run_id={active.id}, state={active.state})"
            ),
        )
    try:
        run = await runs_db.create(
            db,
            checklist_id=checklist_id,
            failure_policy=payload.failure_policy,
            visit_existing=payload.visit_existing,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # Dispatch the live driver task when both the registry and the
    # runtime are wired (production). Tests that omit ``db_connection``
    # on app creation get ``driver_runtime=None`` and fall through to
    # the durable-row-only path, which is sufficient for route-layer
    # unit tests.
    registry = _registry(request)
    runtime = _runtime(request)
    if registry is not None and runtime is not None:
        config = DriverConfig(
            failure_policy=payload.failure_policy,
            visit_existing=payload.visit_existing,
        )
        driver: Driver = build_driver(
            run_id=run.id,
            checklist_id=checklist_id,
            config=config,
            runtime=runtime,
            connection=db,
        )
        registry.register(driver)
        task = asyncio.create_task(
            driver.drive(),
            name=f"auto_driver:{checklist_id}",
        )
        # Unregister on completion so a subsequent Start can re-register
        # a fresh driver. The done-callback fires whether drive() returns
        # normally, raises, or is cancelled.
        task.add_done_callback(lambda _: registry.unregister(checklist_id))
        _LOG.info(
            "start_run: dispatched driver task for checklist %r run_id=%d",
            checklist_id,
            run.id,
        )

    return _to_run_out(run)


@router.post("/api/checklists/{checklist_id}/run/stop", response_model=AutoDriverRunOut)
async def stop_run(checklist_id: str, request: Request) -> AutoDriverRunOut:
    """Cooperative stop on the active run; transitions to ``paused``."""
    db = _db(request)
    active = await runs_db.get_active(db, checklist_id)
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"checklist {checklist_id} has no active run",
        )
    registry = _registry(request)
    if registry is not None:
        registry.stop(checklist_id)
    if active.state != AUTO_DRIVER_STATE_PAUSED:
        try:
            updated = await runs_db.update_state(db, active.id, state=AUTO_DRIVER_STATE_PAUSED)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        if updated is not None:
            active = updated
    return _to_run_out(active)


@router.post("/api/checklists/{checklist_id}/run/pause", response_model=AutoDriverRunOut)
async def pause_run(checklist_id: str, request: Request) -> AutoDriverRunOut:
    """Alias of stop — checklists.md notes pause and stop share wiring in v1."""
    return await stop_run(checklist_id, request)


@router.post("/api/checklists/{checklist_id}/run/resume", response_model=AutoDriverRunOut)
async def resume_run(checklist_id: str, request: Request) -> AutoDriverRunOut:
    """Resume a ``paused`` run by transitioning it back to ``running``.

    Per behavior/checklists.md "the user can re-Start later; the next
    run resumes from the first unchecked item" — the resume API is
    additive on top of Start: if there's no paused run, 404; if the
    state is already running, 409.
    """
    db = _db(request)
    active = await runs_db.get_active(db, checklist_id)
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"checklist {checklist_id} has no active run",
        )
    if active.state != AUTO_DRIVER_STATE_PAUSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"run {active.id} is not paused (state={active.state!r})",
        )
    try:
        updated = await runs_db.update_state(db, active.id, state=AUTO_DRIVER_STATE_RUNNING)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if updated is None:  # pragma: no cover — guarded above
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vanished")
    return _to_run_out(updated)


@router.post(
    "/api/checklists/{checklist_id}/run/skip-current",
    response_model=AutoDriverRunOut,
)
async def skip_current(checklist_id: str, request: Request) -> AutoDriverRunOut:
    """Skip the item currently being driven, if any."""
    db = _db(request)
    active = await runs_db.get_active(db, checklist_id)
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"checklist {checklist_id} has no active run",
        )
    registry = _registry(request)
    if registry is not None:
        registry.skip_current(checklist_id)
    return _to_run_out(active)


@router.get("/api/checklists/{checklist_id}/run/status", response_model=AutoDriverRunOut)
async def run_status(checklist_id: str, request: Request) -> AutoDriverRunOut:
    """Return the active-run row (or 404 when no run is active)."""
    db = _db(request)
    active = await runs_db.get_active(db, checklist_id)
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"checklist {checklist_id} has no active run",
        )
    return _to_run_out(active)


# Suppress "imported but unused" for the constants the route handlers
# don't reference directly — they document the validator alphabet
# tested at boundary. Used here at literal sites; no-op otherwise.
_ = PAIRED_CHAT_SPAWNED_BY_USER  # default value reference for spawned_by


__all__ = ["router"]
