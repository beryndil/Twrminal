"""Agent-authored artifact DTOs (outbound file display).

Pair with the inbound `UploadOut` in `fs.py`. The agent registers a
file it has already written via `POST /api/sessions/{sid}/artifacts`
with an `ArtifactRegister` body; the server validates the path lives
under `settings.artifacts.serve_roots`, stats it, computes a hash, and
returns an `ArtifactOut` carrying a stable `/api/artifacts/{id}` URL
the agent embeds in its reply as a markdown image or download link.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ArtifactRegister(BaseModel):
    """Body for `POST /api/sessions/{session_id}/artifacts`.

    `path` is an absolute filesystem path the agent has already
    written. The register endpoint validates it lives under an
    allowlisted root (`settings.artifacts.serve_roots`) — a path
    outside that list yields 400, not 500, so Claude sees a clear
    error when it tries to register something it wasn't supposed to.

    `filename` is an optional display name; when omitted the server
    falls back to the path's basename. `mime_type` is optional — the
    server detects from the extension + magic bytes and stores the
    result. A caller-supplied value wins only when the detector is
    ambiguous (extension unknown / no match).
    """

    path: str = Field(..., min_length=1)
    filename: str | None = None
    mime_type: str | None = None


class ArtifactOut(BaseModel):
    """Response shape for artifact create / get / list.

    `url` is pre-rendered server-side so the frontend can drop it into
    an `<img src>` or `<a href>` without reassembling the route. It
    points at `GET /api/artifacts/{id}` — same auth rules as the rest
    of `/api/*` — and the response carries
    `Content-Disposition: inline` so the browser renders rather than
    downloads by default. Pass `?download=1` to flip to attachment
    disposition when a real download is wanted.
    """

    id: str
    session_id: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    created_at: str
    url: str
