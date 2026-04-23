"""UI-facing config surface.

Exposes only the settings the frontend needs to know at boot — billing
mode, plan slug, and the parsed `menus.toml` overrides for the
context-menu registry. Anything sensitive (auth tokens, absolute DB
path) stays server-side; this endpoint is deliberately a narrow
allow-list.

The `context_menus` field is the Phase 10 customization layer: per
target type the user can pin actions to the top, hide actions
entirely (they stay reachable via Ctrl+Shift+P), and rebind shortcut
chords. Shape mirrors `bearings.menus.MenuConfig` exactly —
`by_target[target_type].{pinned, hidden, shortcuts}` — so the
frontend can merge it into `resolveMenu` without any translation
layer. Empty-config fallback means a fresh install (no menus.toml)
serves `context_menus = {by_target: {}}` and the registry renders
its defaults unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from bearings.config import BillingMode
from bearings.menus import MenuConfig

router = APIRouter(tags=["config"])


class UiConfigOut(BaseModel):
    """Minimal knob surface the frontend reads at startup.

    `billing_mode` drives the cost-vs-tokens display swap on session
    cards and the conversation header. `billing_plan` is informational
    only (currently just echoed back) so a future release can badge
    the header with the user's plan slug without a second endpoint.
    `context_menus` carries the parsed `menus.toml` overrides — see
    `bearings.menus` for the field-level contract."""

    billing_mode: BillingMode
    billing_plan: str | None = None
    context_menus: MenuConfig = Field(default_factory=MenuConfig)


@router.get("/ui-config", response_model=UiConfigOut)
async def get_ui_config(request: Request) -> UiConfigOut:
    settings = request.app.state.settings
    menus: MenuConfig = getattr(request.app.state, "menus", MenuConfig())
    return UiConfigOut(
        billing_mode=settings.billing.mode,
        billing_plan=settings.billing.plan,
        context_menus=menus,
    )
