/**
 * Central keyboard-shortcut registry. Defines every globally-dispatched
 * binding in one typed map and exposes a single `dispatchShortcut`
 * entry point for the page-level keydown listener. The CheatSheet
 * pulls its display rows from the same registry so the docs cannot
 * drift from the wiring.
 *
 * Why a registry rather than per-component listeners:
 *   - One source of truth for the cheat-sheet renderer. Adding a
 *     binding adds the docs row automatically; deleting a binding
 *     deletes the row. No docs-rot.
 *   - Conflict surfacing — duplicate chords throw at module load
 *     (test-covered), so a typo can't silently shadow a working key.
 *   - Future user-rebinding hook: the registry is the obvious place
 *     to plug in `keybindings.toml` overrides when that lands.
 *
 * v1 scope (decided 2026-04-25 in session f66e25b2):
 *   - Create: `c`, `Shift+C`, `t`
 *   - Navigate: `j`/`k`, `Alt+1..9`, `Alt+[` / `Alt+]`
 *   - Focus: `Esc` (defocus / dismiss overlay)
 *   - Help: `?` (cheat sheet)
 *   - Command palette: `Ctrl+Shift+P`, `Ctrl+K` (sidebar search) —
 *     `Ctrl+K` stays wired in `SidebarSearch.svelte` for now and is
 *     listed here only for the cheat-sheet display; see DISPLAY_ONLY.
 *
 * Each binding's `chord` matches the renderer's split-on-`+` format,
 * so the cheat sheet can render `Shift+C` as `[Shift][C]` without
 * a separate display field.
 */

import { agent } from '$lib/agent.svelte';
import { palette } from '$lib/context-menu/palette.svelte';
import { contextMenu } from '$lib/context-menu/store.svelte';
import { pending } from '$lib/stores/pending.svelte';
import { sessions } from '$lib/stores/sessions.svelte';
import { uiActions } from '$lib/stores/ui_actions.svelte';

export type BindingGroup =
  | 'Create'
  | 'Navigate'
  | 'Focus'
  | 'Help'
  | 'Command palette';

export type BindingDef = {
  /** Stable id — keep alphabetical inside group, kebab-case. Used by
   * tests and (future) `keybindings.toml` overrides. */
  id: string;
  /** Chord string, e.g. `c`, `Shift+C`, `Alt+1`, `Ctrl+Shift+P`, `Esc`.
   * The renderer splits on `+`; modifier order is fixed to
   * `Ctrl Shift Alt <key>` so duplicate detection works. */
  chord: string;
  /** Cheat-sheet group label. */
  group: BindingGroup;
  /** Cheat-sheet description. */
  label: string;
  /** When `true`, binding fires even when an input/textarea has focus.
   * Reserve for power-user chords (Ctrl+Shift+P, Esc). Bare-letter
   * bindings must NOT be global — typing 'c' into a textarea is the
   * common case and stealing it would break composition. */
  global?: boolean;
  /** Cheat-sheet only — no event handler. The `chord` is documented
   * but `dispatchShortcut` ignores it. Use for shortcuts wired
   * elsewhere (e.g. SidebarSearch's `Ctrl+K`). */
  displayOnly?: boolean;
  /** Action handler. Only consulted when `displayOnly` is falsy. */
  run?: (e: KeyboardEvent) => void;
};

// ---------- chord parsing ----------

type ChordReq = {
  ctrl: boolean;
  shift: boolean;
  alt: boolean;
  /** Either a single uppercased letter (`C`), digit (`1`), or a named
   * key (`Escape`, `[`, `]`). Compared against the event with
   * key-then-code fallbacks below. */
  key: string;
};

function parseChord(chord: string): ChordReq {
  const parts = chord.split('+').map((s) => s.trim()).filter(Boolean);
  if (parts.length === 0) throw new Error(`empty chord: ${chord}`);
  const last = parts[parts.length - 1];
  const mods = parts.slice(0, -1).map((p) => p.toLowerCase());
  return {
    ctrl: mods.includes('ctrl'),
    shift: mods.includes('shift'),
    alt: mods.includes('alt'),
    key: last
  };
}

/** True when the event matches the parsed chord requirements. Letters
 * and digits compare against `e.code` so non-US keyboard layouts and
 * AltGr remappings still match the binding the user sees in the cheat
 * sheet. Named keys (`Escape`, `[`, `]`) compare against `e.key`. */
function matches(e: KeyboardEvent, req: ChordReq): boolean {
  // Treat `Cmd` and `Ctrl` as equivalent on Mac so Dave's documented
  // `Ctrl+Shift+P` works for any future Mac visitor without a second
  // table. Linux is the daily driver — `metaKey` is rare but harmless.
  const ctrl = e.ctrlKey || e.metaKey;
  if (req.ctrl !== ctrl) return false;
  if (req.shift !== e.shiftKey) return false;
  if (req.alt !== e.altKey) return false;

  const k = req.key;
  if (k.length === 1 && /[A-Za-z]/.test(k)) {
    return e.code === `Key${k.toUpperCase()}`;
  }
  if (/^[0-9]$/.test(k)) {
    return e.code === `Digit${k}` || e.key === k;
  }
  if (k === '[') return e.key === '[' || e.code === 'BracketLeft';
  if (k === ']') return e.key === ']' || e.code === 'BracketRight';
  if (k === 'Esc' || k === 'Escape') return e.key === 'Escape';
  if (k === '?') return e.key === '?';
  return e.key === k;
}

function isInputFocused(target: EventTarget | null): boolean {
  // Re-read activeElement: Chrome sometimes routes keydown through the
  // body when the textarea is focused by JS rather than user click.
  const el =
    (target instanceof HTMLElement ? target : null) ??
    (typeof document !== 'undefined'
      ? (document.activeElement as HTMLElement | null)
      : null);
  if (!el) return false;
  if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') return true;
  if (el.isContentEditable) return true;
  return false;
}

// ---------- action handlers ----------

/** Move sidebar selection by `delta`, wrapping at both ends. Reads
 * `sessions.openList` so closed sessions don't enter the rotation —
 * matches the visual order in the sidebar. Calls `agent.connect`
 * after `select` so the conversation pane updates the same way a
 * mouse click does. */
async function navigateRelative(delta: number): Promise<void> {
  const list = sessions.openList;
  if (list.length === 0) return;
  const currentId = sessions.selectedId;
  const idx = currentId ? list.findIndex((s) => s.id === currentId) : -1;
  let nextIdx: number;
  if (idx < 0) nextIdx = delta > 0 ? 0 : list.length - 1;
  else nextIdx = ((idx + delta) % list.length + list.length) % list.length;
  const next = list[nextIdx];
  if (!next) return;
  sessions.select(next.id);
  void sessions.markViewed(next.id);
  await agent.connect(next.id);
}

async function jumpToIndex(n: number): Promise<void> {
  const list = sessions.openList;
  if (n < 0 || n >= list.length) return;
  const target = list[n];
  if (!target) return;
  sessions.select(target.id);
  void sessions.markViewed(target.id);
  await agent.connect(target.id);
}

/** Esc cascade: close the highest-priority overlay first, then defocus
 * a focused input, then no-op. Each step is independent so Esc inside
 * a textarea (priority: blur the textarea) doesn't accidentally close
 * the cheatsheet, and Esc with no overlay still blurs.
 *
 * Context menu sits at the top because its document-capture-phase
 * keydown listener swallows alphanumeric keystrokes destined for any
 * focused field — leaving a stuck-open menu wedges the composer
 * textarea (TODO 2026-04-26 wedge fix). The menu's own Esc handling
 * defers to a focused field outside the menu, so without this branch
 * Esc-from-textarea wouldn't close it. */
function handleEscape(e: KeyboardEvent): void {
  if (contextMenu.state.open) {
    e.preventDefault();
    contextMenu.close();
    return;
  }
  if (palette.open) {
    e.preventDefault();
    palette.hide();
    return;
  }
  if (pending.closeCard()) {
    e.preventDefault();
    return;
  }
  if (uiActions.dismissOverlays()) {
    e.preventDefault();
    return;
  }
  const active = (typeof document !== 'undefined'
    ? document.activeElement
    : null) as HTMLElement | null;
  if (
    active &&
    (active.tagName === 'INPUT' ||
      active.tagName === 'TEXTAREA' ||
      active.isContentEditable)
  ) {
    e.preventDefault();
    active.blur();
  }
}

// ---------- registry ----------

function buildBindings(): BindingDef[] {
  const out: BindingDef[] = [
    // Create
    {
      id: 'create.new-chat',
      chord: 'c',
      group: 'Create',
      label: 'New chat',
      run: () => uiActions.toggleNewSession()
    },
    {
      id: 'create.new-chat-with-options',
      chord: 'Shift+C',
      group: 'Create',
      label: 'New chat (skip seeded defaults)',
      run: () => uiActions.toggleNewSession({ fresh: true })
    },
    {
      id: 'create.from-template',
      chord: 't',
      group: 'Create',
      label: 'New chat from template',
      run: () => uiActions.toggleTemplatePicker()
    },

    // Navigate
    {
      id: 'navigate.next',
      chord: 'j',
      group: 'Navigate',
      label: 'Next session in sidebar',
      run: () => void navigateRelative(1)
    },
    {
      id: 'navigate.prev',
      chord: 'k',
      group: 'Navigate',
      label: 'Previous session in sidebar',
      run: () => void navigateRelative(-1)
    },
    {
      id: 'navigate.bracket-next',
      chord: 'Alt+]',
      group: 'Navigate',
      label: 'Next session (modifier variant)',
      global: true,
      run: () => void navigateRelative(1)
    },
    {
      id: 'navigate.bracket-prev',
      chord: 'Alt+[',
      group: 'Navigate',
      label: 'Previous session (modifier variant)',
      global: true,
      run: () => void navigateRelative(-1)
    },

    // Focus
    {
      id: 'focus.escape',
      chord: 'Esc',
      group: 'Focus',
      label: 'Defocus input / dismiss overlay',
      global: true,
      run: handleEscape
    },

    // Help
    {
      id: 'help.cheat-sheet',
      chord: '?',
      group: 'Help',
      label: 'Show this cheat sheet',
      run: () => uiActions.toggleCheatSheet()
    },

    // Pending operations
    {
      id: 'pending.toggle',
      chord: 'Ctrl+Shift+O',
      group: 'Help',
      label: 'Toggle pending-ops card',
      global: true,
      run: () => pending.toggleCard()
    },

    // Command palette
    {
      id: 'palette.toggle',
      chord: 'Ctrl+Shift+P',
      group: 'Command palette',
      label: 'Toggle command palette',
      global: true,
      run: () => palette.toggle()
    },
    {
      id: 'palette.search',
      chord: 'Ctrl+K',
      group: 'Command palette',
      label: 'Focus the sidebar search',
      // SidebarSearch wires this directly so the focus target is
      // colocated with the input ref. Listed here only for cheat-sheet
      // display; the dispatcher skips it.
      displayOnly: true
    }
  ];

  // Alt+1..9 — jump to the Nth open session. Generated rather than
  // hand-listed so the cheat-sheet group renders one row per slot
  // and adding a 10th means changing one number.
  for (let n = 1; n <= 9; n++) {
    const idx = n - 1;
    out.push({
      id: `navigate.jump-${n}`,
      chord: `Alt+${n}`,
      group: 'Navigate',
      label: `Jump to session ${n}`,
      global: true,
      run: () => void jumpToIndex(idx)
    });
  }

  return out;
}

const BINDINGS: BindingDef[] = buildBindings();

// Compile-time-ish duplicate guard. Two bindings on the same chord
// would be a silent shadowing bug at runtime; failing fast at import
// surfaces the typo before the page renders.
{
  const seen = new Map<string, string>();
  for (const b of BINDINGS) {
    if (seen.has(b.chord)) {
      throw new Error(
        `keyboard binding chord conflict: "${b.chord}" used by both ` +
          `${seen.get(b.chord)} and ${b.id}`
      );
    }
    seen.set(b.chord, b.id);
  }
}

const PARSED: { def: BindingDef; req: ChordReq }[] = BINDINGS.map((def) => ({
  def,
  req: parseChord(def.chord)
}));

// ---------- public api ----------

/** Registry export — read-only; callers are not expected to mutate. */
export const bindings: readonly BindingDef[] = BINDINGS;

/** Cheat-sheet shape: bindings grouped by `group`, preserving the
 * registry order within each group. Order of groups is the order they
 * first appear in `BINDINGS`. */
export function groupedBindings(): { group: BindingGroup; items: BindingDef[] }[] {
  const order: BindingGroup[] = [];
  const map = new Map<BindingGroup, BindingDef[]>();
  for (const b of BINDINGS) {
    if (!map.has(b.group)) {
      order.push(b.group);
      map.set(b.group, []);
    }
    map.get(b.group)!.push(b);
  }
  return order.map((group) => ({ group, items: map.get(group)! }));
}

/** Convert a chord string into renderer-friendly segments
 * (`Shift+C` → `['Shift', 'C']`). The renderer wraps each segment in
 * a `<kbd>`. */
export function chordSegments(chord: string): string[] {
  return chord.split('+').map((s) => s.trim()).filter(Boolean);
}

/** Try to dispatch the event against the registry. Returns `true`
 * when a handler ran (caller already saw `preventDefault`); `false`
 * when no binding matched and the event should fall through to the
 * page's default behavior or a more-specific component handler. */
export function dispatchShortcut(e: KeyboardEvent): boolean {
  const inField = isInputFocused(e.target);
  for (const { def, req } of PARSED) {
    if (def.displayOnly || !def.run) continue;
    if (!matches(e, req)) continue;
    if (!def.global && inField) return false;
    e.preventDefault();
    def.run(e);
    return true;
  }
  return false;
}

// Test-only export — kept on the named export surface so the test
// file doesn't need a deep relative import. Underscore-prefixed to
// signal "do not import outside tests".
export const _internal = { parseChord, matches, isInputFocused };
