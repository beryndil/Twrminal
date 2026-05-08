"""bearings_dir — ``.bearings/`` directory-context contract (arch §1.1.6).

The five modules in this package own everything that touches the on-disk
``.bearings/`` subdirectory that Bearings creates (or reads) inside a
project directory when the user accepts the onboarding prompt.

Module surface
--------------
``contract``
    Pydantic models for ``manifest.toml``, ``state.toml``, and
    ``pending.toml``, plus schema-version constants and validation helpers.

``io``
    Atomic TOML read/write (``tempfile.NamedTemporaryFile`` + ``os.replace``)
    and JSONL append-with-cap helpers.

``lifecycle``
    :func:`~bearings.bearings_dir.lifecycle.note_directory_context_start`
    and :func:`~bearings.bearings_dir.lifecycle.read_brief` — the two
    surfaces ``agent/prompt.py`` calls per arch §1.1.6 «Out» column.

``onboarding``
    The 7-step onboarding ritual, brief composition, and the
    :func:`~bearings.bearings_dir.onboarding.dir_init_body` that backs
    the ``mcp__bearings__dir_init`` tool (wired in ``agent/bearings_mcp.py``
    per finding-003).

``pending``
    Pending-ops backing logic for ``web/routes/pending.py``.

Layer isolation
---------------
Per ``docs/architecture-v1.md`` §3 (line 549):

    ``bearings.bearings_dir.*`` may not import ``bearings.agent.*`` or
    ``bearings.web.*`` or ``bearings.cli.*``.

The MCP tool body lives here (``onboarding.dir_init_body``); the agent
layer dispatches to it rather than the reverse.
"""

from __future__ import annotations

__all__: list[str] = []
