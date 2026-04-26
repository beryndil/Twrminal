#!/usr/bin/env bash
# Bearings on_open.sh — dogfood for v0.6.3 polish.
#
# Spawned once at session start by lifecycle.maybe_run_on_open. Output
# is captured (1024-byte cap per stream), stamped into
# .bearings/last_on_open.json, and surfaced in the per-turn brief.
#
# Keep this fast. The whole runner has a 10s timeout; anything that
# can take longer belongs in CI, not here. The check should answer
# "is this workspace healthy enough to start work in?" in one breath.
set -uo pipefail

# Cheap workspace checks. Each one is short, exits non-zero on a real
# problem. The runner aggregates exit codes; bash exits with the last
# command's code unless we OR them together. We want the FIRST failure
# to be visible in the snippet, so guard each check and emit a
# one-line summary.
fail=0

# 1. Are we in a git repo at all? Onboarding assumes so for Bearings.
if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "not a git repo (unexpected for the Bearings checkout)" 1>&2
    fail=1
fi

# 2. Is the lockfile honoring its constraints? `uv sync --locked
#    --dry-run` is the canonical "is uv.lock current" check. Skip
#    silently when uv isn't on PATH so a Python-less host doesn't
#    falsely flag the workspace.
if command -v uv >/dev/null 2>&1; then
    if ! uv sync --locked --dry-run >/dev/null 2>&1; then
        echo "uv.lock drift — run 'uv sync' to refresh" 1>&2
        fail=1
    fi
fi

# 3. Surface any tracked but unmerged conflict markers so a session
#    that opens mid-merge doesn't waste turns guessing.
if git ls-files -u 2>/dev/null | grep -q .; then
    echo "unmerged paths present — `git status` to see the merge" 1>&2
    fail=1
fi

if [ "$fail" -eq 0 ]; then
    echo "workspace healthy"
fi
exit "$fail"
