"""Tests for `init_dir.init_directory_safe` (v0.6.3 graceful degrade).

The happy path is exercised end-to-end by `test_bearings_dir_cli.py` and
the auto-onboarding test suite. This file specifically covers the new
read-only filesystem degrade path: the brief is returned, the write is
skipped, and a human-readable warning is attached.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

import pytest

from bearings.bearings_dir.init_dir import (
    InitOutcome,
    init_directory_safe,
)
from bearings.bearings_dir.io import MANIFEST_FILE, bearings_path


def _seed_pyproject(directory: Path) -> None:
    """Minimal `pyproject.toml` so the onboarding ritual recognises
    the directory as a project."""
    (directory / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )


def test_happy_path_writes_and_returns_root(tmp_path: Path) -> None:
    """Sanity: when the FS is writable, `init_directory_safe` behaves
    identically to `init_directory` (returns root, no warning)."""
    _seed_pyproject(tmp_path)
    outcome = init_directory_safe(tmp_path)
    assert isinstance(outcome, InitOutcome)
    assert outcome.root is not None
    assert outcome.warning is None
    assert (outcome.root / MANIFEST_FILE).is_file()


def test_read_only_filesystem_degrades_gracefully(tmp_path: Path) -> None:
    """When the directory rejects writes, the brief still comes back
    and the warning explains the persistence gap. The agent uses this
    to tell the user "I have a brief but couldn't save it" instead of
    the entire MCP call coming back as an error.

    Implementation: revoke write+exec on `tmp_path` so `mkdir
    .bearings/` raises EACCES. Cross-platform note: on Windows the
    chmod is largely a no-op; this test skips there. Same for a root
    test runner, which bypasses POSIX permission bits."""
    if os.name == "nt":
        pytest.skip("chmod-based read-only test is POSIX-only")
    if os.geteuid() == 0:
        pytest.skip("root bypasses POSIX permission bits")

    _seed_pyproject(tmp_path)
    original_mode = tmp_path.stat().st_mode
    tmp_path.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        outcome = init_directory_safe(tmp_path)
    finally:
        tmp_path.chmod(original_mode)

    # Brief is still produced — the brief is a pure read of the
    # working dir and must never be starved by a write-blocked FS.
    assert outcome.brief is not None
    # Persistence was skipped → root is None and warning carries why.
    assert outcome.root is None
    assert outcome.warning is not None
    assert "persist skipped" in outcome.warning
    # `.bearings/` was NOT written.
    assert not bearings_path(tmp_path).exists()


def test_non_readonly_oserror_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-graceful OSError (e.g. EISDIR) bubbles up — the safe
    wrapper only absorbs the read-only-style errnos. Anything else is
    a real bug and the agent must see it."""
    _seed_pyproject(tmp_path)

    def _explode(_directory: Path, _brief: object) -> Path:
        raise OSError(errno.EIO, "synthetic I/O error")

    # Patch the writer used inside `init_directory_safe`.
    monkeypatch.setattr("bearings.bearings_dir.init_dir.write_bearings", _explode)
    with pytest.raises(OSError) as exc_info:
        init_directory_safe(tmp_path)
    assert exc_info.value.errno == errno.EIO
