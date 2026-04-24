"""Vault: read-only browsing of on-disk plans and TODO.md files.

Surfaces the planning markdown scattered across Dave's setup — plans
under `~/.claude/plans/` and per-project `TODO.md` files — inside
Bearings so he doesn't have to terminal-hop to read them. Read-only
by design: editing `TODO.md` from the UI would race the "append in
the moment" rule and the on-disk files are the source of truth for
multiple tools (editor, git, agent sessions).

Security posture mirrors `routes_fs.py`: localhost-only, requires
auth when enabled, and every file read resolves the target and
checks it belongs to the current indexed set before returning bytes.
The index itself is built from `settings.vault.plan_roots` and
`settings.vault.todo_globs` — paths outside that configured surface
are not reachable through this router, even with a crafted `path`
parameter.
"""

from __future__ import annotations

import glob as _glob
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from bearings.api.auth import require_auth
from bearings.api.models import (
    VaultDocOut,
    VaultEntryOut,
    VaultIndexOut,
    VaultSearchHit,
    VaultSearchOut,
)
from bearings.config import Settings

router = APIRouter(
    prefix="/vault",
    tags=["vault"],
    dependencies=[Depends(require_auth)],
)

# Cap search result count so a one-letter query can't serialize the
# entire vault back to the browser. 200 is enough to surface every
# reasonable hit without choking the UI; the `truncated` flag tells the
# frontend to prompt for a narrower query.
_SEARCH_LIMIT = 200
# Title lookup reads the head of the file for the first `# heading`.
# 4 KB covers every file in the current vault by a wide margin and
# keeps the index cheap when the set grows.
_TITLE_READ_BYTES = 4096
# Trim search snippets to keep the wire payload bounded on long lines
# (e.g. a TODO entry that embeds a one-line error message).
_SEARCH_SNIPPET_MAX = 240

_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

# Match the VaultEntryOut / VaultDocOut discriminator so the wire-format
# constructor accepts the field without a cast.
VaultKind = Literal["plan", "todo"]


@dataclass(frozen=True)
class _Entry:
    """Internal index row. Path is always resolved-absolute so the
    equality check in `/doc` and `/search` compares real filesystem
    identities, not symlink aliases."""

    path: Path
    kind: VaultKind


def _expand_plan_roots(cfg: Settings) -> list[Path]:
    """Resolve configured plan roots to absolute paths. Missing
    directories are silently skipped — a user without any plans yet
    should see an empty index, not a 500."""
    out: list[Path] = []
    for raw in cfg.vault.plan_roots:
        resolved = Path(raw).expanduser().resolve(strict=False)
        if resolved.is_dir():
            out.append(resolved)
    return out


def _expand_todo_globs(cfg: Settings) -> list[Path]:
    """Resolve configured TODO globs to a de-duped, sorted path list.
    Uses stdlib `glob` with `recursive=True` so the `**` wildcard walks
    subdirectories without needing per-pattern manual expansion."""
    seen: set[Path] = set()
    for pattern in cfg.vault.todo_globs:
        expanded = str(Path(pattern).expanduser())
        for match in _glob.glob(expanded, recursive=True):
            p = Path(match).resolve(strict=False)
            if p.is_file():
                seen.add(p)
    return sorted(seen)


def _scan_plans(roots: list[Path]) -> list[_Entry]:
    """Flat listing of every `.md` file directly under each plan
    root. We don't recurse — the plans directory is intentionally flat
    and sub-dirs there would be archival, not browsable."""
    out: list[_Entry] = []
    for root in roots:
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_file() and child.suffix == ".md":
                out.append(_Entry(path=child.resolve(strict=False), kind="plan"))
    return out


def _build_index(cfg: Settings) -> list[_Entry]:
    """Combined plan + todo index. Rebuilt on every request — the walk
    is O(files-in-vault) and the filesystem cache makes repeat scans
    effectively free, so the simpler no-cache shape wins over
    invalidation bugs."""
    entries = _scan_plans(_expand_plan_roots(cfg))
    entries += [_Entry(path=p, kind="todo") for p in _expand_todo_globs(cfg)]
    return entries


def _read_title(path: Path) -> str | None:
    """First `# ` heading in the file, or `None`. Reads the head only
    — every doc in the vault puts its title in the first few lines."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(_TITLE_READ_BYTES)
    except OSError:
        return None
    m = _HEADING_RE.search(head)
    return m.group(1).strip() if m else None


def _entry_to_out(entry: _Entry) -> VaultEntryOut:
    """Convert an index entry to its wire-format row. Stat failures
    degrade gracefully: a file that vanished between scan and stat
    still renders rather than 500-ing the whole index."""
    try:
        stat = entry.path.stat()
        mtime = stat.st_mtime
        size = stat.st_size
    except OSError:
        mtime = 0.0
        size = 0
    return VaultEntryOut(
        path=str(entry.path),
        kind=entry.kind,
        slug=entry.path.stem,
        title=_read_title(entry.path),
        mtime=mtime,
        size=size,
    )


@router.get("/index", response_model=VaultIndexOut)
async def get_index(request: Request) -> VaultIndexOut:
    """Return every vault-visible doc, bucketed by kind and sorted
    newest-first within each bucket."""
    cfg: Settings = request.app.state.settings
    entries = _build_index(cfg)
    plans = [_entry_to_out(e) for e in entries if e.kind == "plan"]
    todos = [_entry_to_out(e) for e in entries if e.kind == "todo"]
    plans.sort(key=lambda x: x.mtime, reverse=True)
    todos.sort(key=lambda x: x.mtime, reverse=True)
    return VaultIndexOut(plans=plans, todos=todos)


def _allowed_set(cfg: Settings) -> dict[Path, VaultKind]:
    """Map of allowed-path → kind for the current index. Used by
    `/doc` both as the allowlist gate and as the source of the `kind`
    field on the response — no second classification pass needed."""
    return {e.path: e.kind for e in _build_index(cfg)}


@router.get("/doc", response_model=VaultDocOut)
async def get_doc(request: Request, path: str = Query(...)) -> VaultDocOut:
    """Return the full markdown body of a vault doc. The `path` param
    must be absolute and must resolve to a file that appears in the
    current index — paths outside the configured surface 403 even
    when they exist and are readable by the server process."""
    cfg: Settings = request.app.state.settings
    target = Path(path)
    if not target.is_absolute():
        raise HTTPException(status_code=400, detail="path must be absolute")
    try:
        resolved = target.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=404, detail="doc not found") from exc
    allowed = _allowed_set(cfg)
    if resolved not in allowed:
        raise HTTPException(status_code=403, detail="path is outside the vault")
    try:
        body = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=500, detail="unable to read doc") from exc
    stat = resolved.stat()
    return VaultDocOut(
        path=str(resolved),
        kind=allowed[resolved],
        slug=resolved.stem,
        title=_read_title(resolved),
        mtime=stat.st_mtime,
        size=stat.st_size,
        body=body,
    )


def _search_one(path: Path, pattern: re.Pattern[str]) -> list[VaultSearchHit]:
    """Scan one file for matches. Returns an empty list on read error
    so a single unreadable file doesn't fail the whole query."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits: list[VaultSearchHit] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            snippet = line.strip()[:_SEARCH_SNIPPET_MAX]
            hits.append(VaultSearchHit(path=str(path), line=lineno, snippet=snippet))
    return hits


@router.get("/search", response_model=VaultSearchOut)
async def search(
    request: Request,
    q: str = Query(..., min_length=1),
) -> VaultSearchOut:
    """Case-insensitive substring search across every vault doc. No
    regex surface exposed to the client — the query is escaped so a
    user typing `foo.bar` matches the literal string, not a regex."""
    cfg: Settings = request.app.state.settings
    pattern = re.compile(re.escape(q), re.IGNORECASE)
    hits: list[VaultSearchHit] = []
    truncated = False
    for entry in _build_index(cfg):
        hits.extend(_search_one(entry.path, pattern))
        if len(hits) >= _SEARCH_LIMIT:
            truncated = True
            break
    return VaultSearchOut(
        query=q,
        hits=hits[:_SEARCH_LIMIT],
        truncated=truncated,
    )
