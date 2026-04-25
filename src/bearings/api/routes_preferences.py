"""GET + PATCH for the singleton preferences row (migration 0026).

The route surface is deliberately tiny: one record, one GET, one
PATCH. No DELETE in v1 — "reset to defaults" is a follow-up if anyone
asks. No POST — the seed row is created at migration time, so the
notion of "create a preferences record" doesn't exist.

PATCH semantics: the body uses Pydantic's `model_dump(exclude_unset=
True)` so only fields the client explicitly sent are forwarded to the
store layer. An empty PATCH body is legal — it lands as a pure
`updated_at` bump, which is what an "I touched the form but changed
nothing" submit should do (and which the frontend's seed-state
detector relies on to flip off, even though nothing else changed).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from bearings.api.auth import require_auth
from bearings.api.models import PreferencesOut, PreferencesPatch
from bearings.db import store

router = APIRouter(
    prefix="/preferences",
    tags=["preferences"],
    dependencies=[Depends(require_auth)],
)


@router.get("", response_model=PreferencesOut)
async def get_preferences(request: Request) -> PreferencesOut:
    row = await store.get_preferences(request.app.state.db)
    return PreferencesOut(**_strip_id(row))


@router.patch("", response_model=PreferencesOut)
async def patch_preferences(body: PreferencesPatch, request: Request) -> PreferencesOut:
    """Partial update. Only fields the client explicitly set are
    forwarded; unset fields keep their current value."""
    fields = body.model_dump(exclude_unset=True)
    row = await store.update_preferences(request.app.state.db, **fields)
    return PreferencesOut(**_strip_id(row))


def _strip_id(row: dict[str, Any]) -> dict[str, Any]:
    """The store layer returns the full row including `id` (always 1
    by CHECK constraint). The wire DTO doesn't surface `id` since the
    record is a singleton and the client has no use for it. Drop it
    here so a stray pydantic-extra-fields config doesn't bite later."""
    return {k: v for k, v in row.items() if k != "id"}
