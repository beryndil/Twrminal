"""Template API surface (Phase 9b of docs/context-menu-plan.md).

URL shape — mounted at `/api`:

  POST   /templates                       — create
  GET    /templates                       — list newest-first
  DELETE /templates/{id}                  — remove
  POST   /sessions/from_template/{id}     — instantiate

Instantiation composes existing primitives rather than rebuilding the
create path: the route resolves the template, folds any caller-supplied
overrides on top, and calls `store.create_session` + `store.attach_tag`
the same way the regular `POST /sessions` route does. Unknown tag ids
(tag was deleted since the template was saved) are silently dropped so
a stale template still produces a usable session.

The `body` field carries an optional first-user-prompt. When non-empty
the route seeds it via `store.insert_message` so the new session lands
with a user message ready for the runner — same behavior as the
`NewSessionForm` initial-prompt path. Empty / null `body` produces a
blank session.

Thin handler — `store.*` does the work. Severity invariant (migration
0021) is enforced via the same `ensure_default_severity` helper the
regular create path uses.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from bearings import metrics
from bearings.agent.sessions_broker import publish_session_upsert
from bearings.api.auth import require_auth
from bearings.api.models import (
    SessionOut,
    TemplateCreate,
    TemplateInstantiateRequest,
    TemplateOut,
)
from bearings.db import store

router = APIRouter(tags=["templates"], dependencies=[Depends(require_auth)])


@router.post("/templates", response_model=TemplateOut, status_code=201)
async def create_template(body: TemplateCreate, request: Request) -> TemplateOut:
    """Save a new template. Unknown tag ids are accepted — the saved
    row is intentionally decoupled from the tags table, so a later
    `DELETE /tags/{id}` doesn't invalidate the template. The
    instantiate path filters at attach time instead."""
    row = await store.create_template(
        request.app.state.db,
        name=body.name,
        body=body.body,
        working_dir=body.working_dir,
        model=body.model,
        session_instructions=body.session_instructions,
        tag_ids=body.tag_ids,
    )
    metrics.templates_created.inc()
    return TemplateOut(**row)


@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(request: Request) -> list[TemplateOut]:
    rows = await store.list_templates(request.app.state.db)
    return [TemplateOut(**row) for row in rows]


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(template_id: str, request: Request) -> Response:
    ok = await store.delete_template(request.app.state.db, template_id)
    if not ok:
        raise HTTPException(status_code=404, detail="template not found")
    return Response(status_code=204)


def _resolved_working_dir(template: dict[str, object], override: str | None) -> str | None:
    """The create path needs a real working_dir; we prefer the
    override, then the template value, then return None so the caller
    can 400 rather than landing a session with an invalid dir."""
    if override is not None and override.strip():
        return override
    saved = template.get("working_dir")
    return saved if isinstance(saved, str) and saved.strip() else None


def _resolved_model(template: dict[str, object], override: str | None) -> str | None:
    if override is not None and override.strip():
        return override
    saved = template.get("model")
    return saved if isinstance(saved, str) and saved.strip() else None


@router.post(
    "/sessions/from_template/{template_id}",
    response_model=SessionOut,
    status_code=201,
)
async def instantiate_template(
    template_id: str,
    body: TemplateInstantiateRequest,
    request: Request,
) -> SessionOut:
    """Spawn a new session from a saved template.

    Field precedence is strict: request body wins over the template's
    saved value. The template acts as the default; the request is a
    one-off override. `working_dir` and `model` must resolve to a
    non-empty string after the fold — templates saved without one
    require the caller to supply one on the instantiate call (400
    otherwise). Tags that no longer exist are silently dropped."""
    conn = request.app.state.db
    template = await store.get_template(conn, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")

    working_dir = _resolved_working_dir(template, body.working_dir)
    model = _resolved_model(template, body.model)
    if working_dir is None:
        raise HTTPException(
            status_code=400,
            detail="working_dir required (template had none)",
        )
    if model is None:
        raise HTTPException(
            status_code=400,
            detail="model required (template had none)",
        )

    title = body.title if body.title is not None else template.get("name")
    instructions = (
        body.session_instructions
        if body.session_instructions is not None
        else template.get("session_instructions")
    )

    session_row = await store.create_session(
        conn,
        working_dir=working_dir,
        model=model,
        title=title if isinstance(title, str) else None,
    )

    # `session_instructions` isn't a direct `create_session` kwarg —
    # update_session owns the column. Apply it as a follow-up when set.
    if isinstance(instructions, str) and instructions.strip():
        await store.update_session(
            conn,
            session_row["id"],
            fields={"session_instructions": instructions},
        )

    # Attach only tags that still exist. Missing ids don't fail the
    # instantiate — the user gets a session with a smaller tag set.
    for tag_id in template.get("tag_ids", []) or []:
        if await store.get_tag(conn, tag_id) is not None:
            await store.attach_tag(conn, session_row["id"], tag_id)
    await store.ensure_default_severity(conn, session_row["id"])

    # Seed an initial user message from the template body (or caller
    # override). Empty string / null means "blank session."
    first_prompt = body.body if body.body is not None else template.get("body")
    if isinstance(first_prompt, str) and first_prompt.strip():
        await store.insert_message(
            conn,
            session_id=session_row["id"],
            role="user",
            content=first_prompt,
        )

    metrics.sessions_created.inc()
    metrics.templates_instantiated.inc()
    await publish_session_upsert(
        getattr(request.app.state, "sessions_broker", None), conn, session_row["id"]
    )
    refreshed = await store.get_session(conn, session_row["id"])
    assert refreshed is not None
    return SessionOut(**refreshed)
