"""Unit tests for bearings_dir/lifecycle.py.

Acceptance-criteria coverage:

* AC-lc-1  note_directory_context_start no-ops when manifest.toml absent.
* AC-lc-2  note_directory_context_start appends to history.jsonl.
* AC-lc-3  note_directory_context_start updates state.toml.
* AC-lc-4  note_directory_context_start handles corrupt state.toml gracefully.
* AC-lc-5  read_brief returns None when manifest.toml absent.
* AC-lc-6  read_brief returns the brief string when manifest is valid.
* AC-lc-7  read_brief returns None on schema-version mismatch (does not raise).
"""

from __future__ import annotations

import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from bearings.bearings_dir.io import write_toml
from bearings.bearings_dir.lifecycle import note_directory_context_start, read_brief
from bearings.config.constants import (
    BEARINGS_DIR_HISTORY_FILENAME,
    BEARINGS_DIR_MANIFEST_FILENAME,
    BEARINGS_DIR_SCHEMA_VERSION,
    BEARINGS_DIR_STATE_FILENAME,
    BEARINGS_DIR_SUBDIR,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _bearings_dir(project: Path) -> Path:
    d = project / BEARINGS_DIR_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_manifest(project: Path, *, brief: str = "Directory: /tmp/foo") -> None:
    bdir = _bearings_dir(project)
    write_toml(
        bdir / BEARINGS_DIR_MANIFEST_FILENAME,
        {
            "schema_version": BEARINGS_DIR_SCHEMA_VERSION,
            "directory": str(project),
            "primary_marker": ".git",
            "created_at": _NOW,
            "brief": brief,
        },
    )


# ---------------------------------------------------------------------------
# AC-lc-1  no-op when manifest absent
# ---------------------------------------------------------------------------


def test_note_no_op_when_manifest_absent(tmp_path: Path) -> None:
    """Should not create any files when manifest.toml is missing."""
    note_directory_context_start(tmp_path, "ses_abc")
    # Nothing should have been created.
    assert not (tmp_path / BEARINGS_DIR_SUBDIR).exists()


# ---------------------------------------------------------------------------
# AC-lc-2  appends to history.jsonl
# ---------------------------------------------------------------------------


def test_note_appends_to_history(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    note_directory_context_start(tmp_path, "ses_abc")
    history_path = tmp_path / BEARINGS_DIR_SUBDIR / BEARINGS_DIR_HISTORY_FILENAME
    assert history_path.exists()
    entries = [json.loads(line) for line in history_path.read_text().splitlines() if line.strip()]
    assert len(entries) == 1
    assert entries[0]["event"] == "context_start"
    assert entries[0]["session_id"] == "ses_abc"


def test_note_accumulates_history_entries(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    note_directory_context_start(tmp_path, "ses_1")
    note_directory_context_start(tmp_path, "ses_2")
    history_path = tmp_path / BEARINGS_DIR_SUBDIR / BEARINGS_DIR_HISTORY_FILENAME
    entries = [json.loads(line) for line in history_path.read_text().splitlines() if line.strip()]
    assert len(entries) == 2
    assert entries[1]["session_id"] == "ses_2"


# ---------------------------------------------------------------------------
# AC-lc-3  updates state.toml
# ---------------------------------------------------------------------------


def test_note_updates_state_toml(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    note_directory_context_start(tmp_path, "ses_xyz")
    state_path = tmp_path / BEARINGS_DIR_SUBDIR / BEARINGS_DIR_STATE_FILENAME
    assert state_path.exists()
    with state_path.open("rb") as fh:
        state = tomllib.load(fh)
    assert state["last_session_id"] == "ses_xyz"
    assert "last_seen_at" in state


# ---------------------------------------------------------------------------
# AC-lc-4  handles corrupt state.toml gracefully
# ---------------------------------------------------------------------------


def test_note_handles_corrupt_state_toml(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    state_path = tmp_path / BEARINGS_DIR_SUBDIR / BEARINGS_DIR_STATE_FILENAME
    state_path.write_text("NOT VALID TOML <<<", encoding="utf-8")
    # Should not raise; overwrites corrupt state with fresh state.
    note_directory_context_start(tmp_path, "ses_recover")
    with state_path.open("rb") as fh:
        state = tomllib.load(fh)
    assert state["last_session_id"] == "ses_recover"


# ---------------------------------------------------------------------------
# AC-lc-5  read_brief returns None when manifest absent
# ---------------------------------------------------------------------------


def test_read_brief_returns_none_when_manifest_absent(tmp_path: Path) -> None:
    result = read_brief(tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# AC-lc-6  read_brief returns the brief string
# ---------------------------------------------------------------------------


def test_read_brief_returns_brief_string(tmp_path: Path) -> None:
    _write_manifest(tmp_path, brief="Directory: /tmp/foo\nPrimary marker: .git")
    result = read_brief(tmp_path)
    assert result is not None
    assert "Primary marker: .git" in result


# ---------------------------------------------------------------------------
# AC-lc-7  read_brief returns None on schema-version mismatch (does not raise)
# ---------------------------------------------------------------------------


def test_read_brief_returns_none_on_schema_mismatch(tmp_path: Path) -> None:
    bdir = _bearings_dir(tmp_path)
    write_toml(
        bdir / BEARINGS_DIR_MANIFEST_FILENAME,
        {
            "schema_version": 999,  # bad version
            "directory": str(tmp_path),
            "primary_marker": ".git",
            "created_at": _NOW,
            "brief": "some brief",
        },
    )
    result = read_brief(tmp_path)
    assert result is None
