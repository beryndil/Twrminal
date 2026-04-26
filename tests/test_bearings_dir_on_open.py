"""Tests for the v0.6.3 `.bearings/checks/on_open.sh` runner.

Covers:
  - `_script_present` returns False on a fresh directory
  - `run_on_open` returns None when the script is missing
  - happy path: exit 0 captured, stdout snippet preserved
  - non-zero exit captured with stderr snippet
  - timeout captured as `timed_out=True`, exit_code=None
  - long output is truncated to the per-stream cap
  - persisted result round-trips via `read_last_on_open`
  - `maybe_run_on_open` is a no-op when no script is installed
  - `persist_on_open` survives a read-only directory (returns False
    and logs, never raises)
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from bearings.bearings_dir import on_open
from bearings.bearings_dir.io import (
    CHECKS_DIR,
    ON_OPEN_SCRIPT,
    bearings_path,
    ensure_bearings_dir,
)
from bearings.bearings_dir.on_open import (
    LAST_ON_OPEN_FILE,
    OnOpenResult,
    maybe_run_on_open,
    persist_on_open,
    read_last_on_open,
    run_on_open,
)


def _install_script(directory: Path, body: str) -> Path:
    """Write `<.bearings>/checks/on_open.sh` with `body` and return
    the script path. Includes a `#!/usr/bin/env bash` shebang so
    invocation works whether or not `bash` is on PATH."""
    ensure_bearings_dir(directory)
    script = bearings_path(directory) / CHECKS_DIR / ON_OPEN_SCRIPT
    script.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    return script


# ───────────── presence gate ─────────────


def test_script_absent_returns_none(tmp_path: Path) -> None:
    """No `.bearings/checks/on_open.sh` → no result. Most directories
    won't install a check; the brief simply omits the section."""
    ensure_bearings_dir(tmp_path)
    assert run_on_open(tmp_path) is None
    assert maybe_run_on_open(tmp_path) is None


def test_script_in_subdir_doesnt_count(tmp_path: Path) -> None:
    """Only `.bearings/checks/on_open.sh` triggers the runner; a
    similarly-named file elsewhere is ignored. Guards against false
    positives if a user keeps a script next to the `.bearings/` dir."""
    (tmp_path / "on_open.sh").write_text("#!/usr/bin/env bash\necho hi\n")
    ensure_bearings_dir(tmp_path)
    assert run_on_open(tmp_path) is None


# ───────────── happy / failure exit codes ─────────────


def test_happy_exit_zero_captures_stdout(tmp_path: Path) -> None:
    _install_script(tmp_path, "echo hello\nexit 0\n")
    result = run_on_open(tmp_path)
    assert result is not None
    assert result.exit_code == 0
    assert "hello" in result.stdout_snippet
    assert result.timed_out is False
    assert result.duration_ms >= 0


def test_failing_exit_captures_stderr(tmp_path: Path) -> None:
    _install_script(
        tmp_path,
        "echo something-broke 1>&2\nexit 7\n",
    )
    result = run_on_open(tmp_path)
    assert result is not None
    assert result.exit_code == 7
    assert "something-broke" in result.stderr_snippet
    assert result.timed_out is False


def test_long_stdout_is_truncated(tmp_path: Path) -> None:
    """A noisy script can't blow the brief's char budget. The runner
    caps each stream at 1024 bytes; verify the cap holds and the
    truncation marker is present."""
    # Print a 4KB run of A's so the cap definitely trips.
    _install_script(tmp_path, "yes 'AAAAAAAAAAAAAAAA' | head -c 4096\n")
    result = run_on_open(tmp_path)
    assert result is not None
    # Per-stream cap is 1024 bytes; the rendered string can be slightly
    # larger because of the truncation marker, but well under 4KB.
    assert len(result.stdout_snippet.encode("utf-8")) < 2048
    assert "truncated" in result.stdout_snippet


# ───────────── timeout ─────────────


def test_timeout_records_timed_out_flag(tmp_path: Path) -> None:
    """A script that hangs past the 10s budget is recorded as
    `timed_out=True`. We monkeypatch the timeout to 0.2s so the test
    stays fast."""
    _install_script(tmp_path, "sleep 5\n")
    with patch.object(on_open, "_TIMEOUT_S", 0.2):
        result = run_on_open(tmp_path)
    assert result is not None
    assert result.timed_out is True
    assert result.exit_code is None


# ───────────── persist + read round-trip ─────────────


def test_persist_and_read_round_trip(tmp_path: Path) -> None:
    """A persisted result must come back exactly via the read helper —
    the brief renderer relies on this round-trip to render last-run
    output without re-spawning the script every turn."""
    ensure_bearings_dir(tmp_path)
    src = OnOpenResult(
        ran_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        duration_ms=42,
        exit_code=0,
        stdout_snippet="all good",
        stderr_snippet="",
        timed_out=False,
    )
    assert persist_on_open(tmp_path, src) is True
    sidecar = bearings_path(tmp_path) / LAST_ON_OPEN_FILE
    assert sidecar.is_file()

    loaded = read_last_on_open(tmp_path)
    assert loaded is not None
    assert loaded.exit_code == 0
    assert loaded.stdout_snippet == "all good"
    assert loaded.duration_ms == 42


def test_read_last_on_open_handles_corrupt_json(tmp_path: Path) -> None:
    """A torn write or hand-edit corrupting the sidecar must not
    crash the brief — `read_last_on_open` returns None and the
    caller silently omits the section."""
    ensure_bearings_dir(tmp_path)
    (bearings_path(tmp_path) / LAST_ON_OPEN_FILE).write_text("{not valid json", encoding="utf-8")
    assert read_last_on_open(tmp_path) is None


def test_read_last_on_open_handles_missing(tmp_path: Path) -> None:
    """No sidecar → no result, no exception."""
    ensure_bearings_dir(tmp_path)
    assert read_last_on_open(tmp_path) is None


# ───────────── maybe_run_on_open + persist failure ─────────────


def test_maybe_run_on_open_persists_result(tmp_path: Path) -> None:
    _install_script(tmp_path, "echo done\nexit 0\n")
    result = maybe_run_on_open(tmp_path)
    assert result is not None
    assert result.exit_code == 0
    # Sidecar exists and round-trips.
    loaded = read_last_on_open(tmp_path)
    assert loaded is not None
    assert loaded.exit_code == 0


def test_persist_on_open_survives_read_only_parent(tmp_path: Path) -> None:
    """When `.bearings/` is read-only the persist call returns False
    rather than raising. Real-world trigger: an NFS mount that lost
    write permission mid-session, or a CI sandbox with a frozen
    workspace. Skipped on Windows where chmod semantics differ."""
    if os.name == "nt":
        pytest.skip("chmod-based read-only test is POSIX-only")
    if os.geteuid() == 0:
        pytest.skip("root bypasses POSIX permission bits")

    ensure_bearings_dir(tmp_path)
    bearings_root = bearings_path(tmp_path)
    # Drop write+exec on the dir so `tempfile.mkstemp` inside it
    # fails. Restore in a finally so pytest cleanup can rm-rf the
    # tree even if the test bails.
    original_mode = bearings_root.stat().st_mode
    bearings_root.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        result = OnOpenResult(
            ran_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            duration_ms=1,
            exit_code=0,
        )
        ok = persist_on_open(tmp_path, result)
        assert ok is False
    finally:
        bearings_root.chmod(original_mode)
