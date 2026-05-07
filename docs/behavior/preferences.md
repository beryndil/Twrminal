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

## Notifications (gap-cycle-07-001)

The **Notifications** section renders below Defaults in the Settings page. It exposes a single toggle:

| Field | Type | Default | Effect |
|---|---|---|---|
| `notify_on_complete` | boolean | `false` | When `true`, fires a desktop notification after each completed assistant turn while the tab is hidden or unfocused |

### Toggle behavior

- **Flipping ON**: the browser permission prompt fires **before** the PATCH. If the user denies, the toggle visibly rolls back and an inline error renders. The PATCH only fires on `"granted"`.
- **Flipping OFF**: persists immediately; no permission prompt.
- **Disabled with footnote** when `window.Notification` is undefined (footnote: *"Your browser does not support desktop notifications."*) or `Notification.permission === "denied"` (footnote: *"Blocked in browser settings — re-allow notifications for this site, then re-toggle."*).

### Notification fire condition

The frontend fires `new Notification("Bearings", { body: "Claude finished replying." })` once per assistant turn when all hold:

1. `notify_on_complete` is `true` in the module-level state (set by the Settings page on load and PATCH).
2. `Notification.permission === "granted"`.
3. `document.visibilityState === "hidden"` OR `!document.hasFocus()`.

The check fires in `agent.svelte.ts` after every `message_complete` WS event.

## Authentication (gap-cycle-07-002)

The **Authentication** section renders below Notifications in the Settings page. It exposes a single password-type input field for the per-device auth token.

| Property | Value |
|---|---|
| Input type | `password` |
| Font | monospace |
| Storage | `localStorage` under `bearings-v1:auth-token` |
| Backend contact | **None** — the token never PATCHes `/api/preferences` |

### Token field behavior

- **Pre-populated** from `localStorage` on mount via `getStoredToken()`.
- **Autosaves on every keystroke** (`oninput`): no explicit Save button.
  - Non-empty value → `saveToken(value)` — writes trimmed value to `localStorage` and clears `authStore.blocking`.
  - Empty value → `clearToken()` — removes the key from `localStorage` without touching `blocking`.
- **Gate-bypass**: when `authStore.blocking` is `true` (gate is showing) and the user types a non-empty token, `saveToken` clears `blocking` immediately — the AuthGate dismisses without a page reload.
- **Clear path**: clearing the field removes the stored token. The gate will reappear on the next 4401 WebSocket close.
- **Section lede** explains: "Your auth token is stored on this device only — it is never sent to the Bearings server as a preference."

## Privacy (gap-cycle-07-003)

The **Privacy** section renders below Authentication in the Settings page. It has two rows and no form submission.

### Row 1 — Telemetry promise

Displays the headline **"Your data stays on this device"** with an external link labelled "No telemetry — audit the promise" pointing to `https://github.com/Beryndil/Bearings/blob/main/TELEMETRY.md` (`target="_blank"`, `rel="noopener noreferrer"`).

### Row 2 — Data directory

On mount, calls `GET /api/health` and displays the resolved `data_dir` field (typically `~/.local/share/bearings-v1/`) in a monospace code element.

An **"Open data dir"** button appears alongside the path:

| Outcome | Behaviour |
|---|---|
| `POST /api/shell/exec` returns 2xx | Button briefly shows **"Opened"** (resets after 2 s) |
| Non-2xx (shell command not allowed / unavailable) | Falls back to `navigator.clipboard.writeText(dataDir)`; button shows **"Path copied"**; a footnote appears: *"To open in a file manager, add xdg-open to shell.allowed_commands in ~/.config/bearings/config.toml"* |
| Both shell open AND clipboard fail | Inline error renders with the error message |

While `GET /api/health` is in flight, a loading label renders. On error, an inline error renders instead of the path and button.

## API contract summary

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/preferences` | Returns `PreferencesOut` including profile fields and `notify_on_complete` |
| `PATCH` | `/api/preferences` | Partial update; `display_name` and `notify_on_complete` patchable here |
| `GET` | `/api/preferences/avatar` | Serve avatar bytes |
| `POST` | `/api/preferences/avatar` | Upload avatar (multipart) |
| `DELETE` | `/api/preferences/avatar` | Remove avatar |
| `POST` | `/api/preferences/sync_from_system` | Populate from OS environment |
