"""Per-turn directory-context brief renderer (v0.6.1).

The prompt assembler calls `format_directory_brief(working_dir)` on
every turn (same cadence as tag memories) and inserts the rendered
text as a `directory_bearings` layer between `tag_memory` and
`session`. Pre-onboarding directories — no `.bearings/` yet — return
`None` and the layer is skipped silently.

Sources, in render order:
  - manifest summary (one line: name, path, language)
  - state environment block (branch, dirty, lockfile freshness)
  - all pending operations (oldest first, with stale flag for ops
    whose `started` is more than `_STALE_OP_DAYS` ago)
  - last `_HISTORY_TAIL` history.jsonl lines

Hard cap: `_BRIEF_CHAR_BUDGET` chars total. The 800-token target from
the v0.4 spec maps to roughly 3200 chars at 4 chars/token. Sections
truncate independently so a runaway pending list can't starve the
manifest header.

Pure read — no writes. Safe to call per-turn from the prompt
assembler. Filesystem misses (no `.bearings/`, missing manifest)
produce `None` rather than raising; the assembler treats that as
"no layer this turn."
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from bearings.bearings_dir.io import (
    HISTORY_FILE,
    MANIFEST_FILE,
    PENDING_FILE,
    STATE_FILE,
    bearings_path,
    read_history,
    read_toml_model,
)
from bearings.bearings_dir.on_open import OnOpenResult, read_last_on_open
from bearings.bearings_dir.schema import (
    HistoryEntry,
    Manifest,
    Pending,
    PendingOperation,
    State,
)

# Total render budget. Matches the v0.4 spec's "~800 token" cap at
# the assembler's 4-chars-per-token estimate (`agent.prompt.estimate_tokens`).
_BRIEF_CHAR_BUDGET = 3200

# Tail length when reading `history.jsonl` for the brief. Ten lines
# is "the last few sessions" without dragging long-running directories
# into multi-KB layers.
_HISTORY_TAIL = 10

# A pending op whose `started` is older than this is rendered with a
# `STALE` prefix in the brief. The 30-day threshold is from the v0.4
# spec — long enough that legitimately long-running ops (months-long
# refactors) aren't false-flagged on day 31, but short enough that an
# op forgotten across a vacation is visible on return.
_STALE_OP_DAYS = 30

# Per-section caps so a runaway value can't crowd out the rest of the
# brief. The total is intentionally larger than `_BRIEF_CHAR_BUDGET`
# because the final assembly truncates the joined string; these caps
# are first-pass guards that keep individual sections sane even if
# the whole-brief truncate disappears later.
_MAX_PENDING_RENDERED = 20
_MAX_HISTORY_RENDERED = _HISTORY_TAIL


def _render_manifest_line(manifest: Manifest) -> str:
    """Single-line identity header. The path is included even though
    it's redundant with the working_dir context — agents that quote
    the brief back to the user benefit from a self-contained line."""
    parts = [f"**{manifest.name}**"]
    if manifest.language:
        parts.append(f"({manifest.language})")
    parts.append(f"at `{manifest.path}`")
    line = " ".join(parts)
    if manifest.description:
        line = f"{line}\n{manifest.description}"
    return line


def _render_state_line(state: State) -> str:
    """Branch + tree state + lockfile freshness in one short paragraph.
    Lockfile-fresh `None` means "unknown" (e.g. `uv` not on PATH); we
    surface that as a hint rather than a problem so the agent doesn't
    treat a missing tool as a project defect."""
    bits: list[str] = []
    if state.branch:
        tree = "dirty" if state.dirty else "clean"
        bits.append(f"branch `{state.branch}` ({tree})")
    elif state.dirty is not None:
        bits.append("dirty tree" if state.dirty else "clean tree")
    env = state.environment
    if env.lockfile_fresh is True:
        bits.append("lockfile fresh")
    elif env.lockfile_fresh is False:
        bits.append("lockfile STALE — run `uv sync`")
    if env.last_validated:
        age = datetime.now(UTC) - env.last_validated
        bits.append(f"last validated {_humanize_age(age)} ago")
    if not bits:
        return ""
    return "State: " + ", ".join(bits)


def _humanize_age(delta: timedelta) -> str:
    """Coarse human-friendly rendering. Days for >24h, hours otherwise.
    Used for both `last_validated` and pending-op `started`; the
    granularity is deliberately rough — minute-level precision in a
    once-per-turn brief just adds noise."""
    total_seconds = max(0, int(delta.total_seconds()))
    if total_seconds >= 86400:
        days = total_seconds // 86400
        return f"{days}d"
    hours = total_seconds // 3600
    if hours <= 0:
        return "<1h"
    return f"{hours}h"


def _render_pending(ops: list[PendingOperation]) -> str:
    """Pending-ops block. Oldest first so a stale 30-day op shows up
    at the top where the agent reads it before the fresh ones. Empty
    list returns an empty string so the assembler omits the section."""
    if not ops:
        return ""
    now = datetime.now(UTC)
    stale_cutoff = timedelta(days=_STALE_OP_DAYS)
    lines: list[str] = ["Pending operations:"]
    for op in ops[:_MAX_PENDING_RENDERED]:
        age = now - op.started
        prefix = "STALE " if age >= stale_cutoff else ""
        head = f"  - {prefix}`{op.name}` (started {_humanize_age(age)} ago)"
        if op.description:
            head = f"{head}: {op.description}"
        lines.append(head)
        if op.command:
            lines.append(f"      command: {op.command}")
    if len(ops) > _MAX_PENDING_RENDERED:
        lines.append(f"  … and {len(ops) - _MAX_PENDING_RENDERED} more")
    return "\n".join(lines)


def _render_on_open(result: OnOpenResult) -> str:
    """Compact rendering of the most recent `on_open.sh` run. Headline
    line carries the verdict (OK / FAIL / TIMEOUT) and exit code; a
    short stderr/stdout tail follows when there's content worth
    seeing. Empty or all-success runs collapse to one line — the brief
    is precious real estate."""
    age = datetime.now(UTC) - result.ran_at
    age_str = _humanize_age(age)
    if result.timed_out:
        verdict = f"TIMED OUT after {result.duration_ms} ms"
    elif result.exit_code == 0:
        verdict = f"OK (exit 0, {result.duration_ms} ms)"
    else:
        verdict = f"FAIL exit {result.exit_code} ({result.duration_ms} ms)"
    lines = [f"on_open.sh: {verdict}, ran {age_str} ago"]
    # Surface stderr first when failing — that's the diagnostic tail
    # users actually need. Cap each rendered stream tightly here so the
    # whole brief stays inside the 3200-char budget; persisted snippets
    # are already capped at 1024 bytes by the runner.
    if result.exit_code not in (0, None) or result.timed_out:
        if result.stderr_snippet.strip():
            lines.append("  stderr:")
            for snippet_line in result.stderr_snippet.splitlines()[-8:]:
                lines.append(f"    {snippet_line}")
        elif result.stdout_snippet.strip():
            lines.append("  stdout:")
            for snippet_line in result.stdout_snippet.splitlines()[-8:]:
                lines.append(f"    {snippet_line}")
    return "\n".join(lines)


def _render_history(entries: list[HistoryEntry]) -> str:
    """Tail of history.jsonl. One line per entry — start markers and
    end markers are shown as separate rows because each carries its
    own status. Empty input returns empty string."""
    if not entries:
        return ""
    lines: list[str] = [f"Recent sessions (last {len(entries)}):"]
    for entry in entries[-_MAX_HISTORY_RENDERED:]:
        ts = entry.started.strftime("%Y-%m-%d %H:%M")
        sid_short = entry.session_id[:8]
        branch = f" [{entry.branch}]" if entry.branch else ""
        if entry.ended is not None:
            tail = f"ended {entry.ended.strftime('%H:%M')}, {entry.status}"
        else:
            tail = f"{entry.status} (no end marker — likely crashed)"
        suffix = ""
        if entry.summary:
            suffix = f" — {entry.summary}"
        if entry.commits:
            suffix = f"{suffix} ({len(entry.commits)} commits)"
        lines.append(f"  - {ts} {sid_short}{branch}: {tail}{suffix}")
    return "\n".join(lines)


def _truncate(text: str, limit: int) -> str:
    """Cut to `limit` chars with a visible marker. Used as the last-line-
    of-defense to keep the whole brief under budget; per-section caps
    above usually mean we never hit this."""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 16)] + "\n…[brief truncated]"


def format_directory_brief(working_dir: Path | str) -> str | None:
    """Render the per-turn directory-context brief.

    Returns `None` when `.bearings/manifest.toml` isn't present —
    pre-onboarding directories silently skip the layer instead of
    emitting an empty section.

    Filesystem reads only; never writes. Corrupt files are quarantined
    by `read_toml_model` / `read_history` and the affected section
    silently shrinks; the rest of the brief still renders.
    """
    directory = Path(working_dir)
    root = bearings_path(directory)
    manifest_path = root / MANIFEST_FILE
    manifest = read_toml_model(manifest_path, Manifest)
    if manifest is None:
        return None

    sections: list[str] = []
    sections.append(_render_manifest_line(manifest))

    state = read_toml_model(root / STATE_FILE, State)
    if state is not None:
        state_line = _render_state_line(state)
        if state_line:
            sections.append(state_line)

    pending = read_toml_model(root / PENDING_FILE, Pending)
    if pending is not None and pending.operations:
        ops = sorted(pending.operations, key=lambda op: op.started)
        rendered = _render_pending(ops)
        if rendered:
            sections.append(rendered)

    # `on_open.sh` result (v0.6.3). Sits between pending and history
    # so the agent reads "what's still in flight" → "what the user's
    # health probe says about the workspace right now" → "what the
    # last few sessions did." Sidecar-missing returns None and the
    # section is silently skipped — most directories won't have a
    # check installed.
    on_open_result = read_last_on_open(directory)
    if on_open_result is not None:
        sections.append(_render_on_open(on_open_result))

    history = read_history(root / HISTORY_FILE, tail=_HISTORY_TAIL)
    rendered_history = _render_history(history)
    if rendered_history:
        sections.append(rendered_history)

    body = "\n\n".join(sections)
    return _truncate(body, _BRIEF_CHAR_BUDGET)


def has_stale_pending_ops(working_dir: Path | str) -> bool:
    """True iff at least one pending op is older than the stale
    threshold. Helper for callers (tests, future UI badge) that want
    a boolean signal without parsing the brief text."""
    directory = Path(working_dir)
    root = bearings_path(directory)
    pending = read_toml_model(root / PENDING_FILE, Pending)
    if pending is None or not pending.operations:
        return False
    cutoff = datetime.now(UTC) - timedelta(days=_STALE_OP_DAYS)
    return any(op.started < cutoff for op in pending.operations)


__all__ = [
    "format_directory_brief",
    "has_stale_pending_ops",
]
