# Preferences — observable behavior

The preferences subsystem stores per-instance settings in a single DB row and exposes them via a REST API. This document covers the full observable behavior including the profile/identity contract added in gap-cycle-03-011.

Sibling subsystems referenced here: [themes](themes.md), [chat](chat.md).

## Settings → Defaults

The **Defaults** section in Settings lets the user pre-fill the new-session form. Four fields are exposed:

| Field | Type | Effect |
|---|---|---|
| `theme` | string | Active UI theme ID; NOT NULL in DB |
| `default_model` | nullable string | Pre-fills the executor model selector in the new-session form |
| `default_permission_mode` | nullable string | Pre-fills the permission mode selector |
| `default_working_dir` | nullable string | Pre-fills the working directory input |

`PATCH /api/preferences` uses Pydantic `model_fields_set` semantics: only explicitly supplied keys are written to the DB. An empty JSON body `{}` is a no-op.

## Profile / Identity (gap-cycle-03-011)

The **Profile** section renders *above* Appearance in the Settings page. It exposes:

| Field | Type | Default |
|---|---|---|
| `display_name` | nullable string | `null` (not displayed when absent) |
| `avatar_url` | nullable string | `null` (fallback icon shown when absent) |

`avatar_url` in the `PreferencesOut` wire shape is always `/api/preferences/avatar` when an avatar is set, or `null` when not. The frontend appends `?v=<updated_at>` as a cache-buster.

### Profile section controls

- **Identity preview** — `UserIdentityBlock` showing the current avatar (or fallback icon) and display name.
- **Display name** field — freetext input, max 120 characters. Saved via `PATCH /api/preferences` with `display_name`.
- **Upload image** button — hidden `<input type="file">` accepting JPEG, PNG, GIF, WebP. Fires `POST /api/preferences/avatar`.
- **Remove** button — visible only when an avatar is set. Fires `DELETE /api/preferences/avatar`.
- **Sync from system** button — fires `POST /api/preferences/sync_from_system`.

### Avatar storage

Avatars are stored as a single file `<avatars_root>/current` where `avatars_root` defaults to `~/.local/share/bearings-v1/avatars/`. The file is overwritten on each upload or sync; there is no version history. The DB stores `avatar_path` (absolute path) and `avatar_mime_type` for correct serving.

### Avatar endpoints

| Method | Path | Body | Effect |
|---|---|---|---|
| `GET` | `/api/preferences/avatar` | — | Returns avatar bytes with stored MIME type. 404 when no avatar set. |
| `POST` | `/api/preferences/avatar` | multipart `file` | Stores avatar. 415 for unsupported MIME types. 413 for bodies > 2 MiB. |
| `DELETE` | `/api/preferences/avatar` | — | Removes file, clears DB fields. Idempotent. |

### Sync from system

`POST /api/preferences/sync_from_system` reads:

- `$USER` (falling back to `$LOGNAME`, then `$USERNAME`) → `display_name`
- `~/.face` (if the file exists and is ≤ 2 MiB) → copied verbatim as the new avatar; MIME type is detected from magic header bytes (JPEG `\xff\xd8`, PNG `\x89PNG`, GIF `GIF87a`/`GIF89a`, WebP `RIFF...WEBP`; unknown defaults to `image/jpeg`)

Both fields are written unconditionally — a subsequent sync always refreshes.

### UserIdentityBlock component

`UserIdentityBlock` is a reusable Svelte 5 component used in:

- Settings → Profile section (identity preview)
- Sidebar top area (when wired by the layout)
- Status bar identity slot (when wired by the layout)

Props: `displayName: string | null`, `avatarUrl: string | null`, `cacheBust?: string`, `size?: string` (CSS unit string, defaults to `"2.5rem"`).

When `avatarUrl` is `null` the component renders a circular fallback SVG (person silhouette). When `displayName` is `null` the name slot is hidden entirely.

## API contract summary

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/preferences` | Returns `PreferencesOut` including profile fields |
| `PATCH` | `/api/preferences` | Partial update; `display_name` patchable here |
| `GET` | `/api/preferences/avatar` | Serve avatar bytes |
| `POST` | `/api/preferences/avatar` | Upload avatar (multipart) |
| `DELETE` | `/api/preferences/avatar` | Remove avatar |
| `POST` | `/api/preferences/sync_from_system` | Populate from OS environment |
