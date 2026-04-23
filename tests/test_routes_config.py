"""Tests for the `/api/ui-config` route.

The endpoint is read-only, tiny, and only exposes two fields — but it
drives the cost-vs-tokens swap throughout the frontend, so regressions
are high-impact. These tests guard:
  - the shape of the response (exact two keys, correct types)
  - that the TOML knob round-trips into the served value
  - that the default is `payg` so PAYG users see no change
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearings.config import BillingCfg, Settings, StorageCfg
from bearings.server import create_app


def _client(cfg: Settings) -> TestClient:
    app: FastAPI = create_app(cfg)
    return TestClient(app)


@pytest.fixture
def tmp_storage(tmp_path: Path) -> Path:
    return tmp_path / "db.sqlite"


def test_ui_config_defaults_to_payg(tmp_storage: Path, tmp_path: Path) -> None:
    cfg = Settings(
        storage=StorageCfg(db_path=tmp_storage),
        menus_file=tmp_path / "menus.toml",
    )
    with _client(cfg) as client:
        resp = client.get("/api/ui-config")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "billing_mode": "payg",
            "billing_plan": None,
            "context_menus": {"by_target": {}},
        }


def test_ui_config_reflects_subscription_mode(tmp_storage: Path, tmp_path: Path) -> None:
    cfg = Settings(
        storage=StorageCfg(db_path=tmp_storage),
        menus_file=tmp_path / "menus.toml",
        billing=BillingCfg(mode="subscription", plan="max_20x"),
    )
    with _client(cfg) as client:
        body = client.get("/api/ui-config").json()
        assert body == {
            "billing_mode": "subscription",
            "billing_plan": "max_20x",
            "context_menus": {"by_target": {}},
        }


def test_ui_config_surfaces_parsed_menus_toml(tmp_storage: Path, tmp_path: Path) -> None:
    """A populated `menus.toml` flows through `/api/ui-config` so the
    frontend can merge overrides at boot without a second fetch."""
    menus_path = tmp_path / "menus.toml"
    menus_path.write_text(
        """
        [session]
        pinned = ["session.copy_id"]
        hidden = ["session.copy_share_link"]

        [session.shortcuts]
        "session.delete" = "ctrl+d"

        [message]
        pinned = ["message.copy_id"]
        """
    )
    cfg = Settings(
        storage=StorageCfg(db_path=tmp_storage),
        menus_file=menus_path,
    )
    with _client(cfg) as client:
        body = client.get("/api/ui-config").json()
    cm = body["context_menus"]["by_target"]
    assert cm["session"]["pinned"] == ["session.copy_id"]
    assert cm["session"]["hidden"] == ["session.copy_share_link"]
    assert cm["session"]["shortcuts"] == {"session.delete": "ctrl+d"}
    assert cm["message"]["pinned"] == ["message.copy_id"]
    assert cm["message"]["hidden"] == []


def test_ui_config_is_unauthenticated(tmp_storage: Path, tmp_path: Path) -> None:
    """The /ui-config endpoint runs before the auth gate — a fresh tab
    needs to know which display mode to render even before the user
    submits a token. Exposing only the billing knob is safe; nothing
    here is sensitive."""
    from bearings.config import AuthCfg

    cfg = Settings(
        storage=StorageCfg(db_path=tmp_storage),
        menus_file=tmp_path / "menus.toml",
        auth=AuthCfg(enabled=True, token="secret"),
    )
    with _client(cfg) as client:
        resp = client.get("/api/ui-config")
        # No Authorization header sent and yet we get 200 — this is the
        # contract that lets the frontend render the right UI at boot.
        assert resp.status_code == 200
