"""Filesystem listing and native-picker bridge for the picker UIs.

`GET /fs/list` lists directory contents under an absolute path so the
in-app FolderPicker/FilePickerModal can walk the tree without relying
on a browser-side file dialog. Read-only; no write or execute
semantics.

`POST /fs/pick` spawns the host's native picker (zenity on GTK,
kdialog on KDE) and returns the chosen absolute path(s). Browser
`<input type="file">` and HTML5 drag-and-drop both sandbox absolute
paths, so the only way to hand Claude a real filesystem path from a
web UI is to defer to the OS dialog the user already trusts. Bearings
is localhost/single-user, so popping a dialog on the user's own
desktop is fair game — and in practice it's the picker the user
already uses every day.

Theming: Bearings' UI is a slate/emerald dark palette, and a white
GTK dialog popping next to it looks like a 1999 cross-platform port.
We force zenity into a dark GTK theme via `GTK_THEME` so the picker
visually blends with the app. Preference order: Breeze-Dark (Kubuntu
default, matches slate tones best), then Adwaita-dark (ships with
every GTK3). If neither is installed we fall back to system default
rather than fail the pick — a light picker that works beats a dark
one that doesn't.

Security posture: Bearings binds 127.0.0.1 by default and is a
single-user tool. Exposing directory and filenames to the local
browser is equivalent to the user running `ls` in a terminal — not a
meaningful disclosure. The pick endpoint only *reads* a path the user
explicitly selected in a native dialog; it does not open or transfer
the file's bytes.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from bearings.api.auth import require_auth
from bearings.api.models import FsEntryOut, FsListOut, FsPickOut

router = APIRouter(
    prefix="/fs",
    tags=["fs"],
    dependencies=[Depends(require_auth)],
)

# Cap the dialog so a forgotten picker can't hold a request handler
# forever. Two minutes is long enough for a human to navigate a deep
# tree but short enough that an abandoned dialog recovers on its own.
_PICK_TIMEOUT_SECONDS = 120

PickMode = Literal["file", "directory"]


def _list_dir(path: Path, *, hidden: bool, include_files: bool) -> FsListOut:
    """Assemble an FsListOut for an already-resolved directory. Caller
    is responsible for validating that `path` exists and is a dir.

    `include_files=False` is the historical FolderPicker contract —
    only directories are returned. `include_files=True` adds regular
    files so the in-app FilePickerModal can render them alongside dirs.
    Special entries (sockets, fifos, devices) are filtered out either
    way — they're never useful to hand to Claude.
    """
    entries: list[FsEntryOut] = []
    for child in sorted(path.iterdir(), key=lambda p: p.name.lower()):
        if not hidden and child.name.startswith("."):
            continue
        try:
            is_dir = child.is_dir()
            is_file = child.is_file()
        except OSError:
            # Broken symlink or racing deletion — skip rather than 500
            # the whole listing.
            continue
        if is_dir:
            entries.append(FsEntryOut(name=child.name, path=str(child), is_dir=True))
        elif include_files and is_file:
            entries.append(FsEntryOut(name=child.name, path=str(child), is_dir=False))
    parent = str(path.parent) if path.parent != path else None
    return FsListOut(path=str(path), parent=parent, entries=entries)


@router.get("/list", response_model=FsListOut)
async def list_dir(
    path: str | None = None,
    hidden: bool = False,
    include_files: bool = False,
) -> FsListOut:
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
        return _list_dir(resolved, hidden=hidden, include_files=include_files)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="permission denied") from exc


def _pick_command(
    *,
    mode: PickMode,
    start: str | None,
    multiple: bool,
    title: str,
) -> list[str] | None:
    """Build the argv for whichever native picker is available.

    Returns None when neither zenity nor kdialog is on PATH — the route
    responds 501 so the UI can surface an actionable install hint
    instead of silently failing. `mode='directory'` switches both
    binaries into their directory-selection flavors; multi-select is
    silently ignored for directories (neither zenity nor kdialog
    supports picking multiple dirs in one shot).
    """
    if shutil.which("zenity"):
        # --width/--height keep the dialog at a dialog-sized dialog.
        # Without these, GTK opens at whatever size the compositor
        # hands it — on tiling WMs (Hyprland) that means "fill the
        # workspace" unless a float rule intercepts, which is the UX
        # Dave specifically doesn't want.
        argv = [
            "zenity",
            "--file-selection",
            f"--title={title}",
            "--width=720",
            "--height=480",
        ]
        if mode == "directory":
            argv.append("--directory")
        elif multiple:
            # zenity returns `|`-separated paths when --multiple is set;
            # --separator swaps that to NUL so paths containing `|`
            # parse cleanly.
            argv.extend(["--multiple", "--separator=\0"])
        if start:
            # zenity wants a trailing slash on dirs to open inside them.
            arg = start if not start.endswith("/") else start
            argv.append(f"--filename={arg}")
        return argv
    if shutil.which("kdialog"):
        argv = ["kdialog", "--title", title]
        start_arg = start or str(Path.home())
        if mode == "directory":
            argv.append("--getexistingdirectory")
            argv.append(start_arg)
        else:
            argv.append("--getopenfilename")
            argv.append(start_arg)
            if multiple:
                argv.append("--multiple")
                argv.append("--separate-output")
        return argv
    return None


_THEME_DIRS = ("/usr/share/themes", str(Path.home() / ".themes"))
# Preferred dark GTK themes in order. Breeze-Dark first because it's
# Kubuntu's out-of-box dark palette and the closest cool-grey match
# for Bearings' `slate-900` background.
_DARK_THEME_CANDIDATES = ("Breeze-Dark", "Adwaita-dark")


def _pick_dark_gtk_theme() -> str | None:
    """First candidate whose theme directory exists on disk. Returns
    None if nothing installed — caller then lets zenity follow the
    user's GTK default rather than forcing a broken theme name (which
    GTK silently falls back on, but the result is inconsistent).
    """
    for name in _DARK_THEME_CANDIDATES:
        for root in _THEME_DIRS:
            if Path(root, name).is_dir():
                return name
    return None


def _picker_env() -> dict[str, str]:
    """Build the env the subprocess should inherit. Starts from the
    server's env so Wayland/display variables survive, then layers the
    dark-theme hints on top. Setting `GTK_THEME` with `:dark` suffix
    is GTK3's canonical way to request the dark flavor of an ambiguous
    theme; we additionally pass `GTK_APPLICATION_PREFER_DARK_THEME`
    for zenity builds that read that hint.
    """
    env = dict(os.environ)
    theme = _pick_dark_gtk_theme()
    if theme is not None:
        env["GTK_THEME"] = theme
        env["GTK_APPLICATION_PREFER_DARK_THEME"] = "1"
    return env


async def _run_picker(argv: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_picker_env(),
    )
    try:
        stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=_PICK_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise HTTPException(status_code=504, detail="file picker timed out") from exc
    return proc.returncode or 0, stdout_b.decode("utf-8", errors="replace")


@router.post("/pick", response_model=FsPickOut)
async def pick_path(
    mode: PickMode = "file",
    start: str | None = None,
    multiple: bool = False,
    title: str = "Select",
) -> FsPickOut:
    """Pop a native picker and return the chosen absolute path(s).

    Bearings is single-user/localhost, so "native dialog the user sees
    on their own desktop" is the right UX — the browser's own file
    picker sandboxes absolute paths, and drag-and-drop on Wayland/Chrome
    is unreliable. Supports both file (`mode='file'`) and directory
    (`mode='directory'`) selection; directory picks ignore `multiple`.
    """
    argv = _pick_command(mode=mode, start=start, multiple=multiple, title=title)
    if argv is None:
        raise HTTPException(
            status_code=501,
            detail="no native file picker available (install zenity or kdialog)",
        )
    code, stdout = await _run_picker(argv)
    # Both zenity and kdialog return non-zero when the user cancels.
    # Empty stdout with a 0 exit (shouldn't happen in practice) is
    # treated the same way — nothing to surface.
    if code != 0 or not stdout.strip():
        return FsPickOut(path=None, paths=[], cancelled=True)
    # zenity --multiple with NUL separator gives us unambiguous splits
    # (paths with embedded newlines would otherwise fracture). Single-
    # pick and kdialog --separate-output emit one path per line.
    sep = "\0" if "\0" in stdout else "\n"
    paths = [p.strip() for p in stdout.split(sep) if p.strip()]
    if not paths:
        return FsPickOut(path=None, paths=[], cancelled=True)
    return FsPickOut(path=paths[0], paths=paths, cancelled=False)
