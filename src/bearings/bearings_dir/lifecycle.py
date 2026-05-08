"""Directory-context lifecycle helpers (arch §1.1.6).

The two public surfaces here are what ``agent/prompt.py`` (per the arch
§1.1.6 «Out» column) calls per session turn:

* :func:`note_directory_context_start` — called when a session opens a
  directory for context; appends to ``history.jsonl`` and refreshes
  ``state.toml``.
* :func:`read_brief` — called to retrieve the onboarding brief that is
  injected into the agent's system prompt.

Both functions are **no-ops** (or return ``None``) when the directory has
not yet been onboarded (i.e. ``manifest.toml`` is absent).  Callers must
not treat a missing brief as an error — it simply means onboarding has not
run yet for that directory.

Layer isolation
---------------
This module imports only from ``bearings.bearings_dir.*`` and
``bearings.config.*``.  It must not import from ``bearings.agent.*``,
``bearings.web.*``, or ``bearings.cli.*`` per arch §3 line 549.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from bearings.bearings_dir import io as bdir_io
from bearings.bearings_dir.contract import StateModel, load_manifest, load_state
from bearings.config.constants import (
    BEARINGS_DIR_HISTORY_CAP,
    BEARINGS_DIR_HISTORY_FILENAME,
    BEARINGS_DIR_MANIFEST_FILENAME,
    BEARINGS_DIR_STATE_FILENAME,
    BEARINGS_DIR_SUBDIR,
)

_log = logging.getLogger(__name__)


def note_directory_context_start(
    directory: Path,
    session_id: str,
) -> None:
    """Record that *session_id* opened *directory* for context.

    Appends a ``context_start`` JSONL entry to
    ``<directory>/.bearings/history.jsonl`` (trimming from the head when the
    :data:`~bearings.config.constants.BEARINGS_DIR_HISTORY_CAP` is exceeded)
    and updates ``state.toml`` with the current session id and timestamp.

    **No-ops silently** when ``manifest.toml`` is absent — this means the
    directory has not been onboarded yet, and calling
    ``mcp__bearings__dir_init`` is required first.

    Filesystem errors are logged at WARNING and swallowed rather than
    propagated, because a lifecycle-record failure must never crash the
    agent session that triggered it.
    """
    bearings_dir = directory / BEARINGS_DIR_SUBDIR
    if not (bearings_dir / BEARINGS_DIR_MANIFEST_FILENAME).exists():
        _log.debug(
            "note_directory_context_start: %s not yet onboarded; skipping",
            directory,
        )
        return

    now = datetime.now(UTC)

    # 1. Append context_start event to history.jsonl.
    history_path = bearings_dir / BEARINGS_DIR_HISTORY_FILENAME
    try:
        bdir_io.append_jsonl(
            history_path,
            {
                "event": "context_start",
                "session_id": session_id,
                "timestamp": now.isoformat(),
            },
            cap=BEARINGS_DIR_HISTORY_CAP,
        )
    except OSError:
        _log.warning(
            "note_directory_context_start: failed to append to %s",
            history_path,
            exc_info=True,
        )

    # 2. Refresh state.toml with session id + timestamp.
    state_path = bearings_dir / BEARINGS_DIR_STATE_FILENAME
    # Read + parse: both OSError (missing) and TOMLDecodeError (corrupt) are
    # treated as "start fresh" — the state file is non-critical state that
    # can always be reconstructed.
    try:
        raw = bdir_io.read_toml(state_path)
        state = load_state(raw)
    except Exception:
        _log.debug("state.toml unreadable in %s; starting fresh", directory)
        state = StateModel()
    updated = StateModel(
        schema_version=state.schema_version,
        last_session_id=session_id,
        last_seen_at=now,
    )
    try:
        bdir_io.write_toml(state_path, updated.model_dump(exclude_none=False))
    except OSError:
        _log.warning(
            "note_directory_context_start: failed to update state.toml in %s",
            directory,
            exc_info=True,
        )


def read_brief(directory: Path) -> str | None:
    """Return the onboarding brief for *directory*, or ``None`` if absent.

    Reads ``<directory>/.bearings/manifest.toml`` and returns the
    ``brief`` field.  Returns ``None`` (never raises) when:

    * ``manifest.toml`` does not exist — directory not yet onboarded.
    * ``manifest.toml`` cannot be parsed — schema mismatch or corruption.

    The caller (``agent/prompt.py``) uses ``None`` as the signal to omit the
    directory-context layer from the system prompt rather than surfacing a
    confusing error to the agent.
    """
    manifest_path = directory / BEARINGS_DIR_SUBDIR / BEARINGS_DIR_MANIFEST_FILENAME
    if not manifest_path.exists():
        return None
    try:
        data = bdir_io.read_toml(manifest_path)
        manifest = load_manifest(data)
        return manifest.brief
    except Exception:
        _log.debug(
            "read_brief: failed to parse manifest.toml in %s",
            directory,
            exc_info=True,
        )
        return None


__all__ = [
    "note_directory_context_start",
    "read_brief",
]
