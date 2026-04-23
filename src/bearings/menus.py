"""`menus.toml` loader — Phase 10 of docs/context-menu-plan.md.

Reads `~/.config/bearings/menus.toml` at boot and exposes the parsed
shape so the frontend can merge user overrides on top of the built-in
context-menu registry. Overrides cover three axes per target type:

  * `pinned` — action IDs the user wants floated to the top of the
    menu in the listed order.
  * `hidden` — action IDs the user never wants to see (still
    reachable via the Ctrl+Shift+P command palette).
  * `shortcuts` — `{action_id -> key_chord}` rebindings that the
    frontend keyboard FSM picks up.

Design notes:

  * **No hot reload in Phase 10.** Spec calls for a server restart to
    reload overrides; that keeps the loader dead-simple and avoids
    a filesystem-watch dependency. A later phase can grow this.
  * **Soft-fail on parse errors.** A typo in menus.toml must never
    brick the UI. Missing file, empty file, or malformed TOML all
    degrade to an empty config + a logged warning so Dave notices
    on server boot.
  * **Canonical target list.** We keep `KNOWN_TARGET_TYPES` mirrored
    from the frontend's `ContextTarget` union. A test in
    `test_menus.py` catches drift if a new target type lands.
  * **Action-ID validation is frontend-side.** The loader doesn't
    know the canonical action-ID list — that contract lives in the
    per-target `*_ACTIONS` arrays. Unknown IDs pass through;
    resolveMenu filters at merge time.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

_log = logging.getLogger(__name__)

# Mirror of the frontend's `ContextTarget['type']` discriminator.
# `test_known_target_types_matches_frontend_union` guards the drift.
KNOWN_TARGET_TYPES: tuple[str, ...] = (
    "session",
    "message",
    "tag",
    "tag_chip",
    "tool_call",
    "code_block",
    "link",
    "checkpoint",
    "multi_select",
)


class TargetMenuConfig(BaseModel):
    """User overrides for one target type. All three fields default
    to empty so callers can iterate without null guards."""

    pinned: list[str] = Field(default_factory=list)
    hidden: list[str] = Field(default_factory=list)
    shortcuts: dict[str, str] = Field(default_factory=dict)


class MenuConfig(BaseModel):
    """Top-level parsed shape. `by_target` keys off target type; the
    loader drops any target name that isn't in `KNOWN_TARGET_TYPES`."""

    by_target: dict[str, TargetMenuConfig] = Field(default_factory=dict)


def _coerce_string_list(raw: Any) -> list[str]:
    """Accept a list from TOML and keep only string elements. A hand-
    edited file with mixed types (int / bool snuck in) must not crash
    — drop the bad entries, keep the rest."""
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str)]


def _coerce_string_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}


def _parse_target(name: str, raw: Any) -> TargetMenuConfig | None:
    """Turn one `[session]` / `[message]` block into a TargetMenuConfig.
    Returns None for non-dict payloads (e.g. the TOML had `session =
    "foo"` instead of a table) so the caller can skip the entry."""
    if not isinstance(raw, dict):
        _log.warning("menus.toml: target %s is not a table, ignoring", name)
        return None
    return TargetMenuConfig(
        pinned=_coerce_string_list(raw.get("pinned")),
        hidden=_coerce_string_list(raw.get("hidden")),
        shortcuts=_coerce_string_map(raw.get("shortcuts")),
    )


def load_menu_config(path: Path) -> MenuConfig:
    """Parse `menus.toml` into a MenuConfig.

    Four degenerate paths all land on an empty config:
      * file doesn't exist
      * file is empty
      * file is malformed TOML
      * file is a TOML document with zero known target tables

    Each non-happy path logs a warning — the UI boots with defaults.
    """
    if not path.exists():
        return MenuConfig()
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        _log.warning("menus.toml: could not read %s (%s)", path, exc)
        return MenuConfig()
    if not raw_bytes.strip():
        return MenuConfig()
    try:
        data = tomllib.loads(raw_bytes.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        _log.warning("menus.toml: parse error at %s (%s)", path, exc)
        return MenuConfig()

    by_target: dict[str, TargetMenuConfig] = {}
    for name, payload in data.items():
        if name not in KNOWN_TARGET_TYPES:
            _log.warning(
                "menus.toml: unknown target type %r — ignoring (known: %s)",
                name,
                ", ".join(KNOWN_TARGET_TYPES),
            )
            continue
        parsed = _parse_target(name, payload)
        if parsed is not None:
            by_target[name] = parsed
    return MenuConfig(by_target=by_target)
