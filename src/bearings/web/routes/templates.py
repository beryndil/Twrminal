"""Template REST endpoints (G7).

Per ``docs/architecture-v1.md`` §1.1.5 every route group lives in its
own module; this one owns:

* ``POST /api/templates`` — create a template from a name + routing fields.
* ``GET /api/templates`` — list all templates, alphabetically by name.
* ``GET /api/templates/{id}`` — fetch one template by integer id.
* ``PATCH /api/templates/{id}`` — partial-update a template; missing
  fields are preserved from the existing row.
* ``DELETE /api/templates/{id}`` — delete one template; 204 on success.
* ``POST /api/templates/{id}/instantiate`` — create a session from a
  template, copying all fields atomically (gap-cycle-13-006).

Per ``docs/behavior/chat.md`` the new-session dialog accepts a template
selection that pre-populates the form fields. Per
``docs/behavior/context-menus.md`` §"Session row" the
``session.save_as_template`` action seeds a template from a live session's
routing/permission settings.

Handler bodies stay thin per arch §1.1.5: parse → single domain call →
shape adapter → response. Errors surface via :class:`HTTPException`
with structured ``detail`` strings — 404 for absent rows, 409 for name
collisions, 422 from Pydantic input validators (auto-emitted).
"""

from __future__ import annotations

from typing import cast

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, Response, status

from bearings.config.constants import (
    KNOWN_SDK_PERMISSION_MODES,
    PERMISSION_PROFILE_TO_SDK_MODE,
    TAG_CLASS_PROJECT,
    TAG_CLASS_SEVERITY,
)
from bearings.db import sessions as sessions_db
from bearings.db import tags as tags_db
from bearings.db import templates as templates_db
from bearings.db.sessions import Session
from bearings.db.templates import Template
from bearings.web.models.sessions import SessionOut
from bearings.web.models.templates import (
    TemplateIn,
    TemplateInstantiateIn,
    TemplateOut,
    TemplatePatch,
)
from bearings.web.routes.ws_sessions import SessionsBroadcaster

router = APIRouter()


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state`` (503 if absent)."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return cast(aiosqlite.Connection, db)


def _to_out(template: Template) -> TemplateOut:
    """Translate :class:`Template` to the wire shape."""
    return TemplateOut(
        id=template.id,
        name=template.name,
        description=template.description,
        model=template.model,
        advisor_model=template.advisor_model,
        advisor_max_uses=template.advisor_max_uses,
        effort_level=template.effort_level,
        permission_profile=template.permission_profile,
        system_prompt_baseline=template.system_prompt_baseline,
        working_dir_default=template.working_dir_default,
        tag_names=list(template.tag_names),
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


@router.post(
    "/api/templates",
    status_code=status.HTTP_201_CREATED,
    response_model=TemplateOut,
)
async def create_template(payload: TemplateIn, request: Request) -> TemplateOut:
    """Create a new template.

    409 when a template with ``payload.name`` already exists (the
    ``templates.name`` column carries a ``UNIQUE`` constraint). 422
    when the routing-alphabet fields are invalid (executor / advisor /
    effort / permission_profile).
    """
    db = _db(request)
    if await templates_db.get_by_name(db, payload.name) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a template named {payload.name!r} already exists",
        )
    try:
        template = await templates_db.create(
            db,
            name=payload.name,
            model=payload.model,
            description=payload.description,
            advisor_model=payload.advisor_model,
            advisor_max_uses=payload.advisor_max_uses,
            effort_level=payload.effort_level,
            permission_profile=payload.permission_profile,
            system_prompt_baseline=payload.system_prompt_baseline,
            working_dir_default=payload.working_dir_default,
            tag_names=tuple(payload.tag_names),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _to_out(template)


@router.get("/api/templates", response_model=list[TemplateOut])
async def list_templates(request: Request) -> list[TemplateOut]:
    """Every template, alphabetically by name.

    Returns ``[]`` when no templates have been created yet. The frontend
    template picker renders this list in a dropdown; an empty response
    means the picker shows only the "-- no template --" placeholder.
    """
    db = _db(request)
    rows = await templates_db.list_all(db)
    return [_to_out(row) for row in rows]


@router.get("/api/templates/{template_id}", response_model=TemplateOut)
async def get_template(template_id: int, request: Request) -> TemplateOut:
    """Fetch one template by integer id. 404 when absent."""
    db = _db(request)
    template = await templates_db.get(db, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no template matches id {template_id}",
        )
    return _to_out(template)


@router.patch("/api/templates/{template_id}", response_model=TemplateOut)
async def patch_template(template_id: int, payload: TemplatePatch, request: Request) -> TemplateOut:
    """Partial-update a template; missing fields are preserved from the existing row.

    The route fetches the existing row, merges the delta, then calls
    :func:`bearings.db.templates.update` with the full field set.

    404 when no template with ``template_id`` exists.
    409 when the requested ``name`` is already taken by another template.
    422 when the updated routing fields fall outside their allowed alphabets.
    """
    db = _db(request)
    existing = await templates_db.get(db, template_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no template matches id {template_id}",
        )
    # If the caller is changing the name, verify uniqueness against other rows.
    new_name = payload.name if payload.name is not None else existing.name
    if new_name != existing.name:
        collision = await templates_db.get_by_name(db, new_name)
        if collision is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"a template named {new_name!r} already exists",
            )
    # Merge delta onto the existing row.
    new_model = payload.model if payload.model is not None else existing.model
    new_description = (
        payload.description if "description" in payload.model_fields_set else existing.description
    )
    new_advisor_model = (
        payload.advisor_model
        if "advisor_model" in payload.model_fields_set
        else existing.advisor_model
    )
    new_advisor_max_uses = (
        payload.advisor_max_uses
        if payload.advisor_max_uses is not None
        else existing.advisor_max_uses
    )
    new_effort_level = (
        payload.effort_level if payload.effort_level is not None else existing.effort_level
    )
    new_permission_profile = (
        payload.permission_profile
        if payload.permission_profile is not None
        else existing.permission_profile
    )
    new_system_prompt = (
        payload.system_prompt_baseline
        if "system_prompt_baseline" in payload.model_fields_set
        else existing.system_prompt_baseline
    )
    new_working_dir = (
        payload.working_dir_default
        if "working_dir_default" in payload.model_fields_set
        else existing.working_dir_default
    )
    new_tag_names = (
        tuple(payload.tag_names) if payload.tag_names is not None else existing.tag_names
    )
    try:
        updated = await templates_db.update(
            db,
            template_id,
            name=new_name,
            model=new_model,
            description=new_description,
            advisor_model=new_advisor_model,
            advisor_max_uses=new_advisor_max_uses,
            effort_level=new_effort_level,
            permission_profile=new_permission_profile,
            system_prompt_baseline=new_system_prompt,
            working_dir_default=new_working_dir,
            tag_names=new_tag_names,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if updated is None:  # pragma: no cover — already confirmed existence above
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no template matches id {template_id}",
        )
    return _to_out(updated)


@router.delete(
    "/api/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_template(template_id: int, request: Request) -> None:
    """Delete one template; 204 on success, 404 when absent."""
    db = _db(request)
    removed = await templates_db.delete(db, template_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no template matches id {template_id}",
        )


def _sessions_broadcaster(request: Request) -> SessionsBroadcaster | None:
    """Pull the optional sessions broadcaster off ``app.state``."""
    return cast(
        SessionsBroadcaster | None,
        getattr(request.app.state, "sessions_broadcaster", None),
    )


def _session_to_out(session: Session) -> SessionOut:
    """Translate a :class:`Session` DB row to the sessions wire shape."""
    return SessionOut(
        id=session.id,
        kind=session.kind,
        title=session.title,
        description=session.description,
        session_instructions=session.session_instructions,
        working_dir=session.working_dir,
        model=session.model,
        permission_mode=session.permission_mode,
        max_budget_usd=session.max_budget_usd,
        total_cost_usd=session.total_cost_usd,
        message_count=session.message_count,
        last_context_pct=session.last_context_pct,
        last_context_tokens=session.last_context_tokens,
        last_context_max=session.last_context_max,
        pinned=session.pinned,
        error_pending=session.error_pending,
        checklist_item_id=session.checklist_item_id,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_viewed_at=session.last_viewed_at,
        last_completed_at=session.last_completed_at,
        closed_at=session.closed_at,
        closing_summary=session.closing_summary,
        pivot_message_id=session.pivot_message_id,
        parent_session_id=session.parent_session_id,
    )


async def _validate_tag_cardinality_local(
    db: aiosqlite.Connection,
    tag_ids: tuple[int, ...],
) -> None:
    """Reject tag-id sets violating the ≤1 project / ≤1 severity rule.

    Mirrors the same check in :mod:`bearings.web.routes.sessions` without
    importing a private function from that module.
    """
    if not tag_ids:
        return
    placeholders = ",".join("?" * len(tag_ids))
    cursor = await db.execute(
        f"SELECT id, class FROM tags WHERE id IN ({placeholders})",
        tag_ids,
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    by_class: dict[str, list[int]] = {}
    for row in rows:
        by_class.setdefault(str(row[1]), []).append(int(str(row[0])))
    project_ids = by_class.get(TAG_CLASS_PROJECT, [])
    severity_ids = by_class.get(TAG_CLASS_SEVERITY, [])
    violations: list[str] = []
    if len(project_ids) > 1:
        violations.append(f"≤1 project tag allowed (got {sorted(project_ids)})")
    if len(severity_ids) > 1:
        violations.append(f"≤1 severity tag allowed (got {sorted(severity_ids)})")
    if violations:
        message = "; ".join(violations)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{message}",
        )


@router.post(
    "/api/templates/{template_id}/instantiate",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_session_from_template(
    template_id: int,
    payload: TemplateInstantiateIn,
    request: Request,
    response: Response,
) -> SessionOut:
    """Create a new session from a template (gap-cycle-13-006).

    Copies all template fields into a new session row in one sequence of
    DB calls.  The caller may supply an optional override body to replace
    any inherited field; omitted fields use the template's stored values.

    Field mapping (template field → session field):

    * ``name`` → ``title`` (override: ``payload.title``).
    * ``model`` → ``model`` (override: ``payload.model``).
    * ``description`` → ``description`` (override: ``payload.description``).
    * ``working_dir_default`` → ``working_dir`` (override: ``payload.working_dir``).
    * ``system_prompt_baseline`` → ``session_instructions``
      (override: ``payload.session_instructions``).
    * ``permission_profile`` → ``permission_mode`` — empty string maps to
      ``None`` (override: ``payload.permission_mode``).
    * ``advisor_model`` → ``routing_advisor_model``
      (override: ``payload.advisor_model``).
    * ``advisor_max_uses`` → ``routing_advisor_max_uses``
      (override: ``payload.advisor_max_uses``).
    * ``effort_level`` → ``routing_effort_level``
      (override: ``payload.effort_level``).
    * ``tag_names`` → resolved to tag ids and attached after session creation.
      Names that do not match an existing tag are silently skipped.

    ``working_dir`` resolution order: payload override → template
    ``working_dir_default`` → first resolved tag whose ``working_dir`` is
    set → 422 if none provide a directory.

    Responses:

    * ``201`` — new session row; ``Location: /api/sessions/<id>``.
    * ``404`` — template not found.
    * ``422`` — no working_dir resolvable, or routing fields out of range.
    """
    db = _db(request)
    template = await templates_db.get(db, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no template matches id {template_id}",
        )

    # -- Resolve tag_names → tag_ids (skip names that no longer exist). ---
    resolved_tag_ids: list[int] = []
    for name in template.tag_names:
        tag = await tags_db.get_by_name(db, name)
        if tag is not None:
            resolved_tag_ids.append(tag.id)
    tag_ids = tuple(resolved_tag_ids)
    if tag_ids:
        await _validate_tag_cardinality_local(db, tag_ids)

    # -- Resolve working_dir: override > template > tag fallback > 422. ---
    resolved_working_dir: str | None = (
        payload.working_dir if payload.working_dir is not None else template.working_dir_default
    )
    if resolved_working_dir is None and tag_ids:
        tag_list = [t for t in await tags_db.list_all(db) if t.id in set(tag_ids)]
        for tid in tag_ids:
            tag = next((t for t in tag_list if t.id == tid), None)
            if tag is not None and tag.working_dir is not None:
                resolved_working_dir = tag.working_dir
                break
    if resolved_working_dir is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "working_dir is required — supply it via the override body, "
                "set working_dir_default on the template, or attach a tag with a working_dir set"
            ),
        )

    # -- Map permission_profile → permission_mode. -------------------------
    # Caller override takes precedence. Otherwise, convert the template's
    # permission_profile (a Bearings profile name or raw SDK mode) to the
    # SDK-level permission_mode the session layer expects:
    #   "standard"   → "acceptEdits"
    #   "restricted" → "default"
    #   "expanded"   → "bypassPermissions"
    #   ""           → None
    #   raw SDK mode → passed through unchanged
    #   unknown      → None (don't fail instantiation over a stale profile)
    if payload.permission_mode is not None:
        permission_mode: str | None = payload.permission_mode
    elif template.permission_profile == "":
        permission_mode = None
    elif template.permission_profile in PERMISSION_PROFILE_TO_SDK_MODE:
        permission_mode = PERMISSION_PROFILE_TO_SDK_MODE[template.permission_profile]
    elif template.permission_profile in KNOWN_SDK_PERMISSION_MODES:
        permission_mode = template.permission_profile
    else:
        permission_mode = None

    # -- Merge overrides onto template fields. ----------------------------
    title = payload.title if payload.title is not None else template.name
    model = payload.model if payload.model is not None else template.model
    description = (
        payload.description if "description" in payload.model_fields_set else template.description
    )
    session_instructions = (
        payload.session_instructions
        if "session_instructions" in payload.model_fields_set
        else template.system_prompt_baseline
    )
    advisor_model = (
        payload.advisor_model
        if "advisor_model" in payload.model_fields_set
        else template.advisor_model
    )
    advisor_max_uses = (
        payload.advisor_max_uses
        if payload.advisor_max_uses is not None
        else template.advisor_max_uses
    )
    effort_level = (
        payload.effort_level if payload.effort_level is not None else template.effort_level
    )

    # -- Create session row. ----------------------------------------------
    try:
        row = await sessions_db.create(
            db,
            kind="chat",
            title=title,
            working_dir=resolved_working_dir,
            model=model,
            description=description,
            session_instructions=session_instructions,
            permission_mode=permission_mode,
            max_budget_usd=None,
            routing_advisor_model=advisor_model,
            routing_advisor_max_uses=advisor_max_uses,
            routing_effort_level=effort_level,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # -- Attach resolved tags. --------------------------------------------
    if tag_ids:
        await tags_db.set_for_session(db, session_id=row.id, tag_ids=tag_ids)

    out = _session_to_out(row)
    broadcaster = _sessions_broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_upsert(out)
    response.headers["Location"] = f"/api/sessions/{row.id}"
    return out


__all__ = ["router"]
