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
* Conversation message bubbles, code-block backgrounds, syntax-highlighting palette (the active syntax theme tracks the app theme);
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

* The display **timezone**. That is a separate Settings → Appearance control (also per-device, persisted in local storage rather than on the server, since a laptop in CT and a phone abroad each want their own display tz).
* The **locale** for date / number formatting. Deferred for v1; helpers accept a locale already, so a follow-up can surface this without disturbing existing strings.
* **Per-component overrides.** The user cannot pick a different theme for the conversation pane vs the sidebar; theme is global.
* **Custom theme uploads.** v1 ships with the three named themes. Custom user themes are out of scope.

## Adding a new theme (user-observable consequences only)

This subsystem doc does not list authoring steps. From the user's perspective, when a future build adds a theme:

* the new option appears in the dropdown alongside the existing three;
* picking it works exactly like picking any other theme — synchronous re-tint, server-synced, mobile-chrome color updated;
* the existing themes remain available unchanged.
