"""Atomic TOML / JSONL helpers with advisory locking.

Writes use tempfile + `os.replace` so a crash mid-write can't leave a
half-written file at the real path. Reads treat a corrupted TOML or a
Pydantic validation failure as "file missing" — the file is moved
aside to `.bearings/corrupted-YYYYMMDDHHMM-<name>` and the caller gets
`None`, which lets the next session re-onboard instead of crashing.

`fcntl.flock` is acquired on the destination path (shared for reads,
exclusive for writes). On Windows the module imports fail; Windows is
documented as single-session-only per the v0.4 spec, and the lock
functions no-op there so dev on Windows still works.

None of this is a transactional multi-file guarantee. A write to
`state.toml` and a write to `pending.toml` can interleave; the caller
is responsible for ordering. The lock only guarantees a single file's
content is never observed mid-write.
"""

from __future__ import annotations

import os
import sys
import tempfile
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

import tomli_w
from pydantic import BaseModel, ValidationError

from bearings.bearings_dir.schema import HistoryEntry

# Directory layout — every filename that lives inside `.bearings/` is
# declared here so callers never string-concat paths by hand.
BEARINGS_DIRNAME = ".bearings"
MANIFEST_FILE = "manifest.toml"
STATE_FILE = "state.toml"
PENDING_FILE = "pending.toml"
HISTORY_FILE = "history.jsonl"
CHECKS_DIR = "checks"
ON_OPEN_SCRIPT = "on_open.sh"

T = TypeVar("T", bound=BaseModel)

_IS_WINDOWS = sys.platform == "win32"


def bearings_path(directory: Path) -> Path:
    """Resolve `<directory>/.bearings/`. No side effects."""
    return directory / BEARINGS_DIRNAME


def ensure_bearings_dir(directory: Path) -> Path:
    """Create `.bearings/` (and `checks/`) if missing. Idempotent.

    Returns the created path so callers can chain. Raises `OSError`
    on a read-only filesystem; `init_dir.init_directory_safe` (v0.6.3)
    catches the read-only-style errnos and degrades gracefully so the
    onboarding brief still reaches the agent's prompt even when the
    persistence write is rejected.
    """
    root = bearings_path(directory)
    root.mkdir(parents=True, exist_ok=True)
    (root / CHECKS_DIR).mkdir(exist_ok=True)
    return root


@contextmanager
def _locked(path: Path, *, exclusive: bool) -> Iterator[None]:
    """Acquire an advisory flock on `path`. No-op on Windows.

    The lock is held on the target file itself, not on a sidecar —
    readers and writers coordinate through the same fd. Missing files
    are handled by the caller; this helper assumes the path exists.
    """
    if _IS_WINDOWS:
        yield
        return
    import fcntl  # local import — fcntl is Unix-only

    mode = "rb+" if exclusive else "rb"
    with path.open(mode) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _quarantine(path: Path, reason: str) -> Path:
    """Move a corrupted file aside with a timestamp suffix. Returns the
    new path. Used when TOML parsing or Pydantic validation fails —
    the file is preserved for forensics but the caller treats it as
    missing so the next session re-onboards cleanly.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    target = path.with_name(f"corrupted-{stamp}-{path.name}")
    # Don't clobber: if a prior quarantine already used this stamp
    # (unlikely but possible under a fast test loop), suffix an index.
    idx = 0
    while target.exists():
        idx += 1
        target = path.with_name(f"corrupted-{stamp}-{idx}-{path.name}")
    path.rename(target)
    # The caller logs to the session; we append the reason as a
    # sidecar so out-of-band forensics (grep) still finds it.
    try:
        target.with_suffix(target.suffix + ".reason").write_text(reason, encoding="utf-8")
    except OSError:
        # Best-effort: if the sidecar can't land, the rename already
        # succeeded which is the important part.
        pass
    return target


def read_toml_model(path: Path, model: type[T]) -> T | None:
    """Read `path` and parse as `model`. Returns `None` when the file
    is absent; quarantines and returns `None` when parsing or
    validation fails.

    The returned object is a fully-validated Pydantic model — callers
    can rely on its invariants without re-checking.
    """
    if not path.exists():
        return None
    try:
        with _locked(path, exclusive=False):
            raw = path.read_bytes()
        data: dict[str, Any] = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        _quarantine(path, f"toml-parse: {exc!r}")
        return None
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        _quarantine(path, f"pydantic-validate: {exc!r}")
        return None


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Tempfile + os.replace so readers never see a half-written file.

    The tempfile lives in the same directory as `path` so `os.replace`
    stays on a single filesystem (rename across filesystems is not
    atomic). fsync before rename so a power-loss leaves either the old
    content or the new content, never the empty file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError:
        # Best-effort cleanup of the tempfile on failure; re-raise so
        # the caller sees the ENOSPC / EACCES / EROFS etc.
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def _to_toml_safe(data: Any) -> Any:
    """Convert Pydantic-dumped values into TOML-friendly shapes.

    `tomli_w` refuses `None` (TOML has no null); we drop those keys.
    datetimes pass through as native TOML datetimes (tomli_w handles
    them); everything else is left alone.
    """
    if isinstance(data, dict):
        return {k: _to_toml_safe(v) for k, v in data.items() if v is not None}
    if isinstance(data, list):
        return [_to_toml_safe(item) for item in data]
    return data


def write_toml_model(path: Path, model: BaseModel) -> None:
    """Atomically write `model` to `path` as TOML.

    Holds an exclusive flock for the window between temp creation and
    rename so a concurrent reader on Unix waits rather than seeing a
    stale-then-new transition. The flock ride-alongs on the
    destination file; if it doesn't exist yet, we create it empty
    first so the lock has something to hold.
    """
    data = _to_toml_safe(model.model_dump(mode="python"))
    payload = tomli_w.dumps(data).encode("utf-8")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    with _locked(path, exclusive=True):
        _atomic_write_bytes(path, payload)


def append_history(path: Path, entry: HistoryEntry) -> None:
    """Append one JSON line to `history.jsonl`. JSONL is append-only
    by design — concurrent appenders can interleave lines but never
    corrupt an existing one, so a flock is overkill. We still open in
    append mode (`"a"`) so an interleaved write from another process
    lands intact on POSIX as long as the line is under PIPE_BUF bytes;
    the 200-char summary cap keeps us well under.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = entry.model_dump_json() + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def read_history(path: Path, *, tail: int | None = None) -> list[HistoryEntry]:
    """Read all (or the last `tail`) entries from `history.jsonl`.

    Lines that fail to parse are silently skipped — a single corrupt
    line shouldn't break the whole brief. The full file isn't
    quarantined because the append-only model means the rest of the
    file is almost certainly fine.
    """
    if not path.exists():
        return []
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    if tail is not None and tail >= 0:
        raw_lines = raw_lines[-tail:]
    out: list[HistoryEntry] = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(HistoryEntry.model_validate_json(line))
        except ValidationError:
            continue
    return out


__all__ = [
    "BEARINGS_DIRNAME",
    "CHECKS_DIR",
    "HISTORY_FILE",
    "MANIFEST_FILE",
    "ON_OPEN_SCRIPT",
    "PENDING_FILE",
    "STATE_FILE",
    "append_history",
    "bearings_path",
    "ensure_bearings_dir",
    "read_history",
    "read_toml_model",
    "write_toml_model",
]
