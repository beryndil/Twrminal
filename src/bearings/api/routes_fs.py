"""Filesystem listing for the folder-picker UI.

Lists directories under an absolute path so the FolderPicker can walk
the tree without relying on a browser-side file dialog (which can't
access server-side paths). Read-only; no write or execute semantics.

Also exposes `POST /fs/pick`, which spawns a native file-selection
dialog (zenity on GTK, kdialog on KDE) so the UI can hand Bearings an
absolute server-side path. Browser `<input type="file">` only surfaces
filenames — useless when Claude needs to read the file from disk — so
we defer to the OS picker since Bearings already runs on the user's
own machine.

Security posture: Bearings binds 127.0.0.1 by default and is a
single-user tool. Exposing directory names to the local browser is
equivalent to the user running `ls` in a terminal — not a meaningful
disclosure. The pick endpoint only *reads* a path the user explicitly
selected in a native dialog; it does not open or transfer the file.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from bearings.api.auth import require_auth
from bearings.api.models import FsEntryOut, FsListOut, FsPickOut

router = APIRouter(
    prefix="/fs",
    tags=["fs"],
    dependencies=[Depends(require_auth)],
)

# Cap the dialog so a never-dismissed picker can't hold a request
# handler forever. Two minutes is long enough for a human to navigate
# a deep tree but short enough that a forgotten dialog recovers on its
# own.
_PICK_TIMEOUT_SECONDS = 120


def _list_dir(path: Path, *, hidden: bool) -> FsListOut:
    """Assemble an FsListOut for an already-resolved directory. Caller
    is responsible for validating that `path` exists and is a dir."""
    entries: list[FsEntryOut] = []
    for child in sorted(path.iterdir(), key=lambda p: p.name.lower()):
        if not hidden and child.name.startswith("."):
            continue
        if not child.is_dir():
            continue
        entries.append(FsEntryOut(name=child.name, path=str(child)))
    parent = str(path.parent) if path.parent != path else None
    return FsListOut(path=str(path), parent=parent, entries=entries)


@router.get("/list", response_model=FsListOut)
async def list_dir(path: str | None = None, hidden: bool = False) -> FsListOut:
    target = Path(path) if path else Path.home()
    if not target.is_absolute():
        raise HTTPException(status_code=400, detail="path must be absolute")
    try:
        resolved = target.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=404, detail="path not found") from exc
    if not resolved.is_dir():
        raise HTTPException(status_code=404, detail="path is not a directory")
    try:
        return _list_dir(resolved, hidden=hidden)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="permission denied") from exc


def _pick_command(*, start: str | None, multiple: bool, title: str) -> list[str] | None:
    """Build the argv for whichever native picker is available.

    Returns None when neither zenity nor kdialog is on PATH — the route
    then responds 501 so the UI can surface an actionable message
    instead of silently failing.
    """
    if shutil.which("zenity"):
        argv = ["zenity", "--file-selection", f"--title={title}"]
        if multiple:
            # zenity returns `|`-separated paths when --multiple is set;
            # --separator swaps that to NUL so paths containing `|` parse
            # cleanly.
            argv.extend(["--multiple", "--separator=\0"])
        if start:
            argv.append(f"--filename={start}")
        return argv
    if shutil.which("kdialog"):
        argv = ["kdialog", "--title", title]
        argv.append("--getopenfilename")
        argv.append(start or str(Path.home()))
        if multiple:
            argv.append("--multiple")
            argv.extend(["--separate-output"])
        return argv
    return None


async def _run_picker(argv: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=_PICK_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise HTTPException(status_code=504, detail="file picker timed out") from exc
    return proc.returncode or 0, stdout_b.decode("utf-8", errors="replace")


@router.post("/pick", response_model=FsPickOut)
async def pick_file(
    start: str | None = None,
    multiple: bool = False,
    title: str = "Select a file",
) -> FsPickOut:
    """Pop a native file-selection dialog and return the chosen path.

    Bearings is single-user/localhost, so "native dialog the user sees
    on their own desktop" is the right UX — it gives Claude an absolute
    path to work from without round-tripping a full browser upload.
    """
    argv = _pick_command(start=start, multiple=multiple, title=title)
    if argv is None:
        raise HTTPException(
            status_code=501,
            detail="no native file picker available (install zenity or kdialog)",
        )
    code, stdout = await _run_picker(argv)
    # Both zenity and kdialog return 1 when the user cancels. Empty
    # stdout with a 0 exit (shouldn't happen in practice) is treated
    # the same way — nothing to surface.
    if code != 0 or not stdout.strip():
        return FsPickOut(path=None, paths=[], cancelled=True)
    # zenity --multiple with NUL separator gives us unambiguous splits
    # (paths with embedded newlines would otherwise fracture). kdialog
    # --separate-output emits one path per line, which is fine because
    # kdialog doesn't allow newline in filenames via Qt anyway.
    sep = "\0" if "\0" in stdout else "\n"
    paths = [p.strip() for p in stdout.split(sep) if p.strip()]
    if not paths:
        return FsPickOut(path=None, paths=[], cancelled=True)
    return FsPickOut(path=paths[0], paths=paths, cancelled=False)
