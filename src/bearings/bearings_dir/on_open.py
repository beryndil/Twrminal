"""Optional `.bearings/checks/on_open.sh` runner (v0.6.3 polish).

Spec (TODO.md v0.6.3+ polish): "Spawn with timeout, capture stderr,
attach exit code + stderr snippet to the brief. No plugin system;
shell script is the API."

The runner fires once per session at start (called from
`lifecycle.maybe_run_on_open` via `runner.note_directory_context_start`'s
fire-and-forget `asyncio.to_thread`). It writes a JSON sidecar at
`.bearings/last_on_open.json` so the per-turn brief renderer can
attach the result without re-spawning the script every turn.

Failure modes — all converted to a recorded `OnOpenResult` rather than
raising — so a broken user script never blocks the session:

  - script absent → returns `None` (no result, no record)
  - timeout → `timed_out=True`, `exit_code=None`
  - subprocess crash (FileNotFoundError on bash) → exit_code=-1, stderr
    carries the diagnostic
  - persist fails (EROFS / ENOSPC) → swallow, log a warning. The brief
    still renders the in-memory result for this turn; the next run
    will retry persistence.

Output is capped per-stream so a runaway log doesn't blow the brief's
3200-char budget. The cap is enforced at capture time (we read at most
N bytes from each pipe via `subprocess.run`'s built-in capture; if the
script writes more, we truncate the captured string).
"""

from __future__ import annotations

import errno
import json
import logging
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from bearings.bearings_dir.io import (
    CHECKS_DIR,
    ON_OPEN_SCRIPT,
    bearings_path,
)

log = logging.getLogger(__name__)

# Sidecar filename for the most recent run's structured result. Lives
# at `.bearings/last_on_open.json` rather than inside `state.toml`
# because (a) it's per-run, not per-state, and (b) JSON survives a
# round-trip cleanly without the TOML quirks around multiline strings.
LAST_ON_OPEN_FILE = "last_on_open.json"

# Hard cap on each stream's captured bytes. 1024 each → ~2KB total in
# the worst case, well under the 3200-char brief budget. Long enough to
# carry a useful failure summary (a typical pytest tail or shell error)
# without crowding the rest of the brief.
_OUTPUT_CAP_BYTES = 1024

# Seconds before the runner gives up on the script. Onboarding is
# already a quick read; a check that takes longer than 10s is doing
# real work and should be deferred to the user's normal CI loop.
_TIMEOUT_S = 10.0

# Sentinel exit code used when subprocess machinery itself raised
# before the script could exit (FileNotFoundError on `bash`,
# permission-denied on the wrapper, etc.). Distinct from a real
# script exit because real scripts can't return -1 portably.
_RUNNER_FAILURE_EXIT = -1


class OnOpenResult(BaseModel):
    """One run of `.bearings/checks/on_open.sh`. Persisted as JSON in
    `<.bearings>/last_on_open.json`; consumed by the brief renderer."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    ran_at: datetime
    duration_ms: int = Field(ge=0)
    exit_code: int | None
    stdout_snippet: str = Field(default="", max_length=_OUTPUT_CAP_BYTES * 2)
    stderr_snippet: str = Field(default="", max_length=_OUTPUT_CAP_BYTES * 2)
    timed_out: bool = False


def _on_open_script_path(directory: Path) -> Path:
    """Resolve the canonical script location. No FS check — callers
    pass the path on to `_script_present` which does the existence
    test. Splitting the two keeps callers honest about whether they
    need a path or a "should we run" boolean."""
    return bearings_path(directory) / CHECKS_DIR / ON_OPEN_SCRIPT


def _script_present(directory: Path) -> bool:
    """True iff `<.bearings>/checks/on_open.sh` exists as a regular
    file. Symlinks are followed (`exists()` follows by default) so
    users can stash the real script elsewhere and link it in."""
    path = _on_open_script_path(directory)
    return path.is_file()


def _truncate_stream(raw: str | bytes | None) -> str:
    """Cap captured output to `_OUTPUT_CAP_BYTES`. Bytes inputs are
    decoded with `errors='replace'` — the brief is human-readable
    text, not a binary forensics tool. Truncated streams get a clear
    marker so a downstream reader sees they were cut."""
    if raw is None:
        return ""
    text = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
    if len(text.encode("utf-8")) <= _OUTPUT_CAP_BYTES:
        return text
    # Truncate from the END — a script's tail (the actual failure
    # message) is more useful than its banner.
    encoded = text.encode("utf-8")[-_OUTPUT_CAP_BYTES:]
    return "…[truncated]\n" + encoded.decode("utf-8", errors="replace")


def run_on_open(directory: Path) -> OnOpenResult | None:
    """Run the user's `on_open.sh` once. Returns `None` when the script
    doesn't exist; never raises. A timeout, missing-bash, or runtime
    crash is recorded as a result with the failure surfaced in
    `stderr_snippet` and `exit_code` set accordingly.

    Invoked via `bash <path>` (not `./<path>`) so users don't need to
    `chmod +x` the script. Per the spec: "shell script is the API."
    """
    script = _on_open_script_path(directory)
    if not script.is_file():
        return None

    start = time.monotonic()
    ran_at = datetime.now(UTC)
    timed_out = False
    exit_code: int | None
    stdout = ""
    stderr = ""
    try:
        proc = subprocess.run(
            ["bash", str(script)],
            cwd=str(directory),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = None
        stdout = _truncate_stream(exc.stdout)
        stderr = _truncate_stream(exc.stderr) or f"timed out after {_TIMEOUT_S:.0f}s"
    except (FileNotFoundError, OSError) as exc:
        # No `bash` on PATH, or some lower-level OS error. Record the
        # failure so the brief tells the user "your check couldn't
        # run" rather than silently dropping the result.
        exit_code = _RUNNER_FAILURE_EXIT
        stderr = f"{type(exc).__name__}: {exc}"
    else:
        exit_code = proc.returncode
        stdout = _truncate_stream(proc.stdout)
        stderr = _truncate_stream(proc.stderr)

    duration_ms = int((time.monotonic() - start) * 1000)
    return OnOpenResult(
        ran_at=ran_at,
        duration_ms=duration_ms,
        exit_code=exit_code,
        stdout_snippet=stdout,
        stderr_snippet=stderr,
        timed_out=timed_out,
    )


def persist_on_open(directory: Path, result: OnOpenResult) -> bool:
    """Atomically write `result` to `<.bearings>/last_on_open.json`.
    Returns True on success, False on a recoverable write failure
    (read-only FS, disk full, missing parent). Never raises — this is
    advisory state.

    The atomic write uses a sibling tempfile + `os.replace` (same
    pattern as `io._atomic_write_bytes`) so a concurrent reader never
    sees a half-written file. If the parent `.bearings/` is read-only
    (the v0.6.3 graceful-degrade case) the write fails and we log a
    one-line warning; the brief on this turn still gets the in-memory
    result via the caller's return value.
    """
    target = bearings_path(directory) / LAST_ON_OPEN_FILE
    payload = result.model_dump_json().encode("utf-8")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if exc.errno in (errno.EROFS, errno.EACCES, errno.EPERM, errno.ENOSPC):
            log.info(
                "directory_context: skipping last_on_open persist for %s (%s)",
                directory,
                exc.strerror or exc,
            )
            return False
        log.warning("directory_context: last_on_open mkdir failed for %s: %s", directory, exc)
        return False
    # Sibling tempfile so `os.replace` stays on one filesystem. Both
    # `mkstemp` and the write itself can raise on a read-only mount —
    # the FS rejects the temp creation as well as the rename — so the
    # whole sequence shares one try/except.
    import os
    import tempfile

    tmp_path: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{LAST_ON_OPEN_FILE}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except OSError as exc:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        if exc.errno in (errno.EROFS, errno.EACCES, errno.EPERM, errno.ENOSPC):
            log.info(
                "directory_context: skipping last_on_open persist for %s (%s)",
                directory,
                exc.strerror or exc,
            )
            return False
        log.warning(
            "directory_context: last_on_open write failed for %s: %s",
            directory,
            exc,
        )
        return False
    return True


def read_last_on_open(directory: Path) -> OnOpenResult | None:
    """Load the persisted result, or `None` if missing or corrupt.
    Corrupt JSON / Pydantic validation failures return `None` rather
    than raising — same fail-open posture as `read_toml_model`. The
    sidecar is overwritten on the next run so a one-off corruption
    self-heals."""
    path = bearings_path(directory) / LAST_ON_OPEN_FILE
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    try:
        return OnOpenResult.model_validate(data)
    except Exception:  # noqa: BLE001 — pydantic ValidationError plus any unexpected shape
        return None


def maybe_run_on_open(directory: Path) -> OnOpenResult | None:
    """Run + persist if the script is present. Returns the result for
    the caller's convenience (e.g. the lifecycle wrapper logging a
    one-liner for failed checks). Returns `None` when no script is
    installed.

    Idempotent — running twice in a row produces two persist writes
    that overwrite each other. Cheap because the script is a user
    artifact, not a Bearings-internal one."""
    if not _script_present(directory):
        return None
    result = run_on_open(directory)
    if result is None:
        return None
    persist_on_open(directory, result)
    return result


__all__ = [
    "LAST_ON_OPEN_FILE",
    "OnOpenResult",
    "maybe_run_on_open",
    "persist_on_open",
    "read_last_on_open",
    "run_on_open",
]
