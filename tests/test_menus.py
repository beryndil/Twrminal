"""Tests for the `menus.toml` loader (Phase 10).

Covers the contract documented in `docs/context-menu-plan.md` §8.6
(TOML loader). Key invariants the tests pin down:

  * Missing file → empty config (not an error). New installs work out
    of the box.
  * Malformed TOML → empty config + logged warning. A hand-edit typo
    should not brick the UI on boot.
  * Unknown target types / action IDs get silently dropped with a
    warning. Spec evolution renames an ID, the user's TOML from a
    prior release keeps booting.
  * Shape round-trips: `pinned`, `hidden`, `shortcuts` are preserved
    per target.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bearings.menus import (
    KNOWN_TARGET_TYPES,
    MenuConfig,
    TargetMenuConfig,
    load_menu_config,
)


def _write(path: Path, body: str) -> Path:
    path.write_text(body)
    return path


def test_missing_file_returns_empty_config(tmp_path: Path) -> None:
    missing = tmp_path / "menus.toml"
    cfg = load_menu_config(missing)
    assert isinstance(cfg, MenuConfig)
    assert cfg.by_target == {}


def test_empty_file_returns_empty_config(tmp_path: Path) -> None:
    path = _write(tmp_path / "menus.toml", "")
    cfg = load_menu_config(path)
    assert cfg.by_target == {}


def test_malformed_toml_returns_empty_config(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A typo in menus.toml must not bring the UI down — degrade to
    "no overrides" and log a warning so Dave knows to fix it."""
    import logging

    path = _write(tmp_path / "menus.toml", "this is = not = valid [toml")
    with caplog.at_level(logging.WARNING, logger="bearings.menus"):
        cfg = load_menu_config(path)
    assert cfg.by_target == {}
    assert any("parse error" in rec.message for rec in caplog.records)


def test_pinned_and_hidden_round_trip(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "menus.toml",
        """
        [session]
        pinned = ["session.copy_id", "session.pin"]
        hidden = ["session.copy_share_link"]

        [message]
        pinned = ["message.copy_id"]
        """,
    )
    cfg = load_menu_config(path)
    assert cfg.by_target["session"].pinned == [
        "session.copy_id",
        "session.pin",
    ]
    assert cfg.by_target["session"].hidden == ["session.copy_share_link"]
    assert cfg.by_target["message"].pinned == ["message.copy_id"]
    assert cfg.by_target["message"].hidden == []


def test_shortcuts_round_trip(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "menus.toml",
        """
        [session.shortcuts]
        "session.delete" = "ctrl+d"
        "session.pin" = "ctrl+p"
        """,
    )
    cfg = load_menu_config(path)
    entry = cfg.by_target["session"]
    assert entry.shortcuts == {
        "session.delete": "ctrl+d",
        "session.pin": "ctrl+p",
    }


def test_unknown_target_types_are_dropped(tmp_path: Path) -> None:
    """A target type that isn't in the canonical list — typo or a
    future target the backend hasn't learned yet — drops silently."""
    path = _write(
        tmp_path / "menus.toml",
        """
        [session]
        pinned = ["session.copy_id"]

        [sess1on]
        pinned = ["session.copy_id"]
        """,
    )
    cfg = load_menu_config(path)
    assert "session" in cfg.by_target
    assert "sess1on" not in cfg.by_target


def test_unknown_action_ids_survive(tmp_path: Path) -> None:
    """The loader doesn't know the canonical action-ID list (that's a
    frontend contract). Unknown IDs pass through — the frontend filters
    at merge time."""
    path = _write(
        tmp_path / "menus.toml",
        """
        [session]
        pinned = ["session.copy_id", "session.bogus_future_action"]
        """,
    )
    cfg = load_menu_config(path)
    assert cfg.by_target["session"].pinned == [
        "session.copy_id",
        "session.bogus_future_action",
    ]


def test_non_string_list_entries_are_skipped(tmp_path: Path) -> None:
    """A list with the wrong shape (`pinned = [1, "session.copy_id"]`)
    must not crash the loader. Non-strings drop, the rest survive."""
    path = _write(
        tmp_path / "menus.toml",
        """
        [session]
        pinned = ["session.copy_id", 1, true]
        """,
    )
    cfg = load_menu_config(path)
    assert cfg.by_target["session"].pinned == ["session.copy_id"]


def test_known_target_types_matches_frontend_union() -> None:
    """The backend's canonical list is the single source of truth for
    which target types the loader accepts. This test exists to force a
    sync update when a new target type lands in the frontend — the
    catalog is mirrored by hand so the loader can reject unknowns."""
    expected = {
        "session",
        "message",
        "tag",
        "tag_chip",
        "tool_call",
        "code_block",
        "link",
        "checkpoint",
        "multi_select",
    }
    assert set(KNOWN_TARGET_TYPES) == expected


def test_target_menu_config_defaults_are_empty() -> None:
    """The pydantic model defaults are empty containers, not None —
    consumers can iterate without null guards."""
    entry = TargetMenuConfig()
    assert entry.pinned == []
    assert entry.hidden == []
    assert entry.shortcuts == {}
