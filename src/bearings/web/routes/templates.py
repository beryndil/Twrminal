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

from typing import TypedDict, cast

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, Response, status

from bearings.config.constants import (
    KNOWN_SDK_PERMISSION_MODES,
    PERMISSION_PROFILE_TO_SDK_MODE,
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
from bearings.web.routes.tags import _validate_tag_cardinality
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
    operation_id="create-template",
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


@router.get("/api/templates", response_model=list[TemplateOut], operation_id="list-templates")
async def list_templates(request: Request) -> list[TemplateOut]:
    """Every template, alphabetically by name.

    Returns ``[]`` when no templates have been created yet. The frontend
    template picker renders this list in a dropdown; an empty response
    means the picker shows only the "-- no template --" placeholder.
    """
    db = _db(request)
    rows = await templates_db.list_all(db)
    return [_to_out(row) for row in rows]


@router.get("/api/templates/{template_id}", response_model=TemplateOut, operation_id="get-template")
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


class _TemplatePatchMerged(TypedDict):
    model: str
    description: str | None
    advisor_model: str | None
    advisor_max_uses: int
    effort_level: str
    permission_profile: str
    system_prompt_baseline: str | None
    working_dir_default: str | None
    tag_names: tuple[str, ...]


class _TemplateInstantiateMerged(TypedDict):
    title: str
    model: str
    description: str | None
    session_instructions: str | None
    advisor_model: str | None
    advisor_max_uses: int
    effort_level: str


def _merge_template_patch(payload: TemplatePatch, existing: Template) -> _TemplatePatchMerged:
    """Merge a :class:`TemplatePatch` delta onto an existing row; return merged dict."""
    fs = payload.model_fields_set
    return {
        "model": payload.model if payload.model is not None else existing.model,
        "description": payload.description if "description" in fs else existing.description,
        "advisor_model": payload.advisor_model if "advisor_model" in fs else existing.advisor_model,
        "advisor_max_uses": (
            payload.advisor_max_uses
            if payload.advisor_max_uses is not None
            else existing.advisor_max_uses
        ),
        "effort_level": (
            payload.effort_level if payload.effort_level is not None else existing.effort_level
        ),
        "permission_profile": (
            payload.permission_profile
            if payload.permission_profile is not None
            else existing.permission_profile
        ),
        "system_prompt_baseline": (
            payload.system_prompt_baseline
            if "system_prompt_baseline" in fs
            else existing.system_prompt_baseline
        ),
        "working_dir_default": (
            payload.working_dir_default
            if "working_dir_default" in fs
            else existing.working_dir_default
        ),
        "tag_names": (
            tuple(payload.tag_names) if payload.tag_names is not None else existing.tag_names
        ),
    }


@router.patch(
    "/api/templates/{template_id}",
    response_model=TemplateOut,
    operation_id="patch-template",
)
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
    merged = _merge_template_patch(payload, existing)
    try:
        updated = await templates_db.update(
            db,
            template_id,
            name=new_name,
            model=merged["model"],
            description=merged["description"],
            advisor_model=merged["advisor_model"],
            advisor_max_uses=merged["advisor_max_uses"],
            effort_level=merged["effort_level"],
            permission_profile=merged["permission_profile"],
            system_prompt_baseline=merged["system_prompt_baseline"],
            working_dir_default=merged["working_dir_default"],
            tag_names=merged["tag_names"],
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
    operation_id="delete-template",
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


def _merge_instantiate_fields(
    payload: TemplateInstantiateIn,
    template: Template,
) -> _TemplateInstantiateMerged:
    """Merge payload overrides onto template fields; return merged dict."""
    fs = payload.model_fields_set
    return {
        "title": payload.title if payload.title is not None else template.name,
        "model": payload.model if payload.model is not None else template.model,
        "description": payload.description if "description" in fs else template.description,
        "session_instructions": (
            payload.session_instructions
            if "session_instructions" in fs
            else template.system_prompt_baseline
        ),
        "advisor_model": (
            payload.advisor_model if "advisor_model" in fs else template.advisor_model
        ),
        "advisor_max_uses": (
            payload.advisor_max_uses
            if payload.advisor_max_uses is not None
            else template.advisor_max_uses
        ),
        "effort_level": (
            payload.effort_level if payload.effort_level is not None else template.effort_level
        ),
    }


async def _resolve_template_tag_ids(
    db: aiosqlite.Connection,
    template: Template,
) -> tuple[int, ...]:
    """Resolve template.tag_names → existing tag ids (silently skip missing)."""
    resolved: list[int] = []
    for name in template.tag_names:
        tag = await tags_db.get_by_name(db, name)
        if tag is not None:
            resolved.append(tag.id)
    return tuple(resolved)


async def _tag_working_dir_fallback(
    db: aiosqlite.Connection,
    tag_ids: tuple[int, ...],
) -> str | None:
    """Return the first working_dir from the ordered tag_ids, or None."""
    tag_map = {t.id: t for t in await tags_db.list_all(db)}
    for tid in tag_ids:
        tag = tag_map.get(tid)
        if tag is not None and tag.working_dir:
            return tag.working_dir
    return None


async def _resolve_template_working_dir(
    db: aiosqlite.Connection,
    payload: TemplateInstantiateIn,
    template: Template,
    tag_ids: tuple[int, ...],
) -> str | None:
    """Resolve working_dir: payload override → template default → tag fallback."""
    if payload.working_dir is not None:
        return payload.working_dir
    if template.working_dir_default is not None:
        return template.working_dir_default
    return await _tag_working_dir_fallback(db, tag_ids) if tag_ids else None


def _resolve_template_permission_mode(
    payload: TemplateInstantiateIn,
    template: Template,
) -> str | None:
    """Map template permission_profile → SDK permission_mode.

    Caller override takes precedence. Otherwise converts the template's
    permission_profile (a Bearings profile name or raw SDK mode) to the
    SDK-level permission_mode the session layer expects.
    """
    if payload.permission_mode is not None:
        return payload.permission_mode
    if template.permission_profile == "":
        return None
    if template.permission_profile in PERMISSION_PROFILE_TO_SDK_MODE:
        return PERMISSION_PROFILE_TO_SDK_MODE[template.permission_profile]
    if template.permission_profile in KNOWN_SDK_PERMISSION_MODES:
        return template.permission_profile
    return None


@router.post(
    "/api/templates/{template_id}/instantiate",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="instantiate-template",
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

    tag_ids = await _resolve_template_tag_ids(db, template)
    if tag_ids:
        await _validate_tag_cardinality(db, tag_ids)

    resolved_working_dir = await _resolve_template_working_dir(db, payload, template, tag_ids)
    if resolved_working_dir is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "working_dir is required — supply it via the override body, "
                "set working_dir_default on the template, or attach a tag with a working_dir set"
            ),
        )

    permission_mode = _resolve_template_permission_mode(payload, template)

    # Merge payload overrides onto template fields.
    merged = _merge_instantiate_fields(payload, template)

    # -- Create session row. ----------------------------------------------
    try:
        row = await sessions_db.create(
            db,
            kind="chat",
            title=merged["title"],
            working_dir=resolved_working_dir,
            model=merged["model"],
            description=merged["description"],
            session_instructions=merged["session_instructions"],
            permission_mode=permission_mode,
            max_budget_usd=None,
            routing_advisor_model=merged["advisor_model"],
            routing_advisor_max_uses=merged["advisor_max_uses"],
            routing_effort_level=merged["effort_level"],
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
