/**
 * Static binding table for v1 — every chord listed in
 * ``docs/behavior/keyboard-shortcuts.md`` §"Bindings (v1)" maps to one
 * action id. This file is the single source of truth for the cheat
 * sheet (which renders the array verbatim) and the dispatcher (which
 * indexes the array by chord key).
 *
 * Adding a binding means:
 *
 * 1. Add the action-id constant in :mod:`config.ts`.
 * 2. Append a :type:`KeybindingSpec` here referencing it.
 * 3. Bind a handler at the consumer mount site via :func:`bindHandler`.
 *
 * The order of the array drives the cheat-sheet display order — the
 * cheat sheet groups by ``section`` and renders within each group in
 * insertion order.
 */
import {
  KEYBINDING_ACTION_ESC_CASCADE,
  KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH,
  KEYBINDING_ACTION_NEW_CHAT_BARE,
  KEYBINDING_ACTION_NEW_CHAT_DEFAULTS,
  KEYBINDING_ACTION_SIDEBAR_DOWN,
  KEYBINDING_ACTION_SIDEBAR_DOWN_FORCE,
  KEYBINDING_ACTION_SIDEBAR_JUMP_PREFIX,
  KEYBINDING_ACTION_SIDEBAR_UP,
  KEYBINDING_ACTION_SIDEBAR_UP_FORCE,
  KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET,
  KEYBINDING_ACTION_TOGGLE_COMMAND_PALETTE,
  KEYBINDING_SECTION_COMMAND_PALETTE,
  KEYBINDING_SECTION_CREATE,
  KEYBINDING_SECTION_FOCUS,
  KEYBINDING_SECTION_HELP,
  KEYBINDING_SECTION_NAVIGATE,
} from "../config";
import { type ChordSpec } from "./chord";

type KeybindingSectionId =
  | typeof KEYBINDING_SECTION_CREATE
  | typeof KEYBINDING_SECTION_NAVIGATE
  | typeof KEYBINDING_SECTION_FOCUS
  | typeof KEYBINDING_SECTION_HELP
  | typeof KEYBINDING_SECTION_COMMAND_PALETTE;

export interface KeybindingSpec {
  /** Action id — looked up by :func:`bindHandler`. */
  readonly id: string;
  /** Chord description (matches against keyboard events). */
  readonly chord: ChordSpec;
  /** Cheat-sheet section. */
  readonly section: KeybindingSectionId;
  /**
   * Fires even with focus inside an input or with a modal open.
   * Bare-letter chords have ``global: false``; modifier chords
   * (Alt+/Ctrl+) have ``global: true`` per the doc §"Conflict
   * resolution" §"``global: true`` bindings vs input focus".
   */
  readonly global: boolean;
  /**
   * Display-only — the chord is wired by a colocated component (e.g.
   * ``Ctrl+K`` lives on the sidebar search). The cheat sheet shows it
   * for discoverability; the global dispatcher does NOT consume it.
   */
  readonly displayOnly?: boolean;
}

/**
 * Generate the nine ``Alt+1`` … ``Alt+9`` slot-jump bindings. Each
 * binding's action id encodes the slot number so the consumer can
 * register a single ``handleSlotJump(n)`` handler at mount time.
 */
function makeSlotJumpBindings(): readonly KeybindingSpec[] {
  const specs: KeybindingSpec[] = [];
  for (let n = 1; n <= 9; n += 1) {
    specs.push({
      id: `${KEYBINDING_ACTION_SIDEBAR_JUMP_PREFIX}${n}`,
      chord: {
        code: `Digit${n}`,
        alt: true,
        display: ["Alt", `${n}`],
      },
      section: KEYBINDING_SECTION_NAVIGATE,
      global: true,
    });
  }
  return specs;
}

/**
 * The v1 binding table. Each chord appears exactly once; duplicates
 * are caught at boot by :func:`installKeybindings` per the doc
 * §"Conflict resolution".
 */
export const KEYBINDINGS: readonly KeybindingSpec[] = [
  // ---- Create ------------------------------------------------------
  {
    id: KEYBINDING_ACTION_NEW_CHAT_DEFAULTS,
    chord: { code: "KeyC", display: ["C"] },
    section: KEYBINDING_SECTION_CREATE,
    global: false,
  },
  {
    id: KEYBINDING_ACTION_NEW_CHAT_BARE,
    chord: { code: "KeyC", shift: true, display: ["Shift", "C"] },
    section: KEYBINDING_SECTION_CREATE,
    global: false,
  },
  // ---- Navigate (sidebar) ------------------------------------------
  {
    id: KEYBINDING_ACTION_SIDEBAR_DOWN,
    chord: { code: "KeyJ", display: ["J"] },
    section: KEYBINDING_SECTION_NAVIGATE,
    global: false,
  },
  {
    id: KEYBINDING_ACTION_SIDEBAR_UP,
    chord: { code: "KeyK", display: ["K"] },
    section: KEYBINDING_SECTION_NAVIGATE,
    global: false,
  },
  {
    id: KEYBINDING_ACTION_SIDEBAR_DOWN_FORCE,
    chord: { key: "]", alt: true, display: ["Alt", "]"] },
    section: KEYBINDING_SECTION_NAVIGATE,
    global: true,
  },
  {
    id: KEYBINDING_ACTION_SIDEBAR_UP_FORCE,
    chord: { key: "[", alt: true, display: ["Alt", "["] },
    section: KEYBINDING_SECTION_NAVIGATE,
    global: true,
  },
  ...makeSlotJumpBindings(),
  // ---- Focus -------------------------------------------------------
  {
    id: KEYBINDING_ACTION_ESC_CASCADE,
    chord: { key: "Escape", display: ["Esc"] },
    section: KEYBINDING_SECTION_FOCUS,
    global: true,
  },
  // ---- Help --------------------------------------------------------
  {
    // No ``shift: true`` on the chord — ``?`` is the produced character;
    // the dispatcher's named-key fallback probes shift-agnostic so a
    // layout where ``?`` is not behind Shift still matches per the
    // doc §"Conflict resolution" §"Non-US keyboard layouts".
    id: KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET,
    chord: { key: "?", display: ["?"] },
    section: KEYBINDING_SECTION_HELP,
    global: false,
  },
  // ---- Command palette ---------------------------------------------
  {
    id: KEYBINDING_ACTION_TOGGLE_COMMAND_PALETTE,
    chord: { code: "KeyP", ctrl: true, shift: true, display: ["Ctrl", "Shift", "P"] },
    section: KEYBINDING_SECTION_COMMAND_PALETTE,
    global: true,
  },
  {
    id: KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH,
    chord: { code: "KeyK", ctrl: true, display: ["Ctrl", "K"] },
    section: KEYBINDING_SECTION_COMMAND_PALETTE,
    global: true,
  },
];

/**
 * Order in which the cheat sheet renders sections. Mirrors the
 * subheading order in the behavior doc §"Bindings (v1)".
 */
export const KEYBINDING_SECTION_ORDER: readonly KeybindingSectionId[] = [
  KEYBINDING_SECTION_CREATE,
  KEYBINDING_SECTION_NAVIGATE,
  KEYBINDING_SECTION_FOCUS,
  KEYBINDING_SECTION_HELP,
  KEYBINDING_SECTION_COMMAND_PALETTE,
] as const;
