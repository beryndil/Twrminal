"""Template REST endpoints (G7).

Per ``docs/architecture-v1.md`` §1.1.5 every route group lives in its
own module; this one owns:

* ``POST /api/templates`` — create a template from a name + routing fields.
* ``GET /api/templates`` — list all templates, alphabetically by name.
* ``GET /api/templates/{id}`` — fetch one template by integer id.
* ``PATCH /api/templates/{id}`` — partial-update a template; missing
  fields are preserved from the existing row.
* ``DELETE /api/templates/{id}`` — delete one template; 204 on success.

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
from fastapi import APIRouter, HTTPException, Request, status

from bearings.db import templates as templates_db
from bearings.db.templates import Template
from bearings.web.models.templates import TemplateIn, TemplateOut, TemplatePatch

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


__all__ = ["router"]
