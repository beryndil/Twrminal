# Settings

The Settings page (`/settings`) is the per-user configuration
surface — themes, keybindings, defaults, authentication, privacy,
data import, and about. This guide walks every section.

The themes / keybindings / context-menu surfaces also have
dedicated behavior docs:
[../behavior/themes.md](../behavior/themes.md),
[../behavior/keyboard-shortcuts.md](../behavior/keyboard-shortcuts.md),
[../behavior/context-menus.md](../behavior/context-menus.md),
[../behavior/preferences.md](../behavior/preferences.md). For
tag management see the **Tags** page (separate route — see below).

## What you can do here

* [Navigate the settings layout](#navigate-the-settings-layout)
* [Edit your profile / display name / avatar](#profile-section)
* [Switch theme](#appearance-section)
* [Set new-session defaults (model, working dir, permission mode)](#defaults-section)
* [Configure notifications](#notifications-section)
* [Set or rotate the auth token](#authentication-section)
* [Set privacy preferences](#privacy-section)
* [Manage system-wide routing rules](#system-routing-section)
* [Import data from a v0.17.x install](#data-import-section)
* [Discover keyboard shortcuts](#help-section)
* [Read app version + build info](#about-section)
* [Manage tags (separate page)](#tags-page-separate-route)

---

## Walkthrough

### Navigate the settings layout

The `/settings` route renders a two-column `SettingsShell` layout:

* **Left nav rail** — `role="tablist"` with one button per
  registered section in weight order. Active button has
  `aria-selected="true"` and the focusable `tabindex`. Keyboard
  navigation: ↑/↓ moves the active section one step (wraps);
  Home / End jump to first / last.
* **Right content pane** — one `role="tabpanel"` per section.
  Inactive panels render with `display:none` rather than
  unmounting, so per-section state and test selectors stay valid.

The active section id is **mirrored into `?settings=<id>`** via
`history.replaceState` on every section switch. On mount, the
shell reads `window.location.search` to honour deep-links;
unrecognised ids fall back to the first registered section.

A **save-status footer** at the bottom of the content pane shows
the aggregated save status of the active section: *"Saving…"*,
*"All changes saved"*, or *"Failed to save: {message}"*. Absent
when idle.

### Section registry

| id | label | section component |
|---|---|---|
| `profile` | Profile | `ProfileSection` |
| `appearance` | Appearance | `AppearanceSection` |
| `defaults` | Defaults | `DefaultsSection` |
| `notifications` | Notifications | `NotificationsSection` |
| `authentication` | Authentication | `AuthSection` |
| `privacy` | Privacy | `PrivacySection` |
| `routing` | System routing | `RoutingRulesSection` |
| `import` | Data import | `ImportSection` |
| `help` | Help | `HelpSection` |
| `about` | About | `AboutSection` |

Adding a section requires one append to
`frontend/src/lib/components/settings/sections.ts` — no changes
to `+page.svelte` or `SettingsShell.svelte`.

### Profile section

Display-name + avatar editor. Display name surfaces in the
session-broadcast WebSocket events for multi-tab presence (when
multiple tabs are open against the same Bearings instance).

`PATCH /api/preferences` for the name field;
`POST /api/preferences/avatar` for the avatar upload.

### Appearance section

The single most-touched setting. Theme picker exposes:

| Theme | Vibe |
|---|---|
| Default | Bearings' default neutral palette. |
| Evergreen | Greens; high-contrast. |
| Midnight Glass | Dark, slightly tinted. |
| Paper Light | Light, paper-toned. |

Themes apply to the app shell (sidebar, header, conversation
panel, inspector, settings dialog), the Markdown content
renderer, every code-block highlighter, and the scrollbar thumb
palette across every scrollable surface. See
[../behavior/themes.md](../behavior/themes.md) for the full
surface inventory.

The theme provider implements **no-flash boot** — the saved theme
loads from `localStorage` before SvelteKit hydrates so the user
never sees a default → saved-theme repaint flash.

Saves immediately on change (`PATCH /api/preferences`).

### Defaults section

Pre-fill values for the new-session form. Four fields, each
**autosaves independently**:

| Field | Control | Save trigger |
|---|---|---|
| `theme` | `<select>` | Immediate on change |
| `default_model` | `<select>` | Immediate on change |
| `default_permission_mode` | `<select>` | Immediate on change |
| `default_working_dir` | `<input type="text">` | Debounced ~400ms |

There is **no Save button**. Each field row carries a per-row
save badge:

| State | Text | Role |
|---|---|---|
| Saving | *"Saving…"* | `status` |
| Saved | *"Saved"* | `status` (auto-fades after ~2s) |
| Error | *"Failed to save: {message}"* | `alert` |

Backed by `PATCH /api/preferences` with only the touched field's
keys (`model_fields_set` semantics — empty body is a no-op).

These defaults seed the new-session form when no recent session
exists. If a recent session does exist, the new-session form
prefers its values (per
[behavior/chat.md §"When the user creates a chat"](../behavior/chat.md#when-the-user-creates-a-chat));
hold **Shift+C** to start fresh from the defaults.

### Notifications section

Toggles for:

* desktop browser notifications (request permission via the
  Notifications API on first enable);
* in-app sound on agent-needs-input (parked-on-tool-approval
  state);
* per-session notification opt-out persisted on the session row.

### Authentication section

Token management. Bearings binds to `127.0.0.1` by default and
auth is optional for the localhost case; if you've opted into
auth (`auth.enabled = true` in `~/.config/bearings/config.toml`),
this section exposes:

* current token (masked; click to reveal);
* **Rotate token** action — generates a new token, displays it
  once, invalidates the old one;
* allowed origin list for WebSocket connections.

The bind/auth interlock is enforced at server startup —
non-loopback `host` with auth disabled refuses to start. See
[cli.md §`bearings serve`](cli.md#bearings-serve).

### Privacy section

* Tracking-consent toggle (off by default — Bearings doesn't
  send anything off-machine without explicit opt-in).
* Analytics opt-in / opt-out for any future telemetry surfaces.

### System routing section

This is where the **system-wide fallback routing rules** live —
the rules that fire when no per-tag rule matched. See
[routing.md §Create a system-wide fallback rule](routing.md#create-a-system-wide-fallback-rule).

The same editor surface that the Tags page exposes for per-tag
rules is reused here, scoped to the system rule set.

### Data import section

Import sessions from a v0.17.x Bearings install (or from any
JSON export). Two paths:

* **Bulk import** — point at a v0.17.x data directory; Bearings
  walks every session and imports them through
  `POST /api/import/bearings` with conflict-resolution
  (`?force=true` re-imports overwriting existing UUIDs).
* **Single-file import** — same as the sidebar Import button;
  paste JSON or pick a `.json` file. See
  [sessions.md §Import a session from JSON](sessions.md#import-a-session-from-json).

### Help section

In-app cheat-sheet for keyboard shortcuts, mirrored from the
keybinding registry. Reachable in any context via **`?`** as
well — see
[../behavior/keyboard-shortcuts.md](../behavior/keyboard-shortcuts.md).

The cheat-sheet shows:

* global shortcuts (`j` / `k` for sidebar nav, `Alt+1..9` for
  jump, `Shift+C` for clear-defaults new session, `?` for help,
  …);
* context-local bindings — the Composer, the Conversation pane,
  the Inspector, the Vault each carry their own bindings that
  surface only when that surface has focus.

### About section

* App version, build commit, license link.
* Link to the GitHub repo.
* The same megaphone-glyph **Submit feedback** affordance the
  conversation header carries — opens a GitHub Issues form pre-
  filled with version, browser UA, platform, and a steps-to-
  reproduce scaffold. Bearings does **not POST any data**; the
  user submits the form manually.

---

## Tags page (separate route)

Tag management does **not** live under Settings. It has its own
route — `/tags` — accessible from the sidebar primary nav rail.

What the tags page exposes:

* **List** every tag with name, class, color, default-model,
  working-dir, sort order.
* **Create** a tag (the same inline-create surface the new-session
  dialog exposes is also reachable here without leaving the page).
* **Edit** a tag's name, class, color, default model,
  `working_dir`, sort order.
* **Edit per-tag routing rules** — same editor as Settings →
  System routing, scoped to the tag.
* **Edit per-tag memories** — the same editor `MemoriesEditor`
  exposes from the global memories index.
* **Delete** a tag with cascade preview — shows how many sessions
  carry the tag and which routing rules / memories will be
  deleted along with it.

For the tag model and class semantics see
[../concepts.md §3](../concepts.md#3-how-tags-drive-everything).

For routing-rule editing see [routing.md](routing.md). For
memories see [vault-and-memories.md](vault-and-memories.md).

---

## Reference

### Action surface

| Action | Trigger | Endpoint |
|---|---|---|
| Read preferences | Page load | `GET /api/preferences` |
| Save preference | Field edit | `PATCH /api/preferences` |
| Set avatar | Profile section upload | `POST /api/preferences/avatar` |
| Sync from system | Profile section button | `POST /api/preferences/sync_from_system` |
| List tags | Sidebar **Tags** | `GET /api/tags` |
| Create tag | Tag create modal / inline filter | `POST /api/tags` |
| Edit tag | Tag editor save | `PATCH /api/tags/{id}` |
| Delete tag | Tag editor → delete (confirm) | `DELETE /api/tags/{id}` |
| List system rules | Settings → System routing | `GET /api/routing/system_rules/` |
| Create system rule | **+ Rule** | `POST /api/routing/system_rules/` |
| Import bearings dir | Settings → Data import | `POST /api/import/bearings` |
| Read app version | About section | `GET /api/diag/server` |
| Show keybinding cheat-sheet | **`?`** anywhere | (UI only) |

### Per-row save-badge palette

| State | Text | CSS modifier |
|---|---|---|
| Saving | *"Saving…"* | `--saving` (muted fg) |
| Saved | *"Saved"* | `--saved` (accent fg) |
| Error | *"Failed to save: {message}"* | `--error` (error fg) |

### Settings deep-link URL format

```
/settings?settings=<section_id>
```

`section_id` is one of the registered ids
(`profile` / `appearance` / `defaults` / …). Unrecognised values
fall back to the first registered section. The fragment is
mirrored on every section switch via `history.replaceState`.

---

## See also

* [../behavior/preferences.md](../behavior/preferences.md) — full
  preferences observable behavior, including the section registry.
* [../behavior/themes.md](../behavior/themes.md) — theme palette
  surfaces, scrollbar thumb palette, no-flash boot.
* [../behavior/keyboard-shortcuts.md](../behavior/keyboard-shortcuts.md)
  — full keybinding registry.
* [../behavior/context-menus.md](../behavior/context-menus.md) —
  right-click action palette per surface.
* [routing.md](routing.md) — system + per-tag routing rules.
* [vault-and-memories.md](vault-and-memories.md) — memory
  management.
* [getting-started.md](getting-started.md) — first-run defaults.
* [../api.md §preferences](../api.md#preferences),
  [../api.md §tags](../api.md#tags).
* `frontend/src/lib/components/settings/`,
  `frontend/src/routes/settings/`,
  `frontend/src/routes/tags/`.
