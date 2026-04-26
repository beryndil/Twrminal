"""Tests for the v0.6.1 session-lifecycle hooks.

Covers:
  - `record_session_start` no-ops on a non-onboarded directory
  - start writes an `in_progress` HistoryEntry
  - `record_session_end` appends a closing entry pairing on session_id
  - end status reflects tree state (clean / unclean / in_progress)
  - end is a no-op when handle is None
  - `needs_revalidation` returns True only for stale state
  - `maybe_revalidate` no-ops on missing manifest
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from bearings.bearings_dir import lifecycle
from bearings.bearings_dir.io import (
    HISTORY_FILE,
    MANIFEST_FILE,
    STATE_FILE,
    bearings_path,
    ensure_bearings_dir,
    read_history,
    write_toml_model,
)
from bearings.bearings_dir.schema import (
    EnvironmentBlock,
    Manifest,
    State,
)


def _seed_manifest(directory: Path) -> None:
    ensure_bearings_dir(directory)
    write_toml_model(
        bearings_path(directory) / MANIFEST_FILE,
        Manifest(name="Test", path=str(directory)),
    )


def test_record_session_start_noop_without_manifest(tmp_path: Path) -> None:
    handle = lifecycle.record_session_start(tmp_path, "sess-abc")
    assert handle is None
    # Nothing written under .bearings/.
    assert not (tmp_path / ".bearings").exists()


def test_record_session_start_writes_in_progress_marker(tmp_path: Path) -> None:
    _seed_manifest(tmp_path)
    handle = lifecycle.record_session_start(tmp_path, "sess-abc")
    assert handle is not None
    assert handle.session_id == "sess-abc"
    assert handle.working_dir == tmp_path

    entries = read_history(bearings_path(tmp_path) / HISTORY_FILE)
    assert len(entries) == 1
    assert entries[0].session_id == "sess-abc"
    assert entries[0].status == "in_progress"
    assert entries[0].ended is None


def test_record_session_end_noop_on_none_handle() -> None:
    """End hook with a None handle does nothing — no file access, no
    raise. Covers the case where the start hook no-op'd because the
    directory wasn't onboarded."""
    lifecycle.record_session_end(None)


def test_record_session_end_appends_closing_entry(tmp_path: Path) -> None:
    _seed_manifest(tmp_path)
    handle = lifecycle.record_session_start(tmp_path, "sess-xyz")
    assert handle is not None
    lifecycle.record_session_end(handle)

    entries = read_history(bearings_path(tmp_path) / HISTORY_FILE)
    # Two records: start (in_progress, ended=None) + end (ended set).
    assert len(entries) == 2
    start, end = entries[0], entries[1]
    assert start.session_id == end.session_id == "sess-xyz"
    assert start.ended is None
    assert end.ended is not None
    # Without git, status falls back to in_progress (not clean/unclean).
    assert end.status in {"clean", "unclean", "in_progress"}


def test_needs_revalidation_false_when_state_fresh(tmp_path: Path) -> None:
    _seed_manifest(tmp_path)
    state = State(
        environment=EnvironmentBlock(last_validated=datetime.now(UTC)),
    )
    write_toml_model(bearings_path(tmp_path) / STATE_FILE, state)
    assert lifecycle.needs_revalidation(tmp_path) is False


def test_needs_revalidation_true_when_state_stale(tmp_path: Path) -> None:
    _seed_manifest(tmp_path)
    stale = datetime.now(UTC) - timedelta(hours=48)
    state = State(environment=EnvironmentBlock(last_validated=stale))
    write_toml_model(bearings_path(tmp_path) / STATE_FILE, state)
    assert lifecycle.needs_revalidation(tmp_path) is True


def test_needs_revalidation_false_when_state_missing(tmp_path: Path) -> None:
    _seed_manifest(tmp_path)
    # No state.toml — onboarding hasn't written one yet.
    assert lifecycle.needs_revalidation(tmp_path) is False


def test_maybe_revalidate_noop_without_manifest(tmp_path: Path) -> None:
    """No manifest → no revalidation (no `.bearings/` to refresh)."""
    assert lifecycle.maybe_revalidate(tmp_path) is False


def test_maybe_revalidate_noop_when_state_fresh(tmp_path: Path) -> None:
    _seed_manifest(tmp_path)
    state = State(environment=EnvironmentBlock(last_validated=datetime.now(UTC)))
    write_toml_model(bearings_path(tmp_path) / STATE_FILE, state)
    assert lifecycle.maybe_revalidate(tmp_path) is False


def test_maybe_run_on_open_noop_without_manifest(tmp_path: Path) -> None:
    """No manifest → no on_open.sh run. Same gating as the rest of
    the lifecycle hooks; we don't write sidecars into directories
    that haven't been onboarded."""
    assert lifecycle.maybe_run_on_open(tmp_path) is False


def test_maybe_run_on_open_noop_without_script(tmp_path: Path) -> None:
    """Manifest present but no `checks/on_open.sh` → returns False
    silently. The check is opt-in; most projects won't install one."""
    _seed_manifest(tmp_path)
    assert lifecycle.maybe_run_on_open(tmp_path) is False


def test_maybe_run_on_open_runs_and_persists(tmp_path: Path) -> None:
    """Happy path: script exists → runner spawns it → result is
    persisted to `last_on_open.json` and the lifecycle wrapper
    returns True."""
    from bearings.bearings_dir.io import CHECKS_DIR, ON_OPEN_SCRIPT
    from bearings.bearings_dir.on_open import LAST_ON_OPEN_FILE, read_last_on_open

    _seed_manifest(tmp_path)
    script = bearings_path(tmp_path) / CHECKS_DIR / ON_OPEN_SCRIPT
    script.write_text("#!/usr/bin/env bash\necho ran\nexit 0\n", encoding="utf-8")

    assert lifecycle.maybe_run_on_open(tmp_path) is True
    sidecar = bearings_path(tmp_path) / LAST_ON_OPEN_FILE
    assert sidecar.is_file()
    persisted = read_last_on_open(tmp_path)
    assert persisted is not None
    assert persisted.exit_code == 0
