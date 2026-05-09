"""Bearings CLI root — argparse parser + dispatch.

Per ``docs/behavior/bearings-cli.md`` §"Top-level shape":

* ``bearings [--version] <subcommand> [...]``
* ``--version`` prints ``bearings <version>`` to stdout and exits 0.
* No subcommand → usage block on stderr, exit 2 (argparse default).
* Unknown subcommand → argparse error on stderr, exit 2.
* ``bearings <subcommand> --help`` → that subcommand's help on
  stdout, exit 0.

Item 1.7 wires the ``todo`` subcommand (the master-item call-out)
plus an ``--info`` placeholder that surfaces the bootstrap notice the
v0.18.0.dev0 install ships with — this preserves the test contract
:mod:`tests.test_bootstrap` set in item 0.1 ("``bearings`` exits 0
and prints a one-line bootstrap notice") without rolling back the
done-when of either item.

Stubs for ``window`` / ``send`` / ``here`` / ``pending`` are deferred
per arch §1.1.1 + behavior doc; each subsequent item adds its module
under ``cli/`` and registers its subparser through
:func:`build_subparser`.  ``gc``, ``init``, and ``migrate`` are now
wired.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from bearings import __version__
from bearings.cli import gc as gc_cli
from bearings.cli import init as init_cli
from bearings.cli import migrate as migrate_cli
from bearings.cli import serve as serve_cli
from bearings.cli import todo as todo_cli
from bearings.config.constants import (
    CLI_EXIT_OK,
    CLI_EXIT_OPERATION_FAILURE,
    CLI_EXIT_USAGE_ERROR,
)

# Bootstrap notice surfaced by ``bearings`` with no subcommand under
# the legacy item-0.1 contract (preserved verbatim so
# ``tests/test_bootstrap.py`` keeps passing while the full CLI grows
# its real subcommand surface). When a real subcommand is supplied the
# notice is not printed; the subcommand handles its own output.
_BOOTSTRAP_MESSAGE: str = (
    "bearings v{version} (v1 rebuild — todo + serve + gc + init + migrate subcommands wired; "
    "window / send / here / pending land in subsequent items)\n"
)


def build_parser() -> argparse.ArgumentParser:
    """Construct the root :class:`argparse.ArgumentParser`.

    Subparsers are required only when a subcommand is invoked; the
    bare ``bearings`` invocation falls through to the bootstrap
    notice path so the item-0.1 test contract survives.
    """
    parser = argparse.ArgumentParser(
        prog="bearings",
        description=(
            "Localhost web UI that streams Claude Code agent sessions. "
            "See `docs/behavior/bearings-cli.md` for the full subcommand surface."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"bearings {__version__}",
        help="print 'bearings <version>' and exit 0",
    )
    sub = parser.add_subparsers(
        dest="subcommand",
        metavar="<subcommand>",
    )
    todo_cli.build_subparser(sub)
    serve_cli.build_subparser(sub)
    gc_cli.build_subparser(sub)
    init_cli.build_subparser(sub)
    migrate_cli.build_subparser(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and dispatch to the relevant subcommand.

    Returns the CLI exit code per behavior doc:

    * 0 — success.
    * 1 — operation-level failure (paired with stderr message).
    * 2 — usage / validation error (paired with argparse-style
      stderr message).
    """
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        # argparse's exit codes: 0 for ``--help`` / ``--version``;
        # 2 for parse errors. Mirror them exactly so the behavior-
        # doc-mandated "exit 2 on usage error" lands without
        # additional wrapping.
        return _coerce_exit_code(exc.code)
    if args.subcommand is None:
        # Bare ``bearings`` — print the bootstrap notice and exit 0
        # (preserves the item-0.1 test contract).
        sys.stdout.write(_BOOTSTRAP_MESSAGE.format(version=__version__))
        return CLI_EXIT_OK
    func = getattr(args, "func", None)
    if func is None:  # pragma: no cover — every leaf parser sets ``func``
        sys.stderr.write(f"bearings: subcommand {args.subcommand!r} not implemented\n")
        return CLI_EXIT_USAGE_ERROR
    rc = func(args)
    if isinstance(rc, int):
        return rc
    return CLI_EXIT_OK


def _coerce_exit_code(code: int | str | None) -> int:
    """Normalise an :class:`SystemExit.code` to the CLI alphabet.

    argparse may pass an int (parse-success: 0; parse-failure: 2) or
    occasionally a string for a custom ``parser.exit("msg")``; the
    CLI alphabet only honours 0 / 1 / 2 so any other value collapses
    to :data:`CLI_EXIT_OPERATION_FAILURE`.
    """
    if code is None:
        return CLI_EXIT_OK
    if isinstance(code, int):
        if code == CLI_EXIT_OK:
            return CLI_EXIT_OK
        if code == CLI_EXIT_USAGE_ERROR:
            return CLI_EXIT_USAGE_ERROR
        return CLI_EXIT_OPERATION_FAILURE
    return CLI_EXIT_OPERATION_FAILURE


if __name__ == "__main__":  # pragma: no cover — exercised via console_script
    raise SystemExit(main(sys.argv[1:]))


__all__ = ["build_parser", "main"]
