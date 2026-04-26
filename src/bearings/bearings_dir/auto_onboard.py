"""Auto-trigger onboarding (v0.6.2).

When a Bearings session opens in a `working_dir` that has not yet been
onboarded (no `<working_dir>/.bearings/manifest.toml`) but otherwise
looks like a project, the prompt assembler injects a
`directory_onboarding` system-prompt layer instead of the regular
`directory_bearings` brief. The layer carries the freshly-rendered
`Brief` plus instructions telling the agent to:

  1. Present the brief verbatim to the user as the first assistant
     message of the session.
  2. Ask in chat prose whether to save it to `.bearings/`.
  3. On confirmation, call the `bearings__dir_init` MCP tool to write
     the files. Once the manifest exists, the next turn falls through
     to the regular `format_directory_brief` path and this layer
     drops out — no per-runner state to track.

Pure read against the target directory. The layer is gated on at
least one project marker existing so opening a session in `~` or a
random temp dir doesn't volunteer a brief.

Failure modes (subprocess errors, unicode-broken paths) are caught
and surfaced as `None` so a flaky FS never blocks prompt assembly —
matching the same fail-open posture as `format_directory_brief`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from bearings.bearings_dir.io import MANIFEST_FILE, bearings_path
from bearings.bearings_dir.onboard import (
    Brief,
    render_brief,
    run_onboarding,
)

log = logging.getLogger(__name__)


# Markers that count as "this directory has enough shape to be worth
# onboarding." Mirrors `_PROJECT_MARKERS` in `onboard.py` minus the
# narrative-only entries — `README.md` alone in `~/Documents` is not a
# project, but `pyproject.toml` or `.git` is. Keeps auto-trigger
# honest: opening a session in a random folder does NOT volunteer a
# brief.
_TRIGGER_MARKERS: tuple[str, ...] = (
    ".git",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
)


# Char budget for the onboarding layer. Larger than the per-turn brief
# cap (3200) because this fires exactly once and the agent needs the
# full brief to quote it verbatim — truncating would defeat the
# Twrminal-style historical-name signal that ships in step 5.
_ONBOARDING_LAYER_BUDGET = 6000


# Header copy the agent reads. Tells it (a) what the brief is, (b)
# what the user expects to see, (c) which tool to call on confirm,
# (d) what NOT to do (no silent writes — the user has to say yes).
_HEADER = """\
# Directory Context onboarding (v0.6.2)

The user has just opened a Bearings session in a directory that has
NOT yet been onboarded. No `.bearings/manifest.toml` exists. The
Bearings server has run the seven-step onboarding ritual against the
working directory and produced the brief below.

**Your first response in this session must:**

1. Greet the user briefly (one short sentence) and explain you are
   presenting a directory-context brief because this is a fresh
   project for Bearings.
2. Quote the brief below to the user **verbatim** in a fenced block.
   Do not paraphrase — the brief is short and precise on purpose.
3. Ask the user: *"Save this context to `.bearings/` so future
   sessions see it on every turn?"*
4. If they answer yes / save / persist / confirm / "go ahead" /
   any clear affirmative, call the `mcp__bearings__dir_init` tool
   with no arguments. The tool writes `.bearings/manifest.toml`,
   `.bearings/state.toml`, and an empty `.bearings/pending.toml`
   for the session's working directory.
5. If they decline or change the subject, drop this onboarding
   thread and answer their actual question. Do NOT retry the prompt;
   the next session that opens this directory will get the same
   layer and can ask again.

**Important caveats for the brief:**

- The naming-inconsistency notes are *historical record*, not
  active rename work. If the brief says
  *"naming note: 'Twrminal' in CHANGELOG.md near 'Bearings'"*,
  that means the project was renamed in the past and the changelog
  preserves the older name. It is NOT a half-finished rename.
  Present such notes as historical context, never as a problem.
- The `Pending operations` and `Recent sessions` sections will be
  empty on a fresh onboarding — they populate over time.
- Do not call `mcp__bearings__dir_init` until the user has clearly
  agreed. Silent writes to `.bearings/` violate the confirmation
  contract.

---

# Brief

"""


def _has_trigger_marker(directory: Path) -> bool:
    """True iff at least one `_TRIGGER_MARKERS` entry exists at the
    target path. Walked-up parents do NOT count — onboarding is
    per-working-dir, not per-repo, so a subdirectory of a git project
    that has its own pyproject would onboard separately and that's
    intentional (each `.bearings/` is independent per the spec)."""
    for marker in _TRIGGER_MARKERS:
        if (directory / marker).exists():
            return True
    return False


def is_onboarded(directory: Path | str) -> bool:
    """True iff `<directory>/.bearings/manifest.toml` exists. Sole
    gate distinguishing the onboarding-prompt path from the regular
    brief path."""
    return (bearings_path(Path(directory)) / MANIFEST_FILE).exists()


def should_offer_onboarding(directory: Path | str) -> bool:
    """True iff the directory is a plausible project AND has not yet
    been onboarded. False on missing dir, no project markers, or
    existing manifest. Pure FS check — safe to call per-turn."""
    target = Path(directory)
    if not target.exists() or not target.is_dir():
        return False
    if is_onboarded(target):
        return False
    return _has_trigger_marker(target)


def _truncate(text: str, limit: int) -> str:
    """Last-line-of-defense cap on the rendered layer. Each section in
    `render_brief` already self-caps; this guards against pathological
    cases (huge README/CHANGELOG heads via future expansion)."""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 32)] + "\n\n…[onboarding layer truncated]"


def build_onboarding_brief(directory: Path | str) -> Brief | None:
    """Run onboarding and return the `Brief`, or `None` if the
    directory does not qualify. Separated from `format_onboarding_layer`
    so the MCP `dir_init` tool can call it directly without re-rendering
    the layer text."""
    target = Path(directory).resolve()
    if not should_offer_onboarding(target):
        return None
    try:
        return run_onboarding(target)
    except (OSError, FileNotFoundError) as exc:
        log.warning(
            "directory_context: auto-onboarding scan failed for %s: %s",
            target,
            exc,
        )
        return None


def format_onboarding_layer(working_dir: Path | str) -> str | None:
    """Render the `directory_onboarding` system-prompt layer.

    Returns `None` on:
      - missing or non-directory `working_dir`
      - directory has no recognised project marker (avoid offering a
        brief for a random `~/Downloads`)
      - `.bearings/manifest.toml` already exists (regular brief path
        takes over)
      - any subprocess / IO error during the scan (graceful degrade —
        the layer is advisory, never critical-path)
    """
    brief = build_onboarding_brief(working_dir)
    if brief is None:
        return None
    rendered = render_brief(brief)
    body = _HEADER + rendered + "\n"
    return _truncate(body, _ONBOARDING_LAYER_BUDGET)


__all__ = [
    "build_onboarding_brief",
    "format_onboarding_layer",
    "is_onboarded",
    "should_offer_onboarding",
]
