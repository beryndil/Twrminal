# mypy: disable-error-code=explicit-any
"""Atomic TOML and JSONL read/write helpers for ``.bearings/`` (arch §1.1.6).

All write paths use ``tempfile.NamedTemporaryFile`` + ``os.replace()``
(POSIX-atomic rename) so a crash mid-write cannot leave a half-written file.
Readers see either the previous complete file or the new complete file — never
a partial state.

Pydantic carve-out
------------------
``tomllib.load()`` returns ``dict[str, Any]`` and ``json.loads()`` returns
``Any``.  Neither can be narrowed further without a full parse; the
``# mypy: disable-error-code=explicit-any`` pragma is therefore required at
this boundary.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

from bearings.config.constants import BEARINGS_DIR_HISTORY_CAP

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TOML helpers
# ---------------------------------------------------------------------------


def read_toml(path: Path) -> dict[str, Any]:
    """Read and parse a TOML file.

    Returns an empty dict when *path* does not exist so callers can treat
    a missing file identically to an empty one without branching.

    Raises :exc:`tomllib.TOMLDecodeError` on malformed TOML.
    """
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def write_toml(path: Path, data: dict[str, Any]) -> None:
    """Atomically write *data* as TOML to *path*.

    Creates parent directories if they don't exist.  Uses
    ``tempfile.NamedTemporaryFile`` in the same directory as *path* so that
    ``os.replace()`` is a same-filesystem rename (guaranteed atomic on POSIX).

    Raises :exc:`OSError` on filesystem failures (propagated to caller).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            delete=False,
            suffix=".tmp",
        ) as tmp:
            tmp_path = Path(tmp.name)
            tomli_w.dump(data, tmp)
        os.replace(tmp_path, path)
        tmp_path = None  # replace succeeded; no cleanup needed
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                _log.debug("Failed to clean up temp file %s", tmp_path)


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read and parse a JSONL file.

    Returns an empty list when *path* does not exist.  Malformed lines are
    silently skipped with a DEBUG log so a single corrupted entry does not
    break the whole history.

    Only dict-typed JSON objects are returned; bare arrays / scalars on a
    line are skipped.
    """
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            _log.debug("Skipping malformed JSONL line in %s", path)
            continue
        if isinstance(entry, dict):
            result.append(entry)
    return result


def append_jsonl(
    path: Path,
    entry: dict[str, Any],
    cap: int = BEARINGS_DIR_HISTORY_CAP,
) -> None:
    """Atomically append *entry* to *path*, trimming oldest entries if cap exceeded.

    The trim removes from the **head** (oldest entries) so the most-recent
    *cap* entries are always preserved.  The write is atomic: a crash after
    ``os.replace`` completes leaves the new file; a crash before leaves the
    original intact.

    Creates parent directories and the file itself if they don't exist.

    Raises :exc:`OSError` on filesystem failures.
    """
    entries = read_jsonl(path)
    entries.append(entry)
    if len(entries) > cap:
        entries = entries[len(entries) - cap :]
    content = "\n".join(json.dumps(e, default=str) for e in entries) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
            suffix=".tmp",
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(content)
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                _log.debug("Failed to clean up temp file %s", tmp_path)


__all__ = [
    "append_jsonl",
    "read_jsonl",
    "read_toml",
    "write_toml",
]
