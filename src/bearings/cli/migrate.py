"""``bearings migrate`` subcommand — apply pending DB schema migrations.

Per ``docs/architecture-v1.md`` §1.1.1 the handler stays thin: argument
parsing, a single call into the domain helper
(:func:`~bearings.db.migrate.run_migrations`), and output formatting.
No business logic lives here.

Per ``docs/behavior/bearings-cli.md`` §"bearings migrate" the subcommand is
idempotent: running it against an up-to-date schema exits 0 with a notice
that no migrations were needed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bearings.config.constants import CLI_EXIT_OK, CLI_EXIT_OPERATION_FAILURE, DEFAULT_DB_PATH
from bearings.db.migrate import run_migrations


def build_subparser(
    parent: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Wire the ``migrate`` subcommand into ``parent``.

    ``parent`` is the root ``bearings`` subparsers action; this function
    adds ``migrate`` and its optional ``--db`` path override.
    """
    p = parent.add_parser(
        "migrate",
        help="apply pending DB schema migrations",
        description=(
            "Apply any pending column migrations to the Bearings SQLite DB. "
            "Safe to run repeatedly — all migrations use PRAGMA table_info "
            "to skip columns that already exist, so the operation is idempotent. "
            "Run `bearings init` first if the DB does not yet exist."
        ),
    )
    p.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        metavar="PATH",
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )
    p.set_defaults(func=_cmd_migrate)


def _cmd_migrate(args: argparse.Namespace) -> int:
    """Handler for ``bearings migrate``.

    Delegates all I/O to :func:`~bearings.db.migrate.run_migrations`.
    Emits a one-line status message on stdout and returns the CLI exit code.
    """
    try:
        added = run_migrations(db_path=args.db)
    except FileNotFoundError:
        sys.stderr.write(
            f"bearings migrate: DB not found at {args.db} — run `bearings init` first.\n"
        )
        return CLI_EXIT_OPERATION_FAILURE
    except OSError as exc:
        sys.stderr.write(f"bearings migrate: migration failed: {exc}\n")
        return CLI_EXIT_OPERATION_FAILURE
    if added:
        sys.stdout.write(
            f"bearings migrate: applied {added} column migration(s). DB is now up to date.\n"
        )
    else:
        sys.stdout.write("bearings migrate: DB schema is up to date (no migrations needed).\n")
    return CLI_EXIT_OK


__all__ = ["build_subparser"]
