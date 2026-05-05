"""Backfill ``sessions.total_cost_usd`` from per-message token counts.

Context: commits ``44766cb`` (camelCase fix on SDK ``model_usage`` keys)
and ``46f5cad`` (session-row rollup wiring) restored cost-tracking.
Sessions that ran *between* the v1 cutover and ``46f5cad`` have zero in
the rollup column even when their per-message token columns are
populated. This script estimates each affected session's cost from
``executor_input_tokens x rate + executor_output_tokens x rate +
cache_read_tokens x rate`` (per-message ``executor_model``) and writes
the rollup back.

Out-of-scope sessions:

* v0.17.x imports — these already carry the correct ``total_cost_usd``
  forwarded by ``db/import_bearings.py``. The query filters them by
  requiring at least one assistant row with a non-NULL
  ``executor_model`` (v0.17.x imports leave that column NULL).
* Pre-``44766cb`` v1-native sessions — every assistant row has tokens=0
  because the snake_case bug silently dropped the SDK payload. Their
  cost is genuinely unrecoverable; the script computes ``0`` for these
  and the no-op SQL leaves the row untouched.

Idempotent: re-running computes the same total from the same token
data. The UPDATE only fires when the computed cost differs from the
current value, so a second invocation is a no-op.

Usage:
    python scripts/backfill_total_cost_usd.py [--db PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

# Anthropic per-token rates as of 2026-01 (USD per 1M tokens). Captured
# from https://docs.anthropic.com/en/docs/about-claude/pricing for the
# standard 200K-context tiers — 1M-context Opus tiers carry a higher
# cache-write rate which this table does NOT model. The undercount on
# 1M-context turns is acceptable for a one-shot historical backfill;
# going-forward cost is read from ``ResultMessage.total_cost_usd`` per
# commit ``46f5cad`` and bypasses this table entirely.
_RATES_PER_MTOK_USD: Mapping[str, _Rate]


class _Rate(NamedTuple):
    """Per-million-token USD rates for one model tier."""

    input_usd: float
    output_usd: float
    cache_read_usd: float


_RATES_PER_MTOK_USD = {
    "sonnet": _Rate(input_usd=3.0, output_usd=15.0, cache_read_usd=0.30),
    "opus": _Rate(input_usd=15.0, output_usd=75.0, cache_read_usd=1.50),
    "haiku": _Rate(input_usd=1.0, output_usd=5.0, cache_read_usd=0.10),
}


def _rate_for_model(model: str | None) -> _Rate | None:
    """Resolve the rate row for an ``executor_model`` cell.

    Accepts short names (``sonnet`` / ``opus`` / ``haiku``) and full
    SDK ids (``claude-sonnet-4-6``, ``claude-opus-4-7[1m]``, …) via a
    case-folded substring test. Returns ``None`` for an unknown model
    so the caller can skip the row rather than guessing.
    """
    if model is None:
        return None
    folded = model.casefold()
    for short, rate in _RATES_PER_MTOK_USD.items():
        if short in folded:
            return rate
    return None


def _compute_cost(
    executor_in: int,
    executor_out: int,
    cache_read: int,
    advisor_in: int,
    advisor_out: int,
    executor_rate: _Rate,
    advisor_rate: _Rate | None,
) -> float:
    """Sum the six per-message token columns x per-rate.

    Cache-read rate is taken from the executor (the executor owns the
    main system-prompt cache; advisor calls are short and rarely hit
    cached blocks of meaningful size).
    """
    cost = (
        executor_in * executor_rate.input_usd
        + executor_out * executor_rate.output_usd
        + cache_read * executor_rate.cache_read_usd
    ) / 1_000_000.0
    if advisor_rate is not None:
        cost += (
            advisor_in * advisor_rate.input_usd + advisor_out * advisor_rate.output_usd
        ) / 1_000_000.0
    return cost


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path.home() / ".local/share/bearings-v1/sessions.db",
        help="Path to the Bearings v1 SQLite database.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned UPDATEs without writing.",
    )
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"database not found: {args.db}")

    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row
    try:
        # Candidates: v1-native sessions (executor_model on at least one
        # assistant row, which v0.17.x imports leave NULL) currently
        # showing zero in the rollup.
        candidates = conn.execute(
            """
            SELECT DISTINCT s.id
            FROM sessions s
            JOIN messages m ON m.session_id = s.id
            WHERE s.total_cost_usd = 0
              AND m.role = 'assistant'
              AND m.executor_model IS NOT NULL
              AND (
                m.executor_input_tokens > 0
                OR m.executor_output_tokens > 0
                OR m.cache_read_tokens > 0
              )
            """
        ).fetchall()
        print(f"candidate sessions: {len(candidates)}")

        updated = 0
        skipped_unknown_model = 0
        total_backfilled_usd = 0.0

        for row in candidates:
            session_id = row["id"]
            messages = conn.execute(
                """
                SELECT executor_model, advisor_model,
                       executor_input_tokens, executor_output_tokens,
                       advisor_input_tokens, advisor_output_tokens,
                       cache_read_tokens
                FROM messages
                WHERE session_id = ? AND role = 'assistant'
                """,
                (session_id,),
            ).fetchall()

            session_cost = 0.0
            had_unknown = False
            for m in messages:
                executor_rate = _rate_for_model(m["executor_model"])
                if executor_rate is None:
                    had_unknown = True
                    continue
                session_cost += _compute_cost(
                    executor_in=int(m["executor_input_tokens"] or 0),
                    executor_out=int(m["executor_output_tokens"] or 0),
                    cache_read=int(m["cache_read_tokens"] or 0),
                    advisor_in=int(m["advisor_input_tokens"] or 0),
                    advisor_out=int(m["advisor_output_tokens"] or 0),
                    executor_rate=executor_rate,
                    advisor_rate=_rate_for_model(m["advisor_model"]),
                )

            if had_unknown:
                skipped_unknown_model += 1

            if session_cost <= 0:
                continue

            if args.dry_run:
                print(f"  {session_id}: would set total_cost_usd = ${session_cost:.6f}")
            else:
                conn.execute(
                    "UPDATE sessions SET total_cost_usd = ? WHERE id = ?",
                    (session_cost, session_id),
                )
                print(f"  {session_id}: total_cost_usd = ${session_cost:.6f}")
            updated += 1
            total_backfilled_usd += session_cost

        if not args.dry_run:
            conn.commit()

        print(
            f"\nupdated {updated} session(s); "
            f"sum of backfilled cost = ${total_backfilled_usd:.6f}"
            f"{' (DRY RUN)' if args.dry_run else ''}"
        )
        if skipped_unknown_model:
            print(
                f"note: {skipped_unknown_model} session(s) had ≥1 assistant row "
                f"with an unrecognised ``executor_model`` (rate table miss); "
                f"those messages contributed 0 to the rollup."
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
