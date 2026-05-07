# Preferences — observable behavior

## Settings shell layout (gap-cycle-07-007)

The ``/settings`` route renders a ``SettingsShell`` two-column layout:

- **Left nav rail** — ``role="tablist"`` ``aria-orientation="vertical"``, one ``<button role="tab">`` per registered section in weight order. The active button has ``aria-selected="true"`` and ``tabindex="0"``; inactive buttons have ``tabindex="-1"`` (roving tabindex). Keyboard navigation: ↑/↓ moves the active section one step (wraps), Home/End jump to first/last.
- **Right content pane** — one ``role="tabpanel"`` per section, rendered in the DOM at all times with CSS ``display:none`` for inactive panels (keeps test selectors valid for per-section test suites).
- **URL deep-link** — the active section id is mirrored into ``?settings=<id>`` via ``history.replaceState`` on every section switch. On mount the shell reads ``window.location.search`` to honour deep-links; unrecognised ids fall back to the first registered section.
- **Save-status footer** — a sticky footer at the bottom of the content pane shows the aggregated save status of the active section: "Saving…" while a PATCH is in flight, "All changes saved" on success, "Failed to save: {message}" on error. The footer is absent when the section is idle. It resets to idle when the user switches sections.

### Section registry

``frontend/src/lib/components/settings/sections.ts`` is the single source of truth:

| id | label | weight | Section |
|---|---|---|---|
| ``profile`` | Profile | 10 | ProfileSection.svelte |
| ``appearance`` | Appearance | 20 | AppearanceSection.svelte |
| ``defaults`` | Defaults | 30 | DefaultsSection.svelte |
| ``notifications`` | Notifications | 40 | NotificationsSection.svelte |
| ``authentication`` | Authentication | 50 | AuthSection.svelte |
| ``privacy`` | Privacy | 60 | PrivacySection.svelte |
| ``routing`` | System routing | 70 | RoutingRulesSection.svelte |
| ``import`` | Data import | 80 | ImportSection.svelte |
| ``help`` | Help | 90 | HelpSection.svelte |
| ``about`` | About | 100 | AboutSection.svelte |

Adding a new section requires one registry append in ``sections.ts``; no changes to ``+page.svelte`` or ``SettingsShell.svelte``.



The preferences subsystem stores per-instance settings in a single DB row and exposes them via a REST API. This document covers the full observable behavior including the profile/identity contract added in gap-cycle-03-011.

Sibling subsystems referenced here: [themes](themes.md), [chat](chat.md).

## Settings → Defaults (gap-cycle-17-002)

The **Defaults** section in Settings lets the user pre-fill the new-session form. Four fields are exposed:

| Field | Type | Control | Save trigger |
|---|---|---|---|
| `theme` | string | `<select>` | Immediate on change |
| `default_model` | nullable string | `<select>` | Immediate on change |
| `default_permission_mode` | nullable string | `<select>` | Immediate on change |
| `default_working_dir` | nullable string | `<input type="text">` | Debounced ~400 ms (`DEFAULTS_AUTOSAVE_DEBOUNCE_MS`) |

There is **no Save button**. Each field autosaves independently — selecting an option or pausing after typing fires its own `PATCH /api/preferences` containing only that field (`model_fields_set` semantics; an empty body `{}` is a no-op).

### Per-row save badges

Every field row carries a save badge rendered to the right of its control, matching the v17 `SettingsRow` pattern:

| State | Text | Role | CSS modifier |
|---|---|---|---|
| Saving | "Saving…" | `status` | `--saving` (muted fg) |
| Saved | "Saved" | `status` | `--saved` (accent fg) |
| Error | "Failed to save: {message}" | `alert` | `--error` (error fg) |

The badge auto-fades back to idle ~2 s after a successful save. The `onsaveStatus` callback fires on every save event so the `SettingsShell` footer aggregates the active section's last save state.

### Theme field cross-sync

The theme `<select>` in Defaults reads from `themeStore.theme` (the same reactive store used by the `ThemePicker` in Appearance). Changing the theme in either location calls `setTheme()`, which updates `themeStore.theme`, applies the new palette to the DOM, and persists to `localStorage` (`bearings-theme-v1`) — the other control reflects the change without a page reload. The autosave path additionally PATCHes `/api/preferences` so the theme is persisted to the DB as well.

## Profile / Identity (gap-cycle-03-011)

The **Profile** section renders *above* Appearance in the Settings page. It exposes:

| Field | Type | Default |
|---|---|---|
| `display_name` | nullable string | `null` (not displayed when absent) |
| `avatar_url` | nullable string | `null` (fallback icon shown when absent) |

`avatar_url` in the `PreferencesOut` wire shape is always `/api/preferences/avatar` when an avatar is set, or `null` when not. The frontend appends `?v=<updated_at>` as a cache-buster.

### Profile section controls

- **Identity preview** — `UserIdentityBlock` showing the current avatar (or fallback icon) and display name.
- **Display name** field — freetext input, max 120 characters. **Autosaves on change** with a ~400 ms debounce (`PROFILE_AUTOSAVE_DEBOUNCE_MS`). Typing then pausing fires `PATCH /api/preferences` with `display_name` without any explicit Save click. There is no Save button.
- **Upload image** button — hidden `<input type="file">` accepting JPEG, PNG, GIF, WebP. Fires `POST /api/preferences/avatar`.
- **Remove** button — visible only when an avatar is set. Fires `DELETE /api/preferences/avatar`.
- **Sync from system** button — fires `POST /api/preferences/sync_from_system`.

#### Per-row save badges (gap-cycle-17-001)

Every mutating row in the Profile section carries a per-row save badge rendered to the right of its control:

| State | Text | Role | CSS modifier |
|---|---|---|---|
| Saving | "Saving…" | `status` | `--saving` (muted fg) |
| Saved | "Saved" | `status` | `--saved` (accent fg) |
| Error | "Failed to save: {message}" | `alert` | `--error` (error fg) |

The badge auto-fades back to idle ~2 s after a successful save. Rows with badges: display-name, avatar upload, avatar remove, sync-from-system.

The `onsaveStatus` callback continues to fire on every save event so the `SettingsShell` footer aggregates the active section's last save state ("Saving…" / "All changes saved" / "Failed to save: …").

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
- **Sidebar bottom** — pinned below the session list via `flex-shrink:0`, wrapped in a button that navigates to `/settings` on click (gap-cycle-08-002). Props are sourced from `preferencesStore` (refreshed on layout mount and after every Profile section mutation). Display name falls back to `"Operator"` when `null`.
- Status bar identity slot (when wired by the layout)

Props: `displayName: string | null`, `avatarUrl: string | null`, `cacheBust?: string`, `size?: string` (CSS unit string, defaults to `"2.5rem"`).

When `avatarUrl` is `null` the component renders a circular fallback SVG (person silhouette). When `displayName` is `null` the name slot is hidden entirely.

### Preferences store (`preferencesStore`)

`src/lib/stores/preferences.svelte.ts` is a singleton Svelte 5 `$state` store that caches the three identity fields needed by the sidebar: `displayName`, `avatarUrl`, `cacheBust`. It exposes:

- `preferencesStore` — reactive snapshot read by the layout and any other consumer.
- `refreshPreferences()` — async; calls `GET /api/preferences` and updates the store. Called on layout mount. Errors are caught silently; the sidebar degrades to the fallback name / silhouette.
- `applyPreferences(prefs: PreferencesOut)` — synchronous; updates the store from an already-fetched preferences row. Called by Profile section after every mutation so the sidebar updates without a second GET.

## Notifications (gap-cycle-07-001, addendum gap-cycle-17-003)

The **Notifications** section renders below Defaults in the Settings page. It exposes a single toggle:

| Field | Type | Default | Effect |
|---|---|---|---|
| `notify_on_complete` | boolean | `false` | When `true`, fires a desktop notification after each completed assistant turn while the tab is hidden or unfocused |

### Steady-state description (gap-cycle-17-003)

Directly below the toggle row, a description paragraph is always visible — before the user interacts, regardless of the supported / denied state:

> *"Fires a tray notification for each completed agent turn — only while this tab is hidden or unfocused."*

This text (`NOTIFICATION_STRINGS.toggleDescription`) explains the visibility-gating condition so users understand the toggle is conditioned on the tab being hidden or unfocused without needing to consult the documentation. The conditional footnotes for unsupported and denied states layer on top of this description — they do not replace it.

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

## Help (gap-cycle-07-004)

The **Help** section renders below Data import in the Settings page. It is read-only — no PATCH calls are made.

Five rows are rendered in order:

| Row | Type | Behaviour |
|---|---|---|
| Keyboard shortcuts | Button | Invokes the registered `help.toggle_cheat_sheet` handler via `getHandler()` — identical to pressing `?` globally. No-op when no handler is registered (provider not mounted). |
| README | External link | Opens `https://github.com/Beryndil/Bearings#readme` in a new tab (`target="_blank"`, `rel="noopener noreferrer"`). |
| Documentation | External link | Opens `https://github.com/Beryndil/Bearings/tree/main/docs` in a new tab (`target="_blank"`, `rel="noopener noreferrer"`). |
| Report a bug | Button | Fetches `/api/diag/server` (lazy, cached), builds a GitHub `issues/new` URL with `labels=bug` and a steps-to-reproduce scaffold, opens it in a new tab. Bearings POSTs nothing — the user submits the GitHub form manually (Beryndil standards §17). |
| Request a feature | Button | Same flow as "Report a bug" but `labels=feature` and a use-case / proposed-behavior scaffold. |

The two feedback buttons share a single `helpFeedbackOpening` flag that disables both while a tab is opening, preventing concurrent dispatches.

### Feedback URL shape

Both feedback rows use `buildFeedbackUrl(kind, version)` from `src/lib/utils/feedback.ts`. The `FeedbackKind` type (`"bug" | "feature"`) selects:

- **Bug**: scaffold sections `## Steps to reproduce`, `## Expected behavior`, `## Actual behavior`; `labels=bug`.
- **Feature**: scaffold sections `## Use case`, `## Proposed behavior`, `## Alternatives considered`; `labels=feature`.

Both kinds prefill: Bearings version, browser UA, platform, language.

The `FeedbackButton` in the conversation header continues to invoke `openFeedbackTab()` with the default `kind="bug"` — no behaviour change.

### Help row descriptions and trailing affordances (gap-cycle-17-004)

Each row renders three elements: a **title**, a one-line **description**, and a **trailing affordance** string. The entire row surface is the action target (full-width button or anchor). All strings are centralised in `HELP_SECTION_STRINGS` in `frontend/src/lib/config.ts` — no inline literals in the section component.

| Row | Description | Trailing | New tab? |
|---|---|---|---|
| Keyboard shortcuts | "Opens the cheat sheet — same overlay you can summon any time with the ? key." | `Show ?` | No |
| README | "Setup, build, and architecture overview on GitHub." | `README ↗` | Yes |
| Documentation | "In-repo reference for checklists, context menus, themes, and keybindings." | `docs/ ↗` | Yes |
| Report a bug | "Opens GitHub with environment and a steps-to-reproduce scaffold prefilled." | `New bug ↗` | Yes |
| Request a feature | "Opens GitHub with a problem / proposal scaffold prefilled." | `New request ↗` | Yes |

The ↗ glyph (`U+2197`) appears only on rows that open an external tab, giving a consistent affordance signal across all link-type rows. The keyboard-shortcuts row uses `Show ?` because it triggers an in-app overlay, not an external page.

## About (gap-cycle-07-005)

The **About** section renders at the bottom of the Settings page. It is read-only — no PATCH calls are made from this section.

### Hero block

A centered column containing:

| Element | Content |
|---|---|
| BearingsMark logo | 48 px icon |
| Product name | "Bearings" |
| Release version | `v{version}` from `GET /api/diag/server`; shows "v…" while loading, "version unavailable" on fetch failure |
| Tagline | "Localhost web UI for Claude Code agent sessions." |
| Byline link | "by Beryndil" → `https://hardknocks.university/developer.html` (`target="_blank"`, `rel="noopener noreferrer"`) |
| Developer photo | `/about_beryndil.png` at 80 × 80 with `border-radius: 50%` and `object-fit: cover` |
| Coffee CTA card | Eyebrow "Enjoy Bearings?" + "Buy Me a Cup of Coffee" link → same developer URL |

### Identity card

A bordered card with four rows rendered below the hero:

| Row | Content |
|---|---|
| Build | Formatted from `build_mtime` (Unix timestamp, seconds) returned by `GET /api/diag/server`. Non-finite or `null` → "dev build". Valid timestamp → `new Date(ts * 1000).toLocaleString()`. |
| Repository | `github.com/Beryndil/Bearings` → `https://github.com/Beryndil/Bearings` |
| License | "MIT" → `https://github.com/Beryndil/Bearings/blob/main/LICENSE` |
| Credits | "CREDITS.md" → `https://github.com/Beryndil/Bearings/blob/main/CREDITS.md` |

All identity card links open `target="_blank"` with `rel="noopener noreferrer"`.

### `GET /api/diag/server` — `build_mtime` field

`ServerDiagOut` now includes `build_mtime: float | None`. The backend computes it as the `st_mtime` of `bearings/__init__.py` (proxy for install/build time). Returns `null` when the path cannot be resolved (e.g., namespace packages).

## API contract summary

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/preferences` | Returns `PreferencesOut` including profile fields and `notify_on_complete` |
| `PATCH` | `/api/preferences` | Partial update; `display_name` and `notify_on_complete` patchable here |
| `GET` | `/api/preferences/avatar` | Serve avatar bytes |
| `POST` | `/api/preferences/avatar` | Upload avatar (multipart) |
| `DELETE` | `/api/preferences/avatar` | Remove avatar |
| `POST` | `/api/preferences/sync_from_system` | Populate from OS environment |

## Per-device localStorage preferences (addendum — gap-cycle-07-006)

Some preferences are per-device by design and are stored in `localStorage` only — they are NOT round-tripped through `/api/preferences`. The rationale: a laptop in CT and a phone abroad each need independent values for these settings.

| Key | Type | Default (absent) | Description |
|---|---|---|---|
| `bearings:display:timezone` | IANA timezone string | Auto (browser default) | Display timezone for all timestamp surfaces. Absence of the key == "Auto". Managed by `frontend/src/lib/stores/displaySettings.svelte.ts`; formatted via `formatAbsolute` in `frontend/src/lib/utils/datetime.ts`. |
| `bearings-theme-v1` | theme ID string | OS-color-scheme fallback | UI theme. See [themes.md](themes.md). |
| `bearings-v1:session-sort` | `"last_action"` \| `"grouped"` | `"last_action"` | Sidebar session sort order. |
| `bearings-v1:auth-token` | raw token string | (none) | Auth token for the API auth gate. |
