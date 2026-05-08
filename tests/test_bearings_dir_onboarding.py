"""Unit tests for bearings_dir/onboarding.py.

Acceptance-criteria coverage:

* AC-ob-1  run_onboarding_ritual returns a non-empty string.
* AC-ob-2  run_onboarding_ritual output contains the expected lines.
* AC-ob-3  dir_init_body creates manifest.toml, state.toml, pending.toml.
* AC-ob-4  dir_init_body is idempotent (safe to re-run).
* AC-ob-5  dir_init_body manifest.toml is Pydantic-parseable.
* AC-ob-6  dir_init_body state.toml starts with no session recorded.
* AC-ob-7  dir_init_body pending.toml is empty.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from bearings.bearings_dir.contract import load_manifest
from bearings.bearings_dir.onboarding import dir_init_body, run_onboarding_ritual
from bearings.config.constants import (
    BEARINGS_DIR_MANIFEST_FILENAME,
    BEARINGS_DIR_PENDING_FILENAME,
    BEARINGS_DIR_SCHEMA_VERSION,
    BEARINGS_DIR_STATE_FILENAME,
    BEARINGS_DIR_SUBDIR,
)


def _bdir(project: Path) -> Path:
    return project / BEARINGS_DIR_SUBDIR


# ---------------------------------------------------------------------------
# AC-ob-1  run_onboarding_ritual returns a non-empty string
# ---------------------------------------------------------------------------


def test_run_onboarding_ritual_returns_nonempty_string(tmp_path: Path) -> None:
    brief = run_onboarding_ritual(tmp_path)
    assert isinstance(brief, str)
    assert len(brief) > 0


# ---------------------------------------------------------------------------
# AC-ob-2  run_onboarding_ritual output contains expected lines
# ---------------------------------------------------------------------------


def test_run_onboarding_ritual_contains_directory_line(tmp_path: Path) -> None:
    brief = run_onboarding_ritual(tmp_path)
    assert f"Directory: {tmp_path}" in brief


def test_run_onboarding_ritual_contains_primary_marker_line(tmp_path: Path) -> None:
    # Plant a pyproject.toml so the marker is deterministic.
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    brief = run_onboarding_ritual(tmp_path)
    assert "Primary marker: pyproject.toml" in brief


def test_run_onboarding_ritual_contains_environment_line(tmp_path: Path) -> None:
    brief = run_onboarding_ritual(tmp_path)
    assert "Environment:" in brief


def test_run_onboarding_ritual_contains_unfinished_markers_line(
    tmp_path: Path,
) -> None:
    brief = run_onboarding_ritual(tmp_path)
    assert "Unfinished markers:" in brief


def test_run_onboarding_ritual_shows_no_primary_marker_when_bare(
    tmp_path: Path,
) -> None:
    brief = run_onboarding_ritual(tmp_path)
    assert "Primary marker: (none found)" in brief


# ---------------------------------------------------------------------------
# AC-ob-3  dir_init_body creates all three files
# ---------------------------------------------------------------------------


def test_dir_init_body_creates_manifest(tmp_path: Path) -> None:
    dir_init_body(tmp_path)
    assert (_bdir(tmp_path) / BEARINGS_DIR_MANIFEST_FILENAME).exists()


def test_dir_init_body_creates_state(tmp_path: Path) -> None:
    dir_init_body(tmp_path)
    assert (_bdir(tmp_path) / BEARINGS_DIR_STATE_FILENAME).exists()


def test_dir_init_body_creates_pending(tmp_path: Path) -> None:
    dir_init_body(tmp_path)
    assert (_bdir(tmp_path) / BEARINGS_DIR_PENDING_FILENAME).exists()


# ---------------------------------------------------------------------------
# AC-ob-4  dir_init_body is idempotent
# ---------------------------------------------------------------------------


def test_dir_init_body_is_idempotent(tmp_path: Path) -> None:
    dir_init_body(tmp_path)
    dir_init_body(tmp_path)  # second call must not raise
    # All files still present and valid.
    manifest_path = _bdir(tmp_path) / BEARINGS_DIR_MANIFEST_FILENAME
    with manifest_path.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["schema_version"] == BEARINGS_DIR_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# AC-ob-5  manifest.toml is Pydantic-parseable
# ---------------------------------------------------------------------------


def test_dir_init_body_manifest_is_parseable(tmp_path: Path) -> None:
    dir_init_body(tmp_path)
    manifest_path = _bdir(tmp_path) / BEARINGS_DIR_MANIFEST_FILENAME
    with manifest_path.open("rb") as fh:
        data = tomllib.load(fh)
    m = load_manifest(data)
    assert m.schema_version == BEARINGS_DIR_SCHEMA_VERSION
    assert m.directory == str(tmp_path)
    assert len(m.brief) > 0


# ---------------------------------------------------------------------------
# AC-ob-6  state.toml starts with no session recorded
# ---------------------------------------------------------------------------


def test_dir_init_body_state_has_no_session(tmp_path: Path) -> None:
    dir_init_body(tmp_path)
    state_path = _bdir(tmp_path) / BEARINGS_DIR_STATE_FILENAME
    with state_path.open("rb") as fh:
        data = tomllib.load(fh)
    assert "last_session_id" not in data or data.get("last_session_id") is None
    assert data["schema_version"] == BEARINGS_DIR_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# AC-ob-7  pending.toml is empty
# ---------------------------------------------------------------------------


def test_dir_init_body_pending_is_empty(tmp_path: Path) -> None:
    dir_init_body(tmp_path)
    pending_path = _bdir(tmp_path) / BEARINGS_DIR_PENDING_FILENAME
    with pending_path.open("rb") as fh:
        data = tomllib.load(fh)
    assert data.get("ops", {}) == {}
