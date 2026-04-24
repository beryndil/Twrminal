-- Migration 0028: artifacts table for outbound file display.
--
-- The mirror of migration 0027's user-side attachment chips. Where 0027
-- tracks files the user dropped INTO the prompt, this table tracks files
-- the agent wrote and wants to show back OUT in the conversation view —
-- images, PDFs, DOCX, plain-text exports. The server endpoint
-- `GET /api/artifacts/{id}` resolves a row here to a disk path and
-- streams the bytes with the right Content-Type and inline disposition,
-- so the existing markdown `<img>` allowlist and the (upcoming)
-- FilePreview component can render the artifact without any
-- filesystem-walking on the browser side.
--
-- Shape:
--   id          UUID hex — stable, sent to the browser as part of the
--               `/api/artifacts/{id}` URL. Not guessable so a stray link
--               can't be walked to enumerate other sessions' artifacts
--               (AuthN is still the primary gate; this is defence-in-
--               depth).
--   session_id  FK sessions(id). CASCADE delete so purging a session
--               also purges the artifact rows that referenced it. The
--               on-disk file is not deleted here — artifact GC lives in
--               a follow-up sweep (see TODO.md next to the upload-GC
--               entry; both share the same sweep job).
--   path        Absolute filesystem path. Validated on INSERT by the
--               register endpoint against `settings.artifacts.serve_roots`;
--               re-validated on GET so a config narrowing between
--               register and serve revokes access cleanly.
--   filename    Display name for the UI (markdown alt text, download
--               filename). Not the on-disk basename — the agent may
--               register a file it wrote under a UUID name.
--   mime_type   Cached MIME for the Content-Type header. Detected by
--               the register endpoint (mimetypes.guess_type + extension
--               allowlist for a handful of overrides) and stored so the
--               serve path is a dict lookup, not a detection call.
--   size_bytes  `stat().st_size` at register time. Surfaced in list
--               endpoints for the UI's "17 KB" chip rendering.
--   sha256      Full-file hash at register time. Two register calls
--               for the same bytes collapse to the same digest, which
--               the attachment-chip UI can use to dedupe previews.
--               Populated once on INSERT; never recomputed on serve.
--   created_at  ISO timestamp. Drives the per-session list ordering
--               and feeds the future retention sweep.
--
-- Idempotent — `CREATE TABLE IF NOT EXISTS` so the migration replays
-- clean on partial-apply recovery.
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Per-session newest-first listing is the hot path for the UI's
-- artifact tray; a composite index serves it without a sort step.
CREATE INDEX IF NOT EXISTS idx_artifacts_session
    ON artifacts(session_id, created_at);
