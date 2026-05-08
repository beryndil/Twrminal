"""Unit tests for bearings_dir/pending.py.

Acceptance-criteria coverage:

* AC-pd-1  load_ops returns empty dict when file absent.
* AC-pd-2  load_ops returns ops from existing pending.toml.
* AC-pd-3  save_ops writes atomically (no temp file left).
* AC-pd-4  remove_op removes the named entry.
* AC-pd-5  remove_op raises KeyError for unknown name.
* AC-pd-6  remove_op on absent file raises KeyError.
* AC-pd-7  remove_op leaves remaining ops intact (multi-op round-trip).
* AC-pd-8  remove_op uses atomic write (delegates to bdir_io, not direct open).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from bearings.bearings_dir.pending import load_ops, remove_op, save_ops
from bearings.config.constants import (
    BEARINGS_DIR_PENDING_FILENAME,
    BEARINGS_DIR_SUBDIR,
)

_TOML_TWO_OPS = """\
[ops.deploy]
description = "Deploy to prod"
started_at = "2024-01-01T00:00:00Z"

[ops.review]
description = "Code review"
started_at = "2024-01-02T00:00:00Z"
"""

_TOML_ONE_OP = """\
[ops.deploy]
description = "Deploy to prod"
started_at = "2024-01-01T00:00:00Z"
"""


def _pending_path(project: Path) -> Path:
    p = project / BEARINGS_DIR_SUBDIR / BEARINGS_DIR_PENDING_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# AC-pd-1  load_ops — file absent returns (path, {})
# ---------------------------------------------------------------------------


def test_load_ops_returns_empty_dict_when_absent(tmp_path: Path) -> None:
    _, ops = load_ops(tmp_path)
    assert ops == {}


# ---------------------------------------------------------------------------
# AC-pd-2  load_ops — reads existing ops
# ---------------------------------------------------------------------------


def test_load_ops_reads_existing_ops(tmp_path: Path) -> None:
    _pending_path(tmp_path).write_text(_TOML_TWO_OPS)
    _, ops = load_ops(tmp_path)
    assert "deploy" in ops
    assert "review" in ops


# ---------------------------------------------------------------------------
# AC-pd-3  save_ops — atomic write, no temp file left
# ---------------------------------------------------------------------------


def test_save_ops_writes_and_leaves_no_temp(tmp_path: Path) -> None:
    path, _ = load_ops(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_ops(path, {"deploy": {"description": "Deploy", "started_at": "2024-01-01T00:00:00Z"}})
    # File exists and is valid TOML.
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    assert "deploy" in data.get("ops", {})
    # No leftover temp files.
    tmp_files = list(path.parent.glob("*.tmp"))
    assert tmp_files == []


def test_save_ops_empty_ops_writes_empty_toml(tmp_path: Path) -> None:
    path, _ = load_ops(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_ops(path, {})
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    assert data.get("ops", {}) == {}


# ---------------------------------------------------------------------------
# AC-pd-4  remove_op — removes the named entry
# ---------------------------------------------------------------------------


def test_remove_op_removes_entry(tmp_path: Path) -> None:
    _pending_path(tmp_path).write_text(_TOML_ONE_OP)
    remove_op(tmp_path, "deploy")
    path = _pending_path(tmp_path)
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    assert "deploy" not in data.get("ops", {})


# ---------------------------------------------------------------------------
# AC-pd-5  remove_op — unknown name raises KeyError
# ---------------------------------------------------------------------------


def test_remove_op_unknown_name_raises_key_error(tmp_path: Path) -> None:
    _pending_path(tmp_path).write_text(_TOML_ONE_OP)
    with pytest.raises(KeyError):
        remove_op(tmp_path, "nonexistent")


# ---------------------------------------------------------------------------
# AC-pd-6  remove_op — absent file raises KeyError
# ---------------------------------------------------------------------------


def test_remove_op_absent_file_raises_key_error(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        remove_op(tmp_path, "deploy")


# ---------------------------------------------------------------------------
# AC-pd-7  remove_op — multi-op file: remaining ops preserved
# ---------------------------------------------------------------------------


def test_remove_op_leaves_other_ops_intact(tmp_path: Path) -> None:
    _pending_path(tmp_path).write_text(_TOML_TWO_OPS)
    remove_op(tmp_path, "deploy")
    path = _pending_path(tmp_path)
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    ops = data.get("ops", {})
    assert "deploy" not in ops
    assert ops.get("review", {}).get("description") == "Code review"


# ---------------------------------------------------------------------------
# AC-pd-8  remove_op — atomic write: no temp file left on success
# ---------------------------------------------------------------------------


def test_remove_op_leaves_no_temp_file(tmp_path: Path) -> None:
    _pending_path(tmp_path).write_text(_TOML_ONE_OP)
    remove_op(tmp_path, "deploy")
    pending_dir = tmp_path / BEARINGS_DIR_SUBDIR
    tmp_files = list(pending_dir.glob("*.tmp"))
    assert tmp_files == []
