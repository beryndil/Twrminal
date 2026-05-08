"""Tag rule + system rule + preview endpoints (spec §9).

Endpoints (spec §9 verbatim):

* ``GET    /api/tags/{id}/routing`` — list rules for tag.
* ``POST   /api/tags/{id}/routing`` — add rule.
* ``PATCH  /api/routing/{id}`` — update tag rule.
* ``DELETE /api/routing/{id}`` — delete tag rule.
* ``PATCH  /api/tags/{id}/routing/reorder`` — re-prioritise.
* ``GET    /api/routing/system`` — list system rules.
* ``POST   /api/routing/system`` — add system rule.
* ``PATCH  /api/routing/system/{id}`` — update system rule.
* ``DELETE /api/routing/system/{id}`` — delete system rule.
* ``POST   /api/routing/preview`` — evaluate against an input message.

Spec note: ``PATCH /api/routing/{id}`` is documented as "(tag or
system)". Item 1.8 implements it as the tag-rule endpoint and reserves
``/api/routing/system/{id}`` for system rules — id-namespace
disambiguation per ``RoutingRule.id`` and ``SystemRoutingRule.id``
sitting in independent ``AUTOINCREMENT`` sequences. Decided-and-
documented: a single shared endpoint would need a query parameter to
disambiguate, which is no simpler than two paths and harder to test.

Handler bodies are thin per arch §1.1.5: argument parsing, single
domain call, response formatting. 404 on missing rule, 422 on bad
shape, 409 on FK violation (tag does not exist), 502 reserved for
quota/usage when upstream is unreachable (the quota endpoints raise
that).
"""

from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, status

from bearings.agent.quota import (
    apply_quota_guard,
    load_latest,
)
from bearings.agent.routing import RoutingDecision, evaluate
from bearings.db import routing as routing_db
from bearings.db.routing import RoutingRule, SystemRoutingRule
from bearings.web.models.routing import (
    RoutingPreviewIn,
    RoutingPreviewOut,
    RoutingReorderIn,
    RoutingRuleIn,
    RoutingRuleOut,
    SystemRoutingRuleIn,
    SystemRoutingRuleOut,
)
from bearings.web.routes._deps import _db, _quota_poller

router = APIRouter()


def _tag_rule_to_out(rule: RoutingRule) -> RoutingRuleOut:
    return RoutingRuleOut(
        id=rule.id,
        tag_id=rule.tag_id,
        priority=rule.priority,
        enabled=rule.enabled,
        match_type=rule.match_type,
        match_value=rule.match_value,
        executor_model=rule.executor_model,
        advisor_model=rule.advisor_model,
        advisor_max_uses=rule.advisor_max_uses,
        effort_level=rule.effort_level,
        reason=rule.reason,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _system_rule_to_out(rule: SystemRoutingRule) -> SystemRoutingRuleOut:
    return SystemRoutingRuleOut(
        id=rule.id,
        priority=rule.priority,
        enabled=rule.enabled,
        match_type=rule.match_type,
        match_value=rule.match_value,
        executor_model=rule.executor_model,
        advisor_model=rule.advisor_model,
        advisor_max_uses=rule.advisor_max_uses,
        effort_level=rule.effort_level,
        reason=rule.reason,
        seeded=rule.seeded,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _decision_to_preview(
    decision: RoutingDecision,
    *,
    pre_guard_source: str,
) -> RoutingPreviewOut:
    """Project a post-guard :class:`RoutingDecision` onto the preview shape.

    ``pre_guard_source`` is the source the evaluator returned before
    the guard ran; if the post-guard source is ``'quota_downgrade'``
    the preview reports ``quota_downgrade_applied = True`` (spec §9
    bool field).
    """
    return RoutingPreviewOut(
        executor=decision.executor_model,
        advisor=decision.advisor_model,
        advisor_max_uses=decision.advisor_max_uses,
        effort=decision.effort_level,
        source=decision.source,
        reason=decision.reason,
        matched_rule_id=decision.matched_rule_id,
        evaluated_rules=list(decision.evaluated_rules),
        quota_downgrade_applied=(
            decision.source == "quota_downgrade" and pre_guard_source != "quota_downgrade"
        ),
        quota_state=dict(decision.quota_state_at_decision),
    )


# ---------------------------------------------------------------------------
# Tag rule CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/api/tags/{tag_id}/routing",
    response_model=list[RoutingRuleOut],
    operation_id="list-tag-routing-rules",
)
async def list_tag_rules(tag_id: int, request: Request) -> list[RoutingRuleOut]:
    """Every routing rule attached to ``tag_id``, ordered by priority."""
    db = _db(request)
    rows = await routing_db.list_for_tag(db, tag_id)
    return [_tag_rule_to_out(r) for r in rows]


@router.post(
    "/api/tags/{tag_id}/routing",
    status_code=status.HTTP_201_CREATED,
    response_model=RoutingRuleOut,
    operation_id="create-tag-routing-rule",
)
async def create_tag_rule(
    tag_id: int,
    payload: RoutingRuleIn,
    request: Request,
) -> RoutingRuleOut:
    """Create a tag rule; 422 on bad shape, 404 if the tag does not exist."""
    db = _db(request)
    try:
        rule = await routing_db.create_tag_rule(
            db,
            tag_id=tag_id,
            priority=payload.priority,
            enabled=payload.enabled,
            match_type=payload.match_type,
            match_value=payload.match_value,
            executor_model=payload.executor_model,
            advisor_model=payload.advisor_model,
            advisor_max_uses=payload.advisor_max_uses,
            effort_level=payload.effort_level,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except aiosqlite.IntegrityError as exc:
        # Only FK violations on tag_id map to 404; UNIQUE/CHECK violations
        # must not silently surface as "tag not found" (finding feature-3-005).
        if "FOREIGN KEY" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"tag {tag_id} not found",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"constraint violation: {exc}",
        ) from exc
    return _tag_rule_to_out(rule)


@router.patch(
    "/api/routing/{rule_id}",
    response_model=RoutingRuleOut,
    operation_id="update-routing-rule",
)
async def update_tag_rule(
    rule_id: int,
    payload: RoutingRuleIn,
    request: Request,
) -> RoutingRuleOut:
    """Replace a tag rule's mutable fields; 404 if absent, 422 on bad shape."""
    db = _db(request)
    try:
        rule = await routing_db.update_tag_rule(
            db,
            rule_id,
            priority=payload.priority,
            enabled=payload.enabled,
            match_type=payload.match_type,
            match_value=payload.match_value,
            executor_model=payload.executor_model,
            advisor_model=payload.advisor_model,
            advisor_max_uses=payload.advisor_max_uses,
            effort_level=payload.effort_level,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"routing rule {rule_id} not found",
        )
    return _tag_rule_to_out(rule)


@router.delete(
    "/api/routing/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete-routing-rule",
)
async def delete_tag_rule(rule_id: int, request: Request) -> None:
    """Delete a tag rule; 404 if it didn't exist."""
    db = _db(request)
    removed = await routing_db.delete_tag_rule(db, rule_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"routing rule {rule_id} not found",
        )


@router.patch(
    "/api/tags/{tag_id}/routing/reorder",
    response_model=list[RoutingRuleOut],
    operation_id="reorder-tag-routing-rules",
)
async def reorder_tag_rules(
    tag_id: int,
    payload: RoutingReorderIn,
    request: Request,
) -> list[RoutingRuleOut]:
    """Re-stamp priorities to match the supplied id order."""
    db = _db(request)
    try:
        rows = await routing_db.reorder_tag_rules(
            db,
            tag_id,
            payload.ids_in_priority_order,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return [_tag_rule_to_out(r) for r in rows]


# ---------------------------------------------------------------------------
# System rule CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/api/routing/system",
    response_model=list[SystemRoutingRuleOut],
    operation_id="list-system-routing-rules",
)
async def list_system_rules(request: Request) -> list[SystemRoutingRuleOut]:
    """Every system rule, ordered by priority."""
    db = _db(request)
    rows = await routing_db.list_system_rules(db)
    return [_system_rule_to_out(r) for r in rows]


@router.post(
    "/api/routing/system",
    status_code=status.HTTP_201_CREATED,
    response_model=SystemRoutingRuleOut,
    operation_id="create-system-routing-rule",
)
async def create_system_rule(
    payload: SystemRoutingRuleIn,
    request: Request,
) -> SystemRoutingRuleOut:
    """Create a user-added system rule (``seeded = 0``)."""
    db = _db(request)
    try:
        rule = await routing_db.create_system_rule(
            db,
            priority=payload.priority,
            enabled=payload.enabled,
            match_type=payload.match_type,
            match_value=payload.match_value,
            executor_model=payload.executor_model,
            advisor_model=payload.advisor_model,
            advisor_max_uses=payload.advisor_max_uses,
            effort_level=payload.effort_level,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return _system_rule_to_out(rule)


@router.patch(
    "/api/routing/system/{rule_id}",
    response_model=SystemRoutingRuleOut,
    operation_id="update-system-routing-rule",
)
async def update_system_rule(
    rule_id: int,
    payload: SystemRoutingRuleIn,
    request: Request,
) -> SystemRoutingRuleOut:
    """Replace a system rule's mutable fields; preserves ``seeded``."""
    db = _db(request)
    try:
        rule = await routing_db.update_system_rule(
            db,
            rule_id,
            priority=payload.priority,
            enabled=payload.enabled,
            match_type=payload.match_type,
            match_value=payload.match_value,
            executor_model=payload.executor_model,
            advisor_model=payload.advisor_model,
            advisor_max_uses=payload.advisor_max_uses,
            effort_level=payload.effort_level,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"system rule {rule_id} not found",
        )
    return _system_rule_to_out(rule)


@router.delete(
    "/api/routing/system/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete-system-routing-rule",
)
async def delete_system_rule(rule_id: int, request: Request) -> None:
    """Delete a system rule; 404 if it didn't exist."""
    db = _db(request)
    removed = await routing_db.delete_system_rule(db, rule_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"system rule {rule_id} not found",
        )


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@router.post(
    "/api/routing/preview",
    response_model=RoutingPreviewOut,
    operation_id="preview-routing",
)
async def preview_routing(
    payload: RoutingPreviewIn,
    request: Request,
) -> RoutingPreviewOut:
    """Evaluate routing against the supplied tags + first message.

    The new-session dialog calls this on every keystroke (debounced
    300ms per spec §6) so the routing-preview line updates as the
    user types. Body shape per spec §9:
    ``{ tags: [ids], message: "..." }``.
    Response carries ``quota_downgrade_applied`` so the dialog can
    render the yellow banner with the "Use anyway" override action.

    The endpoint runs both ``evaluate`` (pure) and
    ``apply_quota_guard`` (pure on top of the latest snapshot). If a
    poller is configured, ``poller.latest`` is the snapshot; otherwise
    the route falls back to :func:`bearings.agent.quota.load_latest`.
    """
    db = _db(request)
    poller = _quota_poller(request)
    snapshot = None
    if poller is not None:
        snapshot = poller.latest
    if snapshot is None:
        snapshot = await load_latest(db)
    tags_with_rules = await routing_db.list_for_tags(
        db,
        payload.tags,
        enabled_only=True,
    )
    system_rules = await routing_db.list_system_rules(db, enabled_only=True)
    raw_decision = evaluate(
        payload.message,
        tags_with_rules,
        system_rules,
        snapshot,
    )
    final_decision = apply_quota_guard(raw_decision, snapshot)
    return _decision_to_preview(
        final_decision,
        pre_guard_source=raw_decision.source,
    )


__all__ = ["router"]
