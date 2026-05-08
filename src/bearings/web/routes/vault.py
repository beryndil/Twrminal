"""Vault read-only markdown routes.

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/vault.py`` owns
the read-only markdown surface for the vault subsystem. Per
``docs/behavior/vault.md`` the user observes:

* ``GET /api/vault`` — bucketed list of plans + todos. Re-scans the
  filesystem on every request (vault.md §"Failure modes" — "Stale
  mtime. The vault re-scans on every list request").
* ``GET /api/vault/{id}`` — open one doc by cache id; returns the
  raw body, a list of redaction ranges (vault.md §"Redaction
  rendering"), and a ``truncated`` flag indicating whether the body
  was capped.
* ``GET /api/vault/by-path?path=...`` — open one doc by absolute
  path; resolves symlinks before the allowlist check (vault.md
  §"Failure modes" → "Path outside the vault").
* ``GET /api/vault/search?q=...`` — case-insensitive substring
  search over every vault doc (vault.md §"Search semantics").

The handler bodies stay thin per arch §1.1.5: argument parsing,
single agent-layer call, response formatting. Errors follow the
shape established by :mod:`bearings.web.routes.tags` — 404 for
absent / out-of-vault, 400 for missing query, 503 when the DB
connection isn't wired.

Configuration source
--------------------

The vault scan reads :class:`bearings.config.settings.VaultCfg` off
``app.state.vault_cfg`` (set by :func:`bearings.web.app.create_app`).
Tests inject a freshly-constructed ``VaultCfg`` whose roots / globs
point at a ``tmp_path`` so the vault surface is deterministic.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request, status

from bearings.agent import vault as vault_agent
from bearings.config.settings import VaultCfg
from bearings.db import vault as vault_db
from bearings.db.vault import VaultEntry
from bearings.web.models.vault import (
    RedactionOut,
    SearchHitOut,
    SearchResultOut,
    VaultDocOut,
    VaultEntryOut,
    VaultListOut,
)

router = APIRouter()


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state``.

    Mirrors :func:`bearings.web.routes.tags._db`; raises 503 if the
    streaming-only surface from item 1.2 is in effect.
    """
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return db  # type: ignore[no-any-return]


def _cfg(request: Request) -> VaultCfg:
    """Pull the :class:`VaultCfg` off ``app.state``.

    Mirrors :func:`bearings.web.routes.vault._db`; raises 503 when
    ``vault_cfg`` is absent or ``None`` on ``app.state``.

    In production :func:`bearings.web.app.create_app` always sets the
    slot (defaulting to a fresh ``VaultCfg()`` when the caller passes
    ``None``), so this branch only fires if something external clears
    the state after startup — treated as a misconfiguration, not a
    silent default.
    """
    cfg = getattr(request.app.state, "vault_cfg", None)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="vault_cfg not configured on app.state",
        )
    if not isinstance(cfg, VaultCfg):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="vault_cfg on app.state is not a VaultCfg instance",
        )
    return cfg


def _to_entry_out(entry: VaultEntry) -> VaultEntryOut:
    """Wire shape for a vault row, with server-computed markdown link."""
    return VaultEntryOut(
        id=entry.id,
        path=entry.path,
        slug=entry.slug,
        title=entry.title,
        kind=entry.kind,
        mtime=entry.mtime,
        size=entry.size,
        last_indexed_at=entry.last_indexed_at,
        markdown_link=vault_agent.build_markdown_link(entry),
    )


def _bucket(entries: list[VaultEntry], kind: str) -> list[VaultEntryOut]:
    """Filter ``entries`` to ``kind`` and translate to wire shape."""
    return [_to_entry_out(e) for e in entries if e.kind == kind]


@router.get("/api/vault", response_model=VaultListOut, operation_id="list-vault")
async def list_vault(request: Request) -> VaultListOut:
    """Re-scan the filesystem and return bucketed plans + todos.

    Per vault.md §"Failure modes" the index re-scans on every list
    request. Plans / todos sections come back already sorted
    newest-mtime first by :func:`bearings.db.vault.list_all`.
    """
    db = _db(request)
    cfg = _cfg(request)
    entries = await vault_agent.rescan(db, cfg)
    return VaultListOut(
        plans=_bucket(entries, "plan"),
        todos=_bucket(entries, "todo"),
        plan_roots=[str(p) for p in cfg.plan_roots],
        todo_globs=list(cfg.todo_globs),
    )


@router.get("/api/vault/search", response_model=SearchResultOut, operation_id="search-vault")
async def search_vault(
    request: Request,
    q: str = Query(..., description="Case-insensitive substring query."),
) -> SearchResultOut:
    """Run a substring search across every vault doc.

    Per vault.md §"Search semantics" the query is treated as a
    literal string (no regex), case-insensitive, line-grained.
    Re-scans the filesystem first so the search reads fresh content.
    A blank query (whitespace only) returns an empty result.
    """
    db = _db(request)
    cfg = _cfg(request)
    entries = await vault_agent.rescan(db, cfg)
    result = vault_agent.search_entries(entries, q)
    return SearchResultOut(
        hits=[
            SearchHitOut(
                vault_id=hit.vault_id,
                path=hit.path,
                title=hit.title,
                kind=hit.kind,
                line_number=hit.line_number,
                snippet=hit.snippet,
            )
            for hit in result.hits
        ],
        capped=result.capped,
    )


@router.get("/api/vault/by-path", response_model=VaultDocOut, operation_id="get-vault-doc-by-path")
async def get_vault_doc_by_path(
    request: Request,
    path: str = Query(..., description="Absolute path of a vault doc."),
) -> VaultDocOut:
    """Open a doc by absolute path; refuses paths outside the vault.

    Per vault.md §"Failure modes" — "Path outside the vault.
    Attempts (e.g. via a hand-crafted URL) to open a path that is
    not in the current index are refused — the user sees 'this path
    is outside the vault.' Symlinks are resolved before the
    allowlist check, so a symlink trick into the vault still
    resolves to the real path and is gated correctly".

    The handler rescans first so a brand-new doc on disk is
    reachable without a separate ``GET /api/vault`` call.
    """
    db = _db(request)
    cfg = _cfg(request)
    entries = await vault_agent.rescan(db, cfg)
    # ``resolve_in_vault`` does the synchronous Path.resolve() once
    # and returns the resolved path string (or ``None`` when outside
    # the vault). Doing the resolve here — before the next DB await
    # — keeps :class:`pathlib.Path` syscalls off the event loop's
    # async stack (ruff ASYNC240).
    resolved = vault_agent.resolve_in_vault(Path(path), entries)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"path {path!r} is outside the vault",
        )
    entry = await vault_db.get_by_path(db, resolved)
    if entry is None:
        # The path resolved into the vault per the entries snapshot
        # but the cache lookup returned nothing — should not happen
        # because :func:`rescan` just wrote the cache, but treat it
        # defensively as a 404.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"path {path!r} not in vault index",
        )
    return _build_doc_out(entry)


@router.get("/api/vault/{vault_id}", response_model=VaultDocOut, operation_id="get-vault-doc")
async def get_vault_doc(vault_id: int, request: Request) -> VaultDocOut:
    """Open one vault doc by cache id; 404 if absent.

    Reads the raw body off disk, runs server-side redaction
    detection, and returns the entry + body + redaction ranges +
    truncated flag. Per vault.md §"Redaction rendering" the body is
    raw — the client masks visually and exposes a "Show" toggle per
    redaction.

    Does NOT rescan first: callers that want freshness are expected
    to pull ``GET /api/vault`` (which always rescans) for the
    discovery handle, then call this endpoint for the specific id.
    Rescanning here would invalidate the id mid-request when paths
    move under the user's editor.
    """
    db = _db(request)
    entry = await vault_db.get(db, vault_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"vault entry {vault_id} not found",
        )
    return _build_doc_out(entry)


def _build_doc_out(entry: VaultEntry) -> VaultDocOut:
    """Read body + detect redactions; assemble the wire response.

    Per vault.md §"Failure modes" — "Read error on a single doc.
    A doc the server can't read … does not crash the index". The
    open path here surfaces an empty body + empty redactions on
    read error, with the entry metadata still surfacing — the
    frontend renders the "unable to read" inline badge based on the
    entry's ``size > 0`` vs the empty body.

    Truncation: if the on-disk size exceeds
    :data:`bearings.config.constants.VAULT_BODY_MAX_CHARS`, the
    returned body carries the truncation marker; the ``truncated``
    flag tells the client to show "doc was very large" affordance.
    """
    try:
        read = vault_agent.read_body(Path(entry.path))
        body = read.body
        truncated = read.truncated
    except OSError:
        body = ""
        truncated = False
    redactions = vault_agent.detect_redactions(body)
    return VaultDocOut(
        entry=_to_entry_out(entry),
        body=body,
        redactions=[
            RedactionOut(offset=r.offset, length=r.length, pattern=r.pattern) for r in redactions
        ],
        truncated=truncated,
    )


__all__ = ["router"]
