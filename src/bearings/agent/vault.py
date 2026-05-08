"""Vault service layer — filesystem scan, search, redaction.

Per ``docs/architecture-v1.md`` §1.1.4 the ``agent`` layer owns
domain-level glue between the storage layer (:mod:`bearings.db.vault`)
and the read-only filesystem index. Per ``docs/behavior/vault.md`` the
vault is "a read-only browser over the user's on-disk planning markdown
— `~/.claude/plans/*.md`, project `TODO.md` files…"; this module
implements every observable behavior the doc lists:

* :func:`scan_filesystem` — produce :class:`ScannedDoc` from
  configured plan roots + TODO globs (vault.md §"Vault entry types").
* :func:`extract_title` — first ``# heading`` from a markdown body
  (vault.md §"Vault entry types").
* :func:`read_body` — read a doc body off disk with size cap +
  truncation marker (vault.md §"When the user opens the vault" plus
  the ``VAULT_BODY_MAX_CHARS`` defensive bound from constants).
* :func:`search_entries` — case-insensitive substring search over a
  set of entries' bodies; returns flat list of hits with line number
  + snippet (vault.md §"Search semantics").
* :func:`detect_redactions` — server-side detection of credential-
  shaped tokens; returns ranges the client masks (vault.md
  §"Redaction rendering").
* :func:`is_path_in_vault` — symlink-aware allowlist check
  (vault.md §"Failure modes" → "Path outside the vault").
* :func:`build_markdown_link` — the ``[Title](file:///abs/path)``
  string the paste-into-composer / Copy-as-Markdown-link surfaces
  emit (vault.md §"Paste-into-message behavior").
* :func:`rescan` — orchestrates :func:`scan_filesystem` + the DB
  layer's :func:`bearings.db.vault.replace_index`. The single call
  the API layer makes for a list request.

Decision trail
--------------

* Redaction is **render-time, server-detected**. Vault.md §"Redaction
  rendering" — "the underlying clipboard-copy paths still receive
  the literal text". The server returns the raw body plus a list of
  (offset, length, pattern) ranges; the client masks visually and
  toggles per-range. Persists no toggle state.
* Search backend is **pure-Python substring**, line-by-line. Vault.md
  prescribes "case-insensitive substring" + "the query is treated as
  a literal string"; the schema does not declare an FTS5 virtual
  table; the doc set is small (≤100 docs typical). Lazy regex /
  FTS would be premature optimisation.
* The ``vault`` table is a **cache**, not the source of truth. Every
  list request re-scans (vault.md §"Failure modes" — "Stale mtime.
  The vault re-scans on every list request"). The cache exists to
  give stable ``id`` handles across rescans (see
  :mod:`bearings.db.vault` for the upsert-by-path discipline).
"""

from __future__ import annotations

import glob as glob_module
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from bearings.config.constants import (
    VAULT_BODY_MAX_CHARS,
    VAULT_BODY_TRUNCATION_MARKER_TEMPLATE,
    VAULT_KIND_PLAN,
    VAULT_KIND_TODO,
    VAULT_REDACTION_KEYWORDS,
    VAULT_REDACTION_MASK_GLYPH,
    VAULT_REDACTION_MIN_VALUE_CHARS,
    VAULT_SEARCH_MAX_LINES_PER_DOC,
    VAULT_SEARCH_RESULT_CAP,
    VAULT_SEARCH_SNIPPET_MAX_CHARS,
)
from bearings.config.settings import VaultCfg
from bearings.db import vault as vault_db
from bearings.db.vault import ScannedDoc, VaultEntry

# ---------------------------------------------------------------------------
# Filesystem scan
# ---------------------------------------------------------------------------


# Horizontal whitespace only ([ \t]) on either side of the heading
# text — using ``\s`` here would cross a newline and let an empty
# ``# \nbody`` heading pull the next line's content as the title.
_TITLE_RE = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_MARKDOWN_SUFFIX = ".md"


def extract_title(body: str) -> str | None:
    """Return the first ``# heading`` (h1) in ``body``, or ``None``.

    Per vault.md §"Vault entry types" — "an optional title (the first
    `# heading` in the file body)". Only h1 (single ``#``) counts; h2
    and deeper are not promoted because the doc convention is that
    h1 = doc title. Matches across the body via :class:`re.MULTILINE`.
    Returns the captured text trimmed of trailing whitespace; an empty
    h1 (``# `` then EOL) yields ``None``.
    """
    match = _TITLE_RE.search(body)
    if match is None:
        return None
    title = match.group(1).strip()
    return title or None


def _scan_plan_roots(cfg: VaultCfg, seen: dict[str, ScannedDoc]) -> None:
    """Walk each plan root (non-recursive) and register .md files in ``seen``."""
    for root in cfg.plan_roots:
        if not root.exists() or not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_file() or entry.suffix != _MARKDOWN_SUFFIX:
                continue
            doc = _build_scanned_doc(entry, kind=VAULT_KIND_PLAN)
            if doc is not None:
                seen[doc.path] = doc


def _scan_todo_globs(cfg: VaultCfg, seen: dict[str, ScannedDoc]) -> None:
    """Expand TODO globs and register docs not already claimed by a plan root."""
    for pattern in cfg.todo_globs:
        for raw_path in sorted(glob_module.iglob(pattern, recursive=True)):
            candidate = Path(raw_path)
            if not candidate.is_file():
                continue
            doc = _build_scanned_doc(candidate, kind=VAULT_KIND_TODO)
            if doc is None or doc.path in seen:
                continue
            seen[doc.path] = doc


def scan_filesystem(cfg: VaultCfg) -> list[ScannedDoc]:
    """Walk plan roots + TODO globs and emit one :class:`ScannedDoc` per file.

    Per vault.md §"Vault entry types":

    * **Plans** — ``.md`` files directly under each configured plan
      root (non-recursive — "Plan roots are flat — sub-directories
      under a plan root are treated as archival and are not
      surfaced").
    * **Todos** — files matched by the configured TODO globs
      (recursive ``**`` permitted because that's how project trees are
      shaped).

    Per vault.md §"Failure modes":

    * Configured roots that don't exist on disk are silently dropped.
    * A doc the server can't read does not crash the index — the
      scanner still emits a row with zero size + ``None`` title and
      lets the open-by-id path surface the read error.
    * Symlinks are resolved before the allowlist check (callers use
      :func:`is_path_in_vault`); the scan itself reports the resolved
      path so duplicate symlinks dedupe naturally.

    Same path emitted by both a plan root and a TODO glob is bucketed
    as a plan (plans win; an explicit plan-root configuration is the
    user's "this is a plan" signal). De-duplication is by resolved
    absolute path so a plan symlinked into a TODO-glob target lands
    once.
    """
    seen: dict[str, ScannedDoc] = {}
    _scan_plan_roots(cfg, seen)
    _scan_todo_globs(cfg, seen)
    return list(seen.values())


def _build_scanned_doc(path: Path, *, kind: str) -> ScannedDoc | None:
    """Resolve + stat ``path`` and produce a :class:`ScannedDoc`.

    Returns ``None`` when the resolve / stat fails — the file
    disappeared between iterdir/glob and the stat call (TOCTOU). Per
    vault.md §"Failure modes" the index keeps moving rather than
    crashing on a transient read error.
    """
    try:
        resolved = path.resolve(strict=True)
        stat_result = resolved.stat()
    except OSError:
        return None
    title: str | None = None
    try:
        # Read just the head of the file for title extraction. Title
        # comes from the first ``# heading`` so a small head-read is
        # sufficient for any realistic doc; this avoids paying the
        # full-file read cost during a cold scan of a big TODO.md.
        with resolved.open(encoding="utf-8", errors="replace") as fh:
            head = fh.read(_TITLE_HEAD_READ_BYTES)
        title = extract_title(head)
    except OSError:
        title = None
    return ScannedDoc(
        path=str(resolved),
        slug=resolved.stem,
        title=title,
        kind=kind,
        mtime=int(stat_result.st_mtime),
        size=int(stat_result.st_size),
    )


# How many bytes to read off the head of a file when extracting the
# title. ``# heading`` is virtually always within the first kilobyte;
# 8 KiB is a generous bound that costs nothing on a typical scan and
# protects against pathological "comment block then heading" docs.
_TITLE_HEAD_READ_BYTES = 8192


# ---------------------------------------------------------------------------
# Body read with cap + truncation marker
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BodyRead:
    """Result of :func:`read_body`: the (possibly truncated) body + flag.

    The ``truncated`` flag is the load-bearing signal — callers that
    want a structured "doc was very large" affordance read it
    directly rather than sniffing the trailing marker text. The
    ``body`` already includes the truncation marker when truncated
    so callers can pass it straight to the renderer.
    """

    body: str
    truncated: bool


def read_body(path: Path, *, max_chars: int = VAULT_BODY_MAX_CHARS) -> BodyRead:
    """Read the markdown body at ``path``, truncating beyond ``max_chars``.

    Per vault.md §"Failure modes" the open-by-id path surfaces a doc
    too large to render in full with a marker rather than wedging the
    response. The marker template
    :data:`bearings.config.constants.VAULT_BODY_TRUNCATION_MARKER_TEMPLATE`
    appends a one-line ``[truncated — N chars elided]`` notice mirroring
    the streaming-truncation marker shape from item 1.2.

    Raises :class:`OSError` (subclasses) on read failure — the caller
    translates to a 5xx / "unable to read" inline badge per vault.md.
    Decoded as UTF-8 with ``errors="replace"`` so a doc with a stray
    binary byte still surfaces.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    if len(raw) <= max_chars:
        return BodyRead(body=raw, truncated=False)
    elided = len(raw) - max_chars
    body = raw[:max_chars] + VAULT_BODY_TRUNCATION_MARKER_TEMPLATE.format(n=elided)
    return BodyRead(body=body, truncated=True)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchHit:
    """One vault search match.

    Per vault.md §"Search semantics" — "the source doc title and its
    kind (Plan / Todo); the line number; a snippet of the matching
    line". Snippets are pre-trimmed to
    :data:`bearings.config.constants.VAULT_SEARCH_SNIPPET_MAX_CHARS`.
    """

    vault_id: int
    path: str
    title: str | None
    kind: str
    line_number: int
    snippet: str

    def __post_init__(self) -> None:
        if self.line_number < 1:
            raise ValueError(f"SearchHit.line_number must be ≥ 1 (got {self.line_number})")


@dataclass(frozen=True)
class SearchResult:
    """Result envelope: hits + capped flag.

    Per vault.md §"Search semantics" — "Result count has a hard cap;
    when the cap is reached the user sees a 'showing first N — narrow
    your query for more' indicator". The ``capped`` boolean drives
    that UI affordance; ``len(hits) <= VAULT_SEARCH_RESULT_CAP``
    always.
    """

    hits: tuple[SearchHit, ...]
    capped: bool


def search_entries(
    entries: Iterable[VaultEntry],
    query: str,
    *,
    snippet_cap: int = VAULT_SEARCH_SNIPPET_MAX_CHARS,
    result_cap: int = VAULT_SEARCH_RESULT_CAP,
    line_cap_per_doc: int = VAULT_SEARCH_MAX_LINES_PER_DOC,
) -> SearchResult:
    """Run a case-insensitive substring search across ``entries``.

    Per vault.md §"Search semantics":

    * **Case-insensitive** — both query and doc body lower-cased
      before comparison.
    * **Literal substring** — ``foo.bar`` matches the literal string
      ``foo.bar``, not a regex.
    * **Line-grained** — each matching line produces one
      :class:`SearchHit`; multiple matches on one line still produce
      one hit (the user sees the line, not every offset).

    A blank query (whitespace only) returns an empty
    :class:`SearchResult` rather than every line — vault.md doesn't
    nominate blank-query behavior, but returning no hits is the
    minimum-surprise default (matches typical search-box UX).

    Iteration order matches the input ``entries`` order (the API layer
    passes the bucketed-by-kind, mtime-DESC list from
    :func:`bearings.db.vault.list_all`); the cap is reached after at
    most ``result_cap`` hits.

    Per-doc safety bound ``line_cap_per_doc`` (defaulting to
    :data:`bearings.config.constants.VAULT_SEARCH_MAX_LINES_PER_DOC`)
    prevents a pathological mis-classified binary file from
    monopolising the search loop. A doc that exceeds the cap stops
    contributing hits and the search continues with the next doc.
    """
    needle = query.strip()
    if not needle:
        return SearchResult(hits=(), capped=False)
    needle_lower = needle.casefold()
    hits: list[SearchHit] = []
    capped = False
    for entry in entries:
        if len(hits) >= result_cap:
            capped = True
            break
        try:
            body = Path(entry.path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            # Per vault.md §"Failure modes" a single unreadable doc
            # does not crash the index. Skip silently — the row still
            # appears in the list with no contribution to search.
            continue
        for line_number, line in enumerate(body.splitlines(), start=1):
            if line_number > line_cap_per_doc:
                break
            if needle_lower not in line.casefold():
                continue
            hits.append(
                SearchHit(
                    vault_id=entry.id,
                    path=entry.path,
                    title=entry.title,
                    kind=entry.kind,
                    line_number=line_number,
                    snippet=_trim_snippet(line, cap=snippet_cap),
                )
            )
            if len(hits) >= result_cap:
                capped = True
                break
    return SearchResult(hits=tuple(hits), capped=capped)


def _trim_snippet(line: str, *, cap: int) -> str:
    """Trim ``line`` to ``cap`` chars + ellipsis if it overflows.

    Mirrors the typical "snippet" shape: short lines pass through, long
    lines truncate to ``cap`` and append a single ``…`` so the user
    sees a clear cut-off marker.
    """
    if len(line) <= cap:
        return line
    return line[:cap] + "…"


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Redaction:
    """One redacted range inside a doc body.

    The client uses ``offset`` + ``length`` to overlay a mask on the
    rendered body and exposes a "Show" toggle that reveals the
    underlying ``length`` characters of the raw body. The pattern name
    is informational (e.g. ``"key"``, ``"token"``) so the client can
    show "API key hidden" hover text per pattern.
    """

    offset: int
    length: int
    pattern: str

    def __post_init__(self) -> None:
        if self.offset < 0:
            raise ValueError(f"Redaction.offset must be ≥ 0 (got {self.offset})")
        if self.length <= 0:
            raise ValueError(f"Redaction.length must be > 0 (got {self.length})")
        if not self.pattern:
            raise ValueError("Redaction.pattern must be non-empty")


# Matches: keyword, optional whitespace, =/:, optional whitespace,
# captured value (greedy non-whitespace, optionally surrounded by
# matching quotes). Captured group #1 = keyword, #2 = value (without
# enclosing quotes). The keyword set comes from
# :data:`bearings.config.constants.VAULT_REDACTION_KEYWORDS`; the
# pattern is assembled at module load so the regex is compiled once.
_REDACTION_KEYWORD_GROUP = "|".join(re.escape(kw) for kw in sorted(VAULT_REDACTION_KEYWORDS))
_REDACTION_RE = re.compile(
    r"(?P<keyword>" + _REDACTION_KEYWORD_GROUP + r")"  # keyword
    r"(?:\s*[=:]\s*|\s+is\s+)"  # `=`, `:`, or ` is ` separator
    r"(?P<quote>['\"]?)"  # optional opening quote
    r"(?P<value>[^\s'\"]+)"  # value (no whitespace / quotes)
    r"(?P=quote)",  # matching closing quote
    re.IGNORECASE,
)


def detect_redactions(
    body: str,
    *,
    min_value_chars: int = VAULT_REDACTION_MIN_VALUE_CHARS,
) -> list[Redaction]:
    """Find credential-shaped tokens in ``body`` and return masking ranges.

    Per vault.md §"Redaction rendering" — "Detects common secret
    shapes (high-entropy strings adjacent to keywords like `key`,
    `token`, `secret`, `password`)". The implementation:

    * Matches ``<keyword>=<value>`` / ``<keyword>: <value>`` /
      ``<keyword> is <value>`` shapes (case-insensitive on the
      keyword).
    * Skips matches whose value is shorter than ``min_value_chars``
      to avoid false positives on short config flags
      (``key=on``).
    * Returns one :class:`Redaction` per match, with ``offset`` /
      ``length`` covering the *value only* — the keyword stays
      visible in the rendered body so the user can tell *what* was
      redacted.

    Returns an empty list when no matches fire. The result is
    ``offset``-sorted (regex matches are returned in left-to-right
    order, which is already sorted).
    """
    redactions: list[Redaction] = []
    for match in _REDACTION_RE.finditer(body):
        value = match.group("value")
        if len(value) < min_value_chars:
            continue
        keyword = match.group("keyword").lower()
        # match.start("value") locates the value within the body
        # (Python's regex captures preserve byte offsets in the
        # original string).
        redactions.append(
            Redaction(
                offset=match.start("value"),
                length=len(value),
                pattern=keyword,
            )
        )
    return redactions


def apply_mask(body: str, redactions: Iterable[Redaction]) -> str:
    """Return ``body`` with each redaction range replaced by the mask glyph.

    Convenience helper for callers (and tests) that want a server-side
    pre-rendered string. The on-the-wire contract still ships the raw
    body + ranges so the client owns the toggle; this helper exists for
    callers that don't need toggling (e.g. a CLI listing).

    Mask glyph is :data:`bearings.config.constants.VAULT_REDACTION_MASK_GLYPH`
    (8 bullet characters) regardless of the original value's length —
    the user sees a fixed-width mask, not a length oracle.
    """
    # Process in reverse so an earlier replacement does not shift
    # later offsets. ``sorted(..., reverse=True)`` is total on offset
    # because Redaction is frozen.
    pieces: list[str] = [body]
    for red in sorted(redactions, key=lambda r: r.offset, reverse=True):
        current = pieces[0]
        pieces[0] = (
            current[: red.offset] + VAULT_REDACTION_MASK_GLYPH + current[red.offset + red.length :]
        )
    return pieces[0]


# ---------------------------------------------------------------------------
# Path safety + paste-into-message
# ---------------------------------------------------------------------------


def is_path_in_vault(candidate: Path, entries: Iterable[VaultEntry]) -> bool:
    """Resolve ``candidate`` and check it matches some entry's path.

    Per vault.md §"Failure modes" — "Symlinks are resolved before the
    allowlist check, so a symlink trick into the vault still resolves
    to the real path and is gated correctly". Thin wrapper around
    :func:`resolve_in_vault` for callers that only need the boolean
    answer.
    """
    return resolve_in_vault(candidate, entries) is not None


def resolve_in_vault(
    candidate: Path,
    entries: Iterable[VaultEntry],
) -> str | None:
    """Return the resolved absolute path string when ``candidate`` is in the vault.

    Returns ``None`` when:

    * the candidate cannot be resolved on disk (does not exist /
      permission denied — :class:`OSError`); or
    * the resolved path is not in the entries snapshot.

    The async route handlers call this helper *before* any DB await
    so the synchronous :class:`pathlib.Path` filesystem syscall does
    not fire from inside an ``async def``. Callers that only need
    the yes/no answer can use :func:`is_path_in_vault`.
    """
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    resolved_str = str(resolved)
    if any(entry.path == resolved_str for entry in entries):
        return resolved_str
    return None


def build_markdown_link(entry: VaultEntry) -> str:
    """Return ``[Title](file:///abs/path)`` for paste-into-composer.

    Per vault.md §"Paste-into-message behavior" — "Drag a vault row
    onto the conversation composer to paste the doc's title-as-
    Markdown-link (`[Title](file:///abs/path)`) into the composer at
    the cursor". The title is the entry's ``title`` if set, else its
    ``slug`` (matches the row-label fallback in vault.md §"When the
    user opens the vault" — "the title (or, when no `# heading`
    exists, the slug)").

    The path is rendered as a ``file://`` URI with three slashes (the
    standard file-URI shape for an absolute path with empty
    authority).
    """
    label = entry.title or entry.slug
    return f"[{label}](file://{entry.path})"


# ---------------------------------------------------------------------------
# Rescan orchestration
# ---------------------------------------------------------------------------


async def rescan(
    connection: aiosqlite.Connection,
    cfg: VaultCfg,
) -> list[VaultEntry]:
    """Scan the filesystem + write the cache + return the bucketed list.

    Single call the API layer makes for ``GET /api/vault``. Steps:

    1. :func:`scan_filesystem` produces the live filesystem state.
    2. :func:`bearings.db.vault.replace_index` upserts/deletes the
       cache to match.
    3. The post-replace cache contents are returned in vault.md's
       "list view" order (kind ASC, mtime DESC).

    Per vault.md §"Failure modes" — "Stale mtime. The vault re-scans
    on every list request" — this function is the one path that
    serves the list, so the contract holds end-to-end.
    """
    scanned = scan_filesystem(cfg)
    return await vault_db.replace_index(connection, scanned)


__all__ = [
    "BodyRead",
    "Redaction",
    "SearchHit",
    "SearchResult",
    "apply_mask",
    "build_markdown_link",
    "detect_redactions",
    "extract_title",
    "is_path_in_vault",
    "read_body",
    "rescan",
    "resolve_in_vault",
    "scan_filesystem",
    "search_entries",
]
