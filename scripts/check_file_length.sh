#!/usr/bin/env bash
# Enforce coding-standards.md Q1b: files must not exceed 400 lines.
#
# Used by .pre-commit-config.yaml — pre-commit passes filenames as
# positional arguments; we walk them and fail if any exceeds the cap.

set -euo pipefail

readonly MAX_LINES=400
fail=0

for f in "$@"; do
    n=$(wc -l < "$f")
    if [ "$n" -gt "$MAX_LINES" ]; then
        printf '%s: %s lines (cap is %s)\n' "$f" "$n" "$MAX_LINES"
        fail=1
    fi
done

exit "$fail"
