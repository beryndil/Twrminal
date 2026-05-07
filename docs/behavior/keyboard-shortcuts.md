# Keyboard shortcuts — observable behavior

Bearings ships a fixed set of global keyboard chords plus a few context-specific bindings. The full list is rendered live in the in-app cheat sheet (opened with `?`) — that is the user's source of truth, so this doc and the cheat sheet must agree by construction. This document lists what the user observes; implementation choices are governed by `docs/architecture-v1.md`.

Sibling subsystems referenced here:
[chat](chat.md), [checklists](checklists.md), [context-menus](context-menus.md), [paired-chats](paired-chats.md).

## What the user sees

* Pressing `?` (anywhere outside an input) opens the cheat sheet modal; pressing `?` again while the cheat sheet is open closes it. The modal lists every active binding grouped by purpose; each chord is rendered as `<kbd>`-style key caps so `Shift+C` shows as `[Shift][C]`.
* The cheat sheet renders two tables in order: (1) the global keybinding registry (the same array that wires the dispatcher), then (2) a static non-registry table of context-local chords (`frontend/src/lib/keyboard/nonRegistryBindings.ts`) covering the composer (`Enter` / `Shift+Enter`), context menus (arrow navigation, `Enter`, `→`, `Esc`, mnemonics), and checklists (`Tab` / `Shift+Tab` / `Enter`). Adding a context-local row only requires editing `nonRegistryBindings.ts` — the dispatcher and registry are not touched.
* Conflicting chords are not allowed at boot time. A duplicate registration crashes early (in development) so a typo cannot silently shadow a working key in production.

## Bindings (v1)

### Create

| Chord | Action |
|---|---|
| `c` | Open the **new chat** dialog. |
| `Shift+C` | Open the new-chat dialog **without** the seeded routing / tag defaults — empty form. |
| `t` | Open the **template picker**. Selecting a template populates the new-chat form. |

### Navigate (sidebar)

| Chord | Action |
|---|---|
| `j` | Move sidebar selection one row **down** (wraps at the bottom). |
| `k` | Move sidebar selection one row **up** (wraps at the top). |
| `Alt+]` | Same as `j`, but the modifier variant fires even with focus inside an input. |
| `Alt+[` | Same as `k`, modifier variant. |
| `Alt+1` … `Alt+9` | Jump directly to sidebar slot N (1-indexed). Out-of-range slots are no-ops. |

`j` and `k` only apply over the **open** sidebar list — closed sessions are not part of the rotation. Selecting a row both focuses it and reconnects the conversation pane (the same effect a mouse click has).

### Focus

| Chord | Action |
|---|---|
| `Esc` | Close the highest-priority overlay first; then defocus a focused input; then no-op. |

The Esc cascade in priority order:

1. If a context menu is open (see [context-menus](context-menus.md)), close it.
2. Else if the command palette is open, close it.
3. Else if a floating "pending operations" card is open, close it.
4. Else if any other overlay (cheat sheet, modal, dropdown) is open, dismiss it.
5. Else if focus is inside an input / textarea / contenteditable, blur it.
6. Else no-op.

### Help

| Chord | Action |
|---|---|
| `?` | Toggle the cheat-sheet modal. |
| `Ctrl+Shift+O` | Toggle the **pending-operations** floating card (global; fires even with focus inside an input). |

### Command palette

| Chord | Action |
|---|---|
| `Ctrl+Shift+P` | Toggle the **command palette** (global). |
| `Ctrl+K` | Focus the **sidebar search** field. |

`Ctrl+K` is wired by the sidebar search component itself (the focus target is colocated with the input); the cheat sheet lists it for discoverability.

## Contexts (sidebar focused, conversation focused, modal open)

### Sidebar focused

* `j` / `k` and `Alt+1..9` work as listed above. Bare-letter chords (`c`, `Shift+C`, `t`, `?`) also work since no input is focused.
* Right-click on a row opens the [context menu](context-menus.md) for that row's target type.

### Conversation focused (composer NOT focused)

* All bare-letter chords still work. The conversation panel itself does not steal letter chords.
* Scroll keys (PgUp / PgDn / arrow keys) follow native browser behavior.

### Composer focused (textarea has focus)

* Bare-letter chords (`c`, `Shift+C`, `t`, `j`, `k`, `?`) **do not fire** — the user is typing; the keystrokes go into the composer.
* The `Alt+...` and `Ctrl+...` global chords (Alt+1..9, Alt+[, Alt+], Ctrl+Shift+P, Ctrl+Shift+O, Esc) still fire even with the composer focused.
* `Esc` blurs the composer (blur is the lowest priority in the Esc cascade above; if no overlay is open, the composer's blur step runs).

### Modal open (new-session dialog, template picker, cheat sheet, etc.)

* The modal is the foreground; sidebar navigation chords do not fire.
* `Esc` closes the modal (highest priority of the Esc cascade).
* `?` closes the cheat sheet when the cheat sheet is the open modal (the toggle fires even with a modal open, but only when no input inside the modal is focused).
* Modal-internal shortcuts (Tab, Shift+Tab, Enter on the primary action, Esc) follow standard form behavior.

### Checklist pane focused

In addition to the global bindings:

* **Tab** on a focused item label nests it under the previous sibling.
* **Shift+Tab** un-nests it (parent → grandparent).
* **Enter** in the Add-item input creates the item and refocuses the input.
* **Enter** in an inline-edit input commits; **Esc** cancels (Esc here is the input-blur step of the global cascade).

See [checklists](checklists.md) for nesting / edit details.

### Context menu open

* **Up / Down** arrow keys move the highlighted item.
* **Enter** activates the highlighted item.
* **Right** opens a submenu when the highlighted item has one.
* **Esc** closes the menu (priority 1 of the Esc cascade).
* Mnemonic letters underlined in action labels jump to that action when typed.

## Conflict resolution

* **Duplicate chord** at registration time → fail-fast at development; the app does not start. The user never sees two bindings on the same chord in production.
* **Native browser binding overlap** (e.g. `Ctrl+K` on Firefox focuses the URL bar). Bearings calls `preventDefault` on chords it owns when the chord matches and is allowed in the current context, so the in-app behavior wins. Chords listed `displayOnly` in the cheat sheet (e.g. `Ctrl+K`) are wired by the owning component, which performs the same prevent-default.
* **Modifier-equivalence on Mac.** `Ctrl` and `Cmd` are treated as equivalent on platforms where `Cmd` is the primary modifier — the documented `Ctrl+Shift+P` works for a Mac visitor without a separate table.
* **Non-US keyboard layouts.** Letter chords compare against the physical key code (e.g. the key in the `KeyC` slot on a US layout), so `c` triggers the new-chat dialog regardless of what character that key produces under AltGr or a non-US layout. Named keys (`Escape`, `[`, `]`, `?`) compare against the produced character, since those slots vary by layout in ways the physical-code path can't paper over.
* **`global: true` bindings vs input focus.** Power-user chords (`Ctrl+Shift+P`, `Ctrl+Shift+O`, `Alt+1..9`, `Alt+[`, `Alt+]`, `Esc`) fire even with an input focused. Bare-letter bindings do not — typing a `c` into a composer textarea must produce a `c`, not open the new-chat dialog.

## What is NOT a v1 binding

* Vim-style chord composition (`g g`, `d d`, etc.) — out of scope.
* User-rebinding via `keybindings.toml` — the registry is the obvious place to plug it in later; v1 ships fixed.
* Chord recording / "what did I just press?" overlay — out of scope.
* OS-level global hotkeys (registering a chord that fires when Bearings is unfocused) — out of scope.
