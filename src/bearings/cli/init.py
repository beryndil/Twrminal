"""``bearings init`` subcommand — initialise the data directory.

Per ``docs/architecture-v1.md`` §1.1.1 the handler stays thin: argument
parsing, a single call into the domain helper
(:func:`~bearings.bearings_dir.init.ensure_data_dir`), and output
formatting.  No business logic lives here.

Per ``docs/behavior/bearings-cli.md`` §"bearings init" the subcommand is
idempotent: running it on an already-initialised installation is a no-op
that exits 0 with a human-readable notice.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bearings.bearings_dir.init import ensure_data_dir
from bearings.config.constants import (
    CLI_EXIT_OK,
    CLI_EXIT_OPERATION_FAILURE,
    DEFAULT_AVATARS_STORAGE_ROOT,
    DEFAULT_DB_PATH,
    DEFAULT_UPLOADS_STORAGE_ROOT,
)


def build_subparser(
    parent: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Wire the ``init`` subcommand into ``parent``.

    ``parent`` is the root ``bearings`` subparsers action; this function
    adds ``init`` and its three optional path overrides.
    """
    p = parent.add_parser(
        "init",
        help="initialise the ~/.local/share/bearings-v1/ data directory",
        description=(
            "Create the data-directory layout and initialise the SQLite DB. "
            "Safe to run on an existing installation — directories are created "
            "with exist_ok=True and the DB schema uses IF NOT EXISTS guards, "
            "so all operations are idempotent."
        ),
    )
    p.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        metavar="PATH",
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )
    p.add_argument(
        "--uploads-root",
        type=Path,
        default=DEFAULT_UPLOADS_STORAGE_ROOT,
        dest="uploads_root",
        metavar="PATH",
        help=f"upload storage root (default: {DEFAULT_UPLOADS_STORAGE_ROOT})",
    )
    p.add_argument(
        "--avatars-root",
        type=Path,
        default=DEFAULT_AVATARS_STORAGE_ROOT,
        dest="avatars_root",
        metavar="PATH",
        help=f"avatar storage root (default: {DEFAULT_AVATARS_STORAGE_ROOT})",
    )
    p.set_defaults(func=_cmd_init)


def _cmd_init(args: argparse.Namespace) -> int:
    """Handler for ``bearings init``.

    Delegates all I/O to :func:`~bearings.bearings_dir.init.ensure_data_dir`.
    Emits a one-line status message on stdout and returns the CLI exit code.
    """
    try:
        fresh = ensure_data_dir(
            db_path=args.db,
            uploads_root=args.uploads_root,
            avatars_root=args.avatars_root,
        )
    except OSError as exc:
        sys.stderr.write(f"bearings init: failed to initialise data directory: {exc}\n")
        return CLI_EXIT_OPERATION_FAILURE
    if fresh:
        sys.stdout.write(f"bearings init: data directory initialised at {args.db.parent}\n")
    else:
        sys.stdout.write(
            f"bearings init: data directory already present at {args.db.parent} (no-op)\n"
        )
    return CLI_EXIT_OK


__all__ = ["build_subparser"]
