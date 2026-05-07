# Themes — observable behavior

The user picks one visual theme that applies to the whole app shell. Theme selection is a per-device preference (it does not follow the user across devices). This document lists what the user observes; implementation choices are governed by `docs/architecture-v1.md`.

Sibling subsystems referenced here:
[chat](chat.md), [keyboard-shortcuts](keyboard-shortcuts.md).

## Theme picker UI

The theme picker lives in **Settings → Appearance**. The user sees a single dropdown labeled **Theme** with three options in v1:

| Option | Visible label |
|---|---|
| `midnight-glass` | "Midnight Glass (warm-navy, glass panels)" |
| `default` | "Default (Tailwind classic dark)" |
| `paper-light` | "Paper Light (cream, flat)" |

Below the theme dropdown is a one-line caption: "Saved per device. Applies immediately." The picker has no Save / Apply button — selecting an option commits the change immediately (no debounce, single click).

When the user lands on the Appearance section for the first time on a device, the dropdown shows the theme that is currently active. If the user has never explicitly picked a theme, the active theme is whatever the OS-color-scheme fallback resolved to: `paper-light` when the OS reports a light scheme, `midnight-glass` otherwise.

## Persistence boundary

* **Per-account, server-synced.** The user's chosen theme persists on the server and is read back when the same account opens Bearings on the same device next time. Two browsers on the same machine share the persisted theme; opening Bearings under a different account starts from the OS-fallback default until the new account picks a theme.
* **Not per-session.** The theme is a global choice. Switching between sessions in the sidebar does not change the theme; opening a checklist does not change the theme; tag changes do not change the theme.
* **Not per-tab.** Two tabs of Bearings open at the same time will both reflect a theme change initiated in either of them once the originating tab's commit lands and the other tab next renders.

## What gets re-themed live

When the user picks a different theme, the change lands **synchronously in the same tick** as the network success — the user does not see a flash of unstyled content. Every visible surface that uses themed color tokens re-tints immediately:

* The app shell (sidebar, header, conversation panel, inspector, settings dialog);
* Conversation message bubbles, code-block backgrounds, syntax-highlighting palette (the active syntax theme tracks the app theme — see addendum below);
* Sidebar row backgrounds, hover states, selected-row accent;
* Tag chips and severity shields;
* Form controls (inputs, selects, buttons, modal chrome);
* The browser's address-bar / mobile-chrome color (via the `<meta name="theme-color">` tag).

The mobile-chrome color is the only piece that can briefly drift on first load: a no-flash boot script paints the address bar before the runtime theme module loads. If the boot script's idea of the color disagrees with what the runtime would compute, the runtime corrects it on the next tick. The user observes at most a single-frame mismatch on cold load, never on a live theme switch.

The boot script is implemented as a synchronous IIFE in `frontend/src/app.html` (before the `%sveltekit.head%` injection point) with its logic mirrored in `frontend/src/lib/themes/boot.ts` for testability. The runtime drift detector lives in `frontend/src/lib/themes/ThemeProvider.svelte`.

## What does NOT get re-themed live

* **Image assets shown inside chat content.** A screenshot pasted into a message keeps its original colors; themes do not adjust user-supplied images.
* **`<iframe>`-embedded content.** External docs the user opens in iframes (rare) stay on their own theme.
* **The OS window chrome.** Bearings cannot repaint the window decorations the user's compositor draws around the browser window; what the OS shows is independent of theme.
* **Already-rendered tool-output blocks.** Tool output that contains terminal escape sequences (e.g. ANSI color codes) keeps the terminal-color palette it was rendered with. The terminal palette is a constant; the app shell around it re-tints, but the colored bytes inside the block do not change.
* **Browser-native scroll bars** when the user's OS / browser overrides them. The app paints custom scroll bars where it can; native ones the browser hands out are unaffected.

## Switching themes during a streaming turn

A theme switch is safe at any point. If the user changes themes while an assistant turn is streaming, the new theme paints around the turn in the same tick; the streaming text continues to arrive in the new theme's bubble color. No scrolling, no re-layout that could confuse the conversation auto-scroll (see [chat](chat.md)).

## Failure modes

* **Server-sync write fails** (network blip on the preferences PATCH). The local preview reverts to whatever the server still has on file; the user sees a "couldn't save your theme — try again" toast. The active theme remains the previously-saved one to keep the app and the server consistent.
* **Drift between boot script and runtime.** The runtime detects the case after init and emits a `console.warn` for developers; users see no prompt. The runtime's theme is authoritative; the boot script is corrected on the next tick.
* **Removed theme.** If the persisted theme name no longer exists in a future build, the app resolves to the OS-fallback default and the picker shows that fallback as the active option.

## What the user does NOT control via the theme picker

* The display **timezone**. That is a separate Settings → Appearance control (also per-device, persisted in local storage rather than on the server, since a laptop in CT and a phone abroad each want their own display tz). **As of gap-cycle-07-006 this control is wired** — see addendum below.
* The **locale** for date / number formatting. Deferred for v1; helpers accept a locale already, so a follow-up can surface this without disturbing existing strings.
* **Per-component overrides.** The user cannot pick a different theme for the conversation pane vs the sidebar; theme is global.
* **Custom theme uploads.** v1 ships with the three named themes. Custom user themes are out of scope.

## Syntax-highlighting palette wiring (addendum — gap-cycle-04-002)

Fenced code blocks inside conversation messages are highlighted by shiki via
`frontend/src/lib/render.ts:highlightCode()`.  The function uses shiki's
`createCssVariablesTheme()` so every highlighted `<span>` receives inline
`style="color: var(--shiki-token-*)"` placeholders rather than baked hex
literals.

The palette values for each Bearings theme are defined in `frontend/src/app.css`
under their respective `[data-theme]` selector blocks, using these custom properties:

| Property | Purpose |
|---|---|
| `--shiki-foreground` | Default code text color |
| `--shiki-background` | Code block background (matches `surface-2`) |
| `--shiki-token-comment` | Comment tokens |
| `--shiki-token-keyword` | Keywords |
| `--shiki-token-string` | String literals |
| `--shiki-token-string-expression` | Template / expression strings |
| `--shiki-token-constant` | Constants / booleans / numbers |
| `--shiki-token-function` | Function names |
| `--shiki-token-parameter` | Function parameters |
| `--shiki-token-punctuation` | Brackets, operators |
| `--shiki-token-link` | URLs in comments / strings |

Dark themes (`evergreen`, `midnight-glass`, `default`) set 200–300-range light
token colors so they are readable on dark surfaces.  `paper-light` sets 700–800-range
dark token colors so they hold contrast on the cream background.  Neither pairing
produces light-on-light or dark-on-dark output.

Because the highlighted HTML already carries CSS-var placeholders, switching the
active Bearings theme is a **pure `data-theme` attribute flip on `<html>`** — the
already-rendered code blocks re-tint synchronously with the rest of the app shell;
no re-render or re-highlight pass is required.

## Per-theme visual treatments (addendum — gap-cycle-04-003)

Beyond color tokens, each theme applies distinct structural treatments via per-theme CSS files
imported at the end of `frontend/src/app.css`.  All rules are scoped under
`[data-theme="<name>"]` on `<html>` so switching the attribute is the only thing required to
activate or deactivate any effect.

| Theme | Treatment file | Effect summary |
|---|---|---|
| `midnight-glass` | `frontend/src/lib/themes/midnight-glass.css` | Aurora body wash (three `radial-gradient` nodes, `background-attachment: fixed`); `<aside>` glass panels (`backdrop-filter: blur(18px) saturate(160%)`, 55 % alpha background); conversation section 40 % alpha blur layer; active-row left-weighted violet gradient + inset + outer glow; primary button gradient overlay + `translateY(-1px)` hover lift; code block violet inner glow; 3 px violet `focus-visible` ring. Reduced-motion: button `transition-duration` collapses to 0.01 ms. |
| `evergreen` | `frontend/src/lib/themes/evergreen.css` | Subtle 2-stop slate body gradient; emerald inset-bar selected-row accent; hairline code-block border; 2 px emerald flat focus outline. Also applied under `:root` (default before any theme is picked). |
| `paper-light` | `frontend/src/lib/themes/paper-light.css` | Warm cream 2-stop body gradient; Prussian-blue inset-bar selected-row accent; warm-parchment hairline code-block border; 2 px Prussian-blue flat focus outline. |
| `default` | `frontend/src/lib/themes/default.css` | Subtle gray-900 2-stop body gradient; sky-blue inset-bar selected-row accent; gray hairline code-block border; 2 px sky-blue flat focus outline. |

The three flat themes (`evergreen`, `paper-light`, `default`) never set `backdrop-filter` or
`radial-gradient` — switching away from `midnight-glass` removes every glass/aurora pixel in the
same tick the `data-theme` attribute flips.

A vitest contract suite at `frontend/src/lib/themes/__tests__/treatments.test.ts` asserts the
mapping: `midnight-glass.css` must declare `backdrop-filter` and `radial-gradient`; all three
flat theme files must declare neither.

## Adding a new theme (user-observable consequences only)

This subsystem doc does not list authoring steps. From the user's perspective, when a future build adds a theme:

* the new option appears in the dropdown alongside the existing three;
* picking it works exactly like picking any other theme — synchronous re-tint, server-synced, mobile-chrome color updated;
* the existing themes remain available unchanged.

## Display timezone control (addendum — gap-cycle-07-006)

The timezone select lives in **Settings → Appearance**, directly below the theme picker. It is a separate control from the theme — see §"What the user does NOT control via the theme picker" above.

### What the user sees

A dropdown labeled **Display timezone** with ten options:

| Option value | Visible label |
|---|---|
| Auto | "Auto (browser default)" |
| UTC | "UTC" |
| America/New_York | "America/New York (ET)" |
| America/Chicago | "America/Chicago (CT)" |
| America/Denver | "America/Denver (MT)" |
| America/Los_Angeles | "America/Los Angeles (PT)" |
| Europe/London | "Europe/London (GMT/BST)" |
| Europe/Paris | "Europe/Paris (CET/CEST)" |
| Asia/Tokyo | "Asia/Tokyo (JST)" |
| Asia/Shanghai | "Asia/Shanghai (CST)" |

Below the select is a caption: "Saved per device. Timestamps re-render immediately."

### Persistence

* **Per-device only** — stored in `localStorage` under `bearings:display:timezone`. NOT round-tripped to `/api/preferences` so devices share themes but keep independent display timezones.
* **"Auto" stores nothing.** Absence of the key in `localStorage` is the canonical representation of "Auto". Selecting "Auto" removes the key rather than writing a sentinel.

### What re-renders on change

Switching the timezone re-renders all surfaces that use `formatAbsolute` from `frontend/src/lib/utils/datetime.ts` **in the same tick**:

* Routing timeline timestamps in the Inspector → Routing tab.
* Reorg audit divider timestamps in the conversation pane.
* Quota reset tooltips in the new-session dialog.
* The Settings → About "Build" row.

### Implementation path

`frontend/src/lib/stores/displaySettings.svelte.ts` owns the reactive `displaySettingsStore.timezone` state.
`frontend/src/lib/utils/datetime.ts:formatAbsolute` reads it on every call — because the store is a Svelte 5 `$state` object, any `$derived` that calls `formatAbsolute` re-runs automatically when the timezone changes, propagating the re-render without any additional subscription or effect.
