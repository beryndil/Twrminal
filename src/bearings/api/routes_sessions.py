from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from bearings import metrics
from bearings.agent.prompt import assemble_prompt, estimate_tokens
from bearings.agent.sessions_broker import (
    publish_session_delete,
    publish_session_upsert,
)
from bearings.api.auth import require_auth
from bearings.api.models import (
    MessageOut,
    SessionCreate,
    SessionOut,
    SessionUpdate,
    SystemPromptLayerOut,
    SystemPromptOut,
    TagOut,
    TodoItemOut,
    TodosOut,
    TokenTotalsOut,
    ToolCallOut,
)
from bearings.db import store

router = APIRouter(
    prefix="/sessions",
    tags=["sessions"],
    dependencies=[Depends(require_auth)],
)


@router.post("", response_model=SessionOut)
async def create_session(body: SessionCreate, request: Request) -> SessionOut:
    # v0.2.13: require ≥1 tag on every externally-created session.
    # Tags carry the project-like defaults + memories, so a tag-less
    # session has no context hooks at all — guard rail against that.
    if not body.tag_ids:
        raise HTTPException(
            status_code=400,
            detail="at least one tag_id is required (sessions must be tagged)",
        )
    conn = request.app.state.db
    # Validate every tag exists before inserting the session — avoids a
    # partial state where the session row is created but some tags fail
    # to attach.
    for tag_id in body.tag_ids:
        if await store.get_tag(conn, tag_id) is None:
            raise HTTPException(status_code=400, detail=f"tag_id {tag_id} does not exist")
    # Fill in the global per-session cap from config when the caller
    # didn't pass one. Explicit `0` or any other value is honored
    # verbatim — operator knows best for that specific session.
    # `None` + config default `None` keeps today's uncapped behavior.
    # 2026-04-21 security audit §7.
    settings = request.app.state.settings
    budget = body.max_budget_usd
    if budget is None:
        budget = settings.agent.default_max_budget_usd
    # working_dir resolution. Caller-supplied wins. When absent the
    # route falls back to the profile's `workspace_root` (per-session
    # sandbox subdir, `safe` profile) or the legacy
    # `settings.agent.working_dir` default. We pre-create the sandbox
    # subdir so the agent's first tool call doesn't trip on a missing
    # cwd. 2026-04-21 security audit §5 (workspace sandboxing).
    requested_dir = (body.working_dir or "").strip()
    workspace_root = settings.agent.workspace_root
    use_sandbox = not requested_dir and workspace_root is not None
    if requested_dir:
        working_dir = requested_dir
    elif workspace_root is None:
        working_dir = str(settings.agent.working_dir)
    else:
        # Provisional path; the per-session subdir gets the real
        # session_id appended after `create_session` mints it.
        working_dir = str(settings.agent.working_dir)
    row = await store.create_session(
        conn,
        working_dir=working_dir,
        model=body.model,
        title=body.title,
        description=body.description,
        max_budget_usd=budget,
        kind=body.kind,
    )
    if use_sandbox:
        assert workspace_root is not None  # narrowed by use_sandbox
        sandbox_dir = workspace_root / row["id"]
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        await store.set_working_dir(conn, row["id"], str(sandbox_dir))
    for tag_id in body.tag_ids:
        await store.attach_tag(conn, row["id"], tag_id)
    # Severity invariant (migration 0021): every session carries exactly
    # one severity tag. If the caller passed one explicitly in tag_ids
    # the `attach_tag` loop already landed it; otherwise auto-attach
    # the default ('Low'). Silent no-op if the user has deleted /
    # renamed the default — the session lands without a visible
    # severity, matching the "physical law, not DB constraint" design.
    await store.ensure_default_severity(conn, row["id"])
    # Checklist-kind sessions carry a 1:1 companion row. Create it in
    # the same request so a freshly-minted checklist session is
    # immediately addressable via `/api/sessions/{id}/checklist` — no
    # half-built state where the session exists but the checklist
    # doesn't. `create_checklist` commits; a failure here leaves the
    # session row behind, which is acceptable (user can retry the
    # checklist body endpoint) and simpler than an explicit rollback.
    if body.kind == "checklist":
        await store.create_checklist(conn, row["id"])
    metrics.sessions_created.inc()
    # Re-fetch so the returned row carries any updated_at bump from
    # the attach step, for frontend sort consistency.
    refreshed = await store.get_session(conn, row["id"])
    assert refreshed is not None
    # Broadcast to every open sidebar so a second tab sees the new
    # session appear without waiting on the Phase-1 poll tick.
    await publish_session_upsert(
        getattr(request.app.state, "sessions_broker", None), conn, row["id"]
    )
    return SessionOut(**refreshed)


@router.get("/running", response_model=list[str])
async def list_running_sessions(request: Request) -> list[str]:
    """Session ids whose runner currently has a turn in flight.

    Polled by the UI so the session list can flag sessions the user
    kicked off and walked away from. Cheap — reads in-memory registry
    state, no DB hit. Shape is a bare `list[str]` for backward
    compatibility with every frontend bundle shipped before the v0.10
    indicator redesign — the red-flashing `is_awaiting_user` axis
    lives on a sibling endpoint (`/api/sessions/awaiting`) so callers
    that only care about running don't have to adapt."""
    runners = getattr(request.app.state, "runners", None)
    if runners is None:
        return []
    return sorted(runners.running_ids())


@router.get("/awaiting", response_model=list[str])
async def list_awaiting_sessions(request: Request) -> list[str]:
    """Session ids whose runner is currently parked on a `can_use_tool`
    decision (tool-use permission OR AskUserQuestion). Drives the
    sidebar's red-flashing "look at this now" indicator as the poll
    fallback when the `/ws/sessions` broadcast socket is down.

    A session can be reported by both `/running` and `/awaiting` — the
    intersection is exactly the red-flashing set; `/running \\ /awaiting`
    is orange-flashing. Cheap — in-memory registry walk, no DB hit."""
    runners = getattr(request.app.state, "runners", None)
    if runners is None:
        return []
    return sorted(runners.awaiting_user_ids())


def _parse_tag_csv(raw: str | None, param_name: str) -> list[int] | None:
    """Parse a comma-separated tag-id query param.

    - `None` → `None` (param absent, no filter on this axis).
    - Empty string (`?tags=`) → `[]` (param present but empty). The
      v0.7.4 sidebar sends this when the user has the panel open but
      no general tags selected — it means "match nothing", not "no
      filter". `list_sessions` maps the empty list to `1 = 0`.
    - Non-empty CSV → list of ints.

    Malformed values raise a 400 so the client learns immediately
    rather than getting silently empty results.
    """
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return []
    try:
        return [int(t) for t in stripped.split(",") if t.strip()]
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{param_name} must be comma-separated integers",
        ) from exc


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    request: Request,
    tags: str | None = Query(
        None,
        description=(
            "Comma-separated tag ids (general group). Omit the param for "
            "the legacy 'no filter' path (every session). Send an empty "
            "value (`?tags=`) to request 'match nothing' — the v0.7.4 "
            "sidebar default when no general tags are selected. "
            "Non-empty lists OR-combine (any listed tag)."
        ),
    ),
    severity_tags: str | None = Query(
        None,
        description=(
            "Comma-separated severity tag ids (tag_group='severity'). "
            "Always OR-within-group since each session carries exactly one "
            "severity; combined with the `tags` filter via AND."
        ),
    ),
) -> list[SessionOut]:
    tag_ids = _parse_tag_csv(tags, "tags")
    severity_tag_ids = _parse_tag_csv(severity_tags, "severity_tags")
    rows = await store.list_sessions(
        request.app.state.db,
        tag_ids=tag_ids,
        severity_tag_ids=severity_tag_ids,
    )
    return [SessionOut(**r) for r in rows]


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, request: Request) -> SessionOut:
    row = await store.get_session(request.app.state.db, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionOut(**row)


# SessionUpdate fields whose change on a live session invalidates the
# running runner's SDK subprocess — either because they're layered into
# the system prompt (`description`, `session_instructions`) or because
# the subprocess itself was spawned with a now-stale argument (`model`,
# per Phase 4a.1 / plan §2.1 "change model for continuation"). Dropping
# the runner forces the next WS turn to spawn fresh and pick up the new
# value. Fields NOT in this set (title, max_budget_usd, pinned) are
# UI/billing-only and don't need a respawn.
_RUNNER_RESPAWN_FIELDS = frozenset({"description", "session_instructions", "model"})


async def _drop_runner_if_present(request: Request, session_id: str) -> None:
    """Tear down the live runner for `session_id` if one exists. Safe
    to call when no runner is attached (idempotent no-op). The next WS
    turn re-creates the runner via `RunnerRegistry.get_or_create`,
    which re-assembles the system prompt from current DB state."""
    runners = getattr(request.app.state, "runners", None)
    if runners is not None:
        await runners.drop(session_id)


@router.patch("/{session_id}", response_model=SessionOut)
async def update_session(session_id: str, body: SessionUpdate, request: Request) -> SessionOut:
    # Only fields the client explicitly set are applied — unset fields
    # leave the column untouched, explicit null clears it.
    fields = {k: getattr(body, k) for k in body.model_fields_set}
    row = await store.update_session(request.app.state.db, session_id, fields=fields)
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    if _RUNNER_RESPAWN_FIELDS & body.model_fields_set:
        # description / session_instructions / model edits reach the
        # agent only after a runner respawn — see
        # `_RUNNER_RESPAWN_FIELDS` note.
        await _drop_runner_if_present(request, session_id)
    await publish_session_upsert(
        getattr(request.app.state, "sessions_broker", None),
        request.app.state.db,
        session_id,
    )
    return SessionOut(**row)


@router.post("/{session_id}/close", response_model=SessionOut)
async def close_session(session_id: str, request: Request) -> SessionOut:
    """Mark the session closed — the sidebar sinks it into the
    collapsed "Closed" group on the next render. Idempotent: a second
    call just refreshes `closed_at`. No runner respawn; the lifecycle
    flag doesn't enter the system prompt."""
    row = await store.close_session(request.app.state.db, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    await publish_session_upsert(
        getattr(request.app.state, "sessions_broker", None),
        request.app.state.db,
        session_id,
    )
    return SessionOut(**row)


@router.post("/{session_id}/reopen", response_model=SessionOut)
async def reopen_session(session_id: str, request: Request) -> SessionOut:
    """Clear the closed flag. Idempotent on already-open sessions."""
    row = await store.reopen_session(request.app.state.db, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    await publish_session_upsert(
        getattr(request.app.state, "sessions_broker", None),
        request.app.state.db,
        session_id,
    )
    return SessionOut(**row)


@router.post("/{session_id}/viewed", response_model=SessionOut)
async def mark_session_viewed(session_id: str, request: Request) -> SessionOut:
    """Stamp `last_viewed_at` so the sidebar clears the "finished but
    unviewed" amber dot. Called by the frontend when the user selects
    the session or the browser tab regains focus while the session is
    selected. Does NOT bump `updated_at` — viewing doesn't change sort
    position. Idempotent: a second call just refreshes the timestamp."""
    row = await store.mark_session_viewed(request.app.state.db, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    # Publish the viewed-state change so a second tab's amber dot
    # clears without its own click — the row doesn't resort (we didn't
    # touch updated_at) but `last_viewed_at` now matches the user's
    # action elsewhere.
    await publish_session_upsert(
        getattr(request.app.state, "sessions_broker", None),
        request.app.state.db,
        session_id,
    )
    return SessionOut(**row)


@router.delete("/{session_id}")
async def delete_session(session_id: str, request: Request) -> dict[str, bool]:
    ok = await store.delete_session(request.app.state.db, session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")
    # If this session had a live runner (it was open in a tab, even
    # one we never reconnected to), drain it so its SDK subprocess
    # doesn't outlive the row it was serving.
    runners = getattr(request.app.state, "runners", None)
    if runners is not None:
        await runners.drop(session_id)
    # Broadcast the deletion so every open sidebar drops the row
    # without waiting on the poll. `publish_session_delete` is the
    # cheap fire-and-forget path — no DB round-trip to confirm a row
    # we know is gone.
    publish_session_delete(getattr(request.app.state, "sessions_broker", None), session_id)
    return {"deleted": True}


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(
    session_id: str,
    request: Request,
    before: str | None = Query(None),
    limit: int | None = Query(None, ge=1, le=500),
) -> list[MessageOut]:
    conn = request.app.state.db
    if await store.get_session(conn, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    rows = await store.list_messages(conn, session_id, before=before, limit=limit)
    return [MessageOut(**r) for r in rows]


@router.get("/{session_id}/tokens", response_model=TokenTotalsOut)
async def get_session_tokens(session_id: str, request: Request) -> TokenTotalsOut:
    """Aggregate token totals for a session — feeds the subscription-
    mode session card and conversation header. Cheap (one COALESCE(SUM)
    over an indexed session_id scan), so the frontend polls it on
    message_complete rather than maintaining a running tally."""
    conn = request.app.state.db
    if await store.get_session(conn, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    totals = await store.get_session_token_totals(conn, session_id)
    return TokenTotalsOut(**totals)


@router.get("/{session_id}/tool_calls", response_model=list[ToolCallOut])
async def list_tool_calls(
    session_id: str,
    request: Request,
    message_ids: Annotated[list[str] | None, Query()] = None,
) -> list[ToolCallOut]:
    """List tool_calls for a session.

    `message_ids` is an optional repeated query param used by the
    conversation pane to scope the response to the currently-visible
    message page. Omit it for the full-history view (export /
    checkpoints / reorg). Passing an empty list short-circuits to
    `[]` — FastAPI parses a bare `?message_ids=` as an empty list, and
    the DB helper treats that as "no visible messages, no rows to
    return" rather than building a syntactically-invalid `IN ()`."""
    conn = request.app.state.db
    if await store.get_session(conn, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    rows = await store.list_tool_calls(conn, session_id, message_ids=message_ids)
    return [ToolCallOut(**r) for r in rows]


@router.get("/{session_id}/todos", response_model=TodosOut)
async def get_session_todos(session_id: str, request: Request) -> TodosOut:
    """Return the latest TodoWrite snapshot for a session — feeds the
    first paint of the sticky LiveTodos widget. Live updates after
    that are delivered via the `todo_write_update` WS event; this
    route exists so reloading the page or switching sessions doesn't
    show an empty widget while the next TodoWrite call lands.

    Tolerates malformed historical rows: `store.get_latest_todowrite`
    logs-and-returns-None for a row whose `input` isn't valid JSON or
    lacks a `todos` list, so the widget degrades to "no todos" rather
    than a 500."""
    conn = request.app.state.db
    if await store.get_session(conn, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    raw = await store.get_latest_todowrite(conn, session_id)
    if raw is None:
        return TodosOut(todos=None)
    items: list[TodoItemOut] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            items.append(TodoItemOut.model_validate(entry))
        except Exception:  # noqa: BLE001 — tolerate individual bad rows
            # Skip malformed rows silently; a widget with N-1 items is
            # still useful while the agent updates on the next call.
            continue
    return TodosOut(todos=items)


# Size cap on the raw import body. The export shape carries every
# message + tool_call for a single session — ~16 MB covers a 5000-event
# turn at ~3 KB/event with headroom for an unusually long thread, while
# slamming the door on accidental or hostile multi-GB uploads that
# would otherwise be parsed entirely into memory before any validation
# could fire. (Security audit 2026-04-21 §4.)
_IMPORT_MAX_BYTES = 16 * 1024 * 1024
# Per-list caps on the parsed payload. The exporter writes one row per
# message and one per tool call; these caps bound the per-import work
# the store layer will do without changing the realistic export size.
_IMPORT_MAX_MESSAGES = 100_000
_IMPORT_MAX_TOOL_CALLS = 200_000


def _validate_import_payload(payload: Any) -> dict[str, Any]:
    """Shape-check the import body. Raises `HTTPException(400)` on any
    malformed input — top-level must be a JSON object containing a
    `session` object, optional `messages` list, optional `tool_calls`
    list, each within the per-list caps. Returns the validated dict so
    the caller can hand it straight to `store.import_session`."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="import body must be a JSON object")
    session = payload.get("session")
    if not isinstance(session, dict):
        raise HTTPException(status_code=400, detail="missing or malformed `session` object")
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="`messages` must be a list")
    if len(messages) > _IMPORT_MAX_MESSAGES:
        raise HTTPException(
            status_code=400,
            detail=f"too many messages (max {_IMPORT_MAX_MESSAGES})",
        )
    if not all(isinstance(m, dict) for m in messages):
        raise HTTPException(status_code=400, detail="every `messages` entry must be an object")
    tool_calls = payload.get("tool_calls", [])
    if not isinstance(tool_calls, list):
        raise HTTPException(status_code=400, detail="`tool_calls` must be a list")
    if len(tool_calls) > _IMPORT_MAX_TOOL_CALLS:
        raise HTTPException(
            status_code=400,
            detail=f"too many tool_calls (max {_IMPORT_MAX_TOOL_CALLS})",
        )
    if not all(isinstance(t, dict) for t in tool_calls):
        raise HTTPException(status_code=400, detail="every `tool_calls` entry must be an object")
    return payload


@router.post("/import", response_model=SessionOut)
async def import_session(request: Request) -> SessionOut:
    """Restore a session from the v0.1.30 export shape. Generates new
    ids so the import can land next to an existing session with the
    same original id. Sibling of the per-session /export endpoint.

    Reads the body manually (rather than letting FastAPI bind a
    `dict[str, Any]` parameter) so we can enforce a hard size cap
    BEFORE the JSON is parsed into Python objects. Without the cap a
    multi-GB upload would balloon the process before any validator
    could reject it. Then `_validate_import_payload` shape-checks the
    parsed dict and `ensure_default_severity` preserves the
    every-session-has-a-severity-tag invariant
    (security audit 2026-04-21 §4)."""
    body = await request.body()
    if len(body) > _IMPORT_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"import body exceeds {_IMPORT_MAX_BYTES} bytes",
        )
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc.msg}") from exc
    payload = _validate_import_payload(payload)
    row = await store.import_session(request.app.state.db, payload)
    # Imports predate migration 0021 by definition — backfill the
    # default severity so the imported session has a shield in the
    # sidebar. No-op on re-import of something already carrying a
    # severity (ensure_default_severity is idempotent).
    await store.ensure_default_severity(request.app.state.db, row["id"])
    metrics.sessions_created.inc()
    await publish_session_upsert(
        getattr(request.app.state, "sessions_broker", None),
        request.app.state.db,
        row["id"],
    )
    return SessionOut(**row)


@router.get("/{session_id}/export")
async def export_session(session_id: str, request: Request) -> dict[str, Any]:
    """Single-session dump — session metadata + every message and
    tool call. Keeps the `/api/history/export` shape-per-section but
    scoped to one session so users can archive a finished
    conversation as a standalone JSON file."""
    conn = request.app.state.db
    session = await store.get_session(conn, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    messages = await store.list_messages(conn, session_id)
    tool_calls = await store.list_tool_calls(conn, session_id)
    return {
        "session": session,
        "messages": messages,
        "tool_calls": tool_calls,
    }


@router.get("/{session_id}/tags", response_model=list[TagOut])
async def list_session_tags(session_id: str, request: Request) -> list[TagOut]:
    conn = request.app.state.db
    if await store.get_session(conn, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    rows = await store.list_session_tags(conn, session_id)
    return [TagOut(**r) for r in rows]


@router.get("/{session_id}/system_prompt", response_model=SystemPromptOut)
async def get_session_system_prompt(session_id: str, request: Request) -> SystemPromptOut:
    """Inspect the layered system prompt that would be sent to the SDK on
    the next turn. Read-only — calls the same `assemble_prompt` the
    agent uses so what you see here is what the model sees."""
    conn = request.app.state.db
    if await store.get_session(conn, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    assembled = await assemble_prompt(conn, session_id)
    layers = [
        SystemPromptLayerOut(
            name=layer.name,
            kind=layer.kind,
            content=layer.content,
            token_count=estimate_tokens(layer.content),
        )
        for layer in assembled.layers
    ]
    return SystemPromptOut(
        layers=layers,
        total_tokens=sum(layer.token_count for layer in layers),
    )


@router.post("/{session_id}/tags/{tag_id}", response_model=list[TagOut])
async def attach_session_tag(session_id: str, tag_id: int, request: Request) -> list[TagOut]:
    conn = request.app.state.db
    ok = await store.attach_tag(conn, session_id, tag_id)
    if not ok:
        # attach_tag returns False when either the session or the tag
        # doesn't exist — both map to 404 from the client's view.
        if await store.get_session(conn, session_id) is None:
            raise HTTPException(status_code=404, detail="session not found")
        raise HTTPException(status_code=404, detail="tag not found")
    rows = await store.list_session_tags(conn, session_id)
    # Tag attach adds/removes a tag_memory layer on the next assembled
    # prompt; the live runner must respawn to transport that to the SDK.
    await _drop_runner_if_present(request, session_id)
    return [TagOut(**r) for r in rows]


@router.delete("/{session_id}/tags/{tag_id}", response_model=list[TagOut])
async def detach_session_tag(session_id: str, tag_id: int, request: Request) -> list[TagOut]:
    conn = request.app.state.db
    ok = await store.detach_tag(conn, session_id, tag_id)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")
    rows = await store.list_session_tags(conn, session_id)
    await _drop_runner_if_present(request, session_id)
    return [TagOut(**r) for r in rows]
