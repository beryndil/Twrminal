"""On-disk content-addressed storage for the uploads endpoint.

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/uploads.py``
delegates the on-disk body work to this module so the route handler
stays under the §40-line cap. The DB-side metadata mirror lives in
:mod:`bearings.db.uploads`; the two surfaces compose at the route
layer per arch §3 layer rules.

Storage layout:

* ``<storage_root>/<sha256[:N]>/<sha256>``
  where ``N`` = :data:`bearings.config.constants.UPLOADS_SHA256_SHARD_CHARS`
  (currently 2). Two-character shard keeps any one directory below
  ~256 entries after a full hash sweep — well-behaved on every
  filesystem the rebuild targets, and the layout matches the git
  object-store convention so a power user reading the on-disk shape
  recognises it immediately.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path

from bearings.config.constants import (
    UPLOAD_STREAM_CHUNK_BYTES,
    UPLOADS_SHA256_SHARD_CHARS,
)


def compute_sha256(body: bytes) -> str:
    """Return the hex sha256 digest of ``body``.

    Used at upload time to derive the content-address; the resulting
    digest is the natural primary key for the on-disk body and the
    UNIQUE column in the ``uploads`` DB table.
    """
    return hashlib.sha256(body).hexdigest()


def body_path(storage_root: Path, sha256: str) -> Path:
    """Resolve ``<storage_root>/<sha256[:N]>/<sha256>`` for a digest.

    Public helper for callers (e.g. the GC sweep in :mod:`bearings.cli.gc`)
    that need the canonical on-disk path without performing any I/O.
    The path is derived purely from the sha256 and the shard-prefix
    constant; no filesystem calls are made.
    """
    shard = sha256[:UPLOADS_SHA256_SHARD_CHARS]
    return storage_root / shard / sha256


# Module-private alias kept so the four read/write helpers below can
# remain call-site-stable without importing from themselves.
_body_path = body_path


def store_bytes(storage_root: Path, sha256: str, body: bytes) -> Path:
    """Write ``body`` to the canonical on-disk path; idempotent.

    If the file already exists (a re-upload of the same content), the
    write is skipped — the existing on-disk body is byte-for-byte
    identical by content-address invariant. The return value is the
    absolute path the body landed at.

    The shard subdirectory is created with ``parents=True,
    exist_ok=True`` so concurrent writers cannot race on the
    ``mkdir``.
    """
    target = _body_path(storage_root, sha256)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(body)
    return target


def read_bytes(storage_root: Path, sha256: str) -> bytes:
    """Read the on-disk body for ``sha256``.

    Raises :class:`FileNotFoundError` if the body is absent — the
    route layer maps that to 404 (the metadata row exists but the
    body went missing, which would be a corrupted state).
    """
    return _body_path(storage_root, sha256).read_bytes()


def stream_bytes(storage_root: Path, sha256: str) -> Iterator[bytes]:
    """Yield the on-disk body in
    :data:`bearings.config.constants.UPLOAD_STREAM_CHUNK_BYTES`-sized
    chunks for the :func:`fastapi.responses.StreamingResponse` shape.
    """
    path = _body_path(storage_root, sha256)
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(UPLOAD_STREAM_CHUNK_BYTES)
            if not chunk:
                return
            yield chunk


def delete_bytes(storage_root: Path, sha256: str) -> bool:
    """Remove the on-disk body if present; returns ``True`` if removed.

    Idempotent: a missing file (concurrent delete, or the metadata
    row outliving the body for whatever reason) returns ``False``
    rather than raising.
    """
    target = _body_path(storage_root, sha256)
    if not target.exists():
        return False
    target.unlink()
    # Best-effort shard-directory cleanup. ``rmdir`` only succeeds on
    # an empty directory, so a still-populated shard from another
    # upload remains untouched. ``suppress`` because a benign race
    # (concurrent shard delete) is fine here.
    with suppress(OSError):
        target.parent.rmdir()
    return True


__all__ = [
    "body_path",
    "compute_sha256",
    "delete_bytes",
    "read_bytes",
    "store_bytes",
    "stream_bytes",
]
