/**
 * Context-menu keyboard FSM. Pure reducer — no DOM, no timers, no
 * stores. The renderer owns focus, DOM events, and imperative effects;
 * this module owns the decision of what should happen next.
 *
 * Covers arrow navigation (with wrap + disabled skip), Home / End,
 * Enter activation, Escape dismissal, Left / Right for submenu
 * open / close, and mnemonic jump-and-activate per plan §6.2.
 *
 * Only one submenu level is supported — the spec caps submenu nesting
 * at two levels total (root + one), and "beyond that, a dialog"
 * (non-decision from plan §11).
 */

/** Minimal per-item info the reducer needs. Handlers, labels, icons,
 * and other render-layer concerns intentionally do not appear here
 * — keeping the reducer's input surface small makes every transition
 * unit-testable without fixtures. */
export type FSMItem = {
  /** The lowercase one-character key that activates this item. */
  mnemonic?: string;
  /** True when the item is greyed-out (disabled-with-tooltip, per
   * decision §2.3). Disabled items are skipped by arrow navigation
   * and never activate. */
  disabled?: boolean;
  /** True when Enter / ArrowRight should open a submenu instead of
   * firing an activate effect. */
  hasSubmenu?: boolean;
};

/** Flat snapshot of both lists the reducer can see right now. The
 * `submenu` array is empty when no submenu is open; when it is open,
 * `state.submenuOpen` must be `true` and the renderer is responsible
 * for keeping the two in sync. */
export type ItemsSnapshot = {
  main: readonly FSMItem[];
  submenu: readonly FSMItem[];
};

export type KeyboardState = {
  /** Index into `main`. -1 when nothing is focused (freshly opened). */
  focusedIndex: number;
  /** True while a submenu is open. Implies `submenuFocusedIndex` is
   * the active focus and `focusedIndex` points at the parent item. */
  submenuOpen: boolean;
  /** Index into `submenu`. -1 when submenu is closed or nothing is
   * focused inside it yet. */
  submenuFocusedIndex: number;
};

export const INITIAL_STATE: KeyboardState = {
  focusedIndex: -1,
  submenuOpen: false,
  submenuFocusedIndex: -1
};

export type FSMEvent =
  | { type: 'ArrowUp' }
  | { type: 'ArrowDown' }
  | { type: 'ArrowLeft' }
  | { type: 'ArrowRight' }
  | { type: 'Home' }
  | { type: 'End' }
  | { type: 'Enter' }
  | { type: 'Escape' }
  | { type: 'Mnemonic'; char: string };

/** Side-effects the renderer is expected to apply after the reducer
 * updates state. Exactly one effect per transition, or none. */
export type FSMEffect =
  | { type: 'activate'; list: 'main' | 'submenu'; index: number }
  | { type: 'openSubmenu'; parentIndex: number }
  | { type: 'closeSubmenu' }
  | { type: 'close' };

export type FSMResult = {
  state: KeyboardState;
  effect?: FSMEffect;
};

/**
 * Apply `event` to `state`. The returned state always replaces the
 * input — never mutated. If the event produces no visible change,
 * the same state is returned (but no referential-identity guarantee).
 */
export function reduce(
  state: KeyboardState,
  event: FSMEvent,
  items: ItemsSnapshot
): FSMResult {
  if (state.submenuOpen) {
    return reduceSubmenu(state, event, items);
  }
  return reduceMain(state, event, items);
}

function reduceMain(
  state: KeyboardState,
  event: FSMEvent,
  items: ItemsSnapshot
): FSMResult {
  const main = items.main;
  switch (event.type) {
    case 'ArrowDown': {
      const next = advance(main, state.focusedIndex, 1);
      return { state: { ...state, focusedIndex: next } };
    }
    case 'ArrowUp': {
      const next = advance(main, state.focusedIndex, -1);
      return { state: { ...state, focusedIndex: next } };
    }
    case 'Home': {
      const next = firstFocusable(main);
      return { state: { ...state, focusedIndex: next } };
    }
    case 'End': {
      const next = lastFocusable(main);
      return { state: { ...state, focusedIndex: next } };
    }
    case 'ArrowRight': {
      const idx = state.focusedIndex;
      if (idx < 0 || idx >= main.length) return { state };
      const item = main[idx];
      if (!item || item.disabled || !item.hasSubmenu) return { state };
      return {
        state: {
          ...state,
          submenuOpen: true,
          submenuFocusedIndex: firstFocusable(items.submenu)
        },
        effect: { type: 'openSubmenu', parentIndex: idx }
      };
    }
    case 'ArrowLeft':
      // Nothing to close at the root level.
      return { state };
    case 'Enter': {
      const idx = state.focusedIndex;
      if (idx < 0 || idx >= main.length) return { state };
      const item = main[idx];
      if (!item || item.disabled) return { state };
      if (item.hasSubmenu) {
        return {
          state: {
            ...state,
            submenuOpen: true,
            submenuFocusedIndex: firstFocusable(items.submenu)
          },
          effect: { type: 'openSubmenu', parentIndex: idx }
        };
      }
      return {
        state,
        effect: { type: 'activate', list: 'main', index: idx }
      };
    }
    case 'Escape':
      return { state, effect: { type: 'close' } };
    case 'Mnemonic':
      return mnemonicJump(state, event.char, main, 'main');
  }
}

function reduceSubmenu(
  state: KeyboardState,
  event: FSMEvent,
  items: ItemsSnapshot
): FSMResult {
  const submenu = items.submenu;
  switch (event.type) {
    case 'ArrowDown': {
      const next = advance(submenu, state.submenuFocusedIndex, 1);
      return { state: { ...state, submenuFocusedIndex: next } };
    }
    case 'ArrowUp': {
      const next = advance(submenu, state.submenuFocusedIndex, -1);
      return { state: { ...state, submenuFocusedIndex: next } };
    }
    case 'Home': {
      const next = firstFocusable(submenu);
      return { state: { ...state, submenuFocusedIndex: next } };
    }
    case 'End': {
      const next = lastFocusable(submenu);
      return { state: { ...state, submenuFocusedIndex: next } };
    }
    case 'ArrowLeft':
      return {
        state: { ...state, submenuOpen: false, submenuFocusedIndex: -1 },
        effect: { type: 'closeSubmenu' }
      };
    case 'ArrowRight':
      // Max two submenu levels — no deeper nesting.
      return { state };
    case 'Enter': {
      const idx = state.submenuFocusedIndex;
      if (idx < 0 || idx >= submenu.length) return { state };
      const item = submenu[idx];
      if (!item || item.disabled || item.hasSubmenu) return { state };
      return {
        state,
        effect: { type: 'activate', list: 'submenu', index: idx }
      };
    }
    case 'Escape':
      // Escape in a submenu closes the submenu only; the root stays
      // open. A second Escape (handled via the closed-submenu branch)
      // closes the whole menu.
      return {
        state: { ...state, submenuOpen: false, submenuFocusedIndex: -1 },
        effect: { type: 'closeSubmenu' }
      };
    case 'Mnemonic':
      return mnemonicJump(state, event.char, submenu, 'submenu');
  }
}

/** Next focusable index wrapping past the ends; skips disabled. When
 * every item is disabled (or the list is empty) returns `from`. */
function advance(
  items: readonly FSMItem[],
  from: number,
  step: 1 | -1
): number {
  const n = items.length;
  if (n === 0) return -1;
  // If nothing is focused, ArrowDown seeds the first focusable and
  // ArrowUp seeds the last — matches WAI-ARIA menu pattern.
  if (from < 0) {
    return step === 1 ? firstFocusable(items) : lastFocusable(items);
  }
  let idx = from;
  for (let i = 0; i < n; i++) {
    idx = (idx + step + n) % n;
    if (!items[idx]?.disabled) return idx;
  }
  return from;
}

function firstFocusable(items: readonly FSMItem[]): number {
  for (let i = 0; i < items.length; i++) {
    if (!items[i]?.disabled) return i;
  }
  return -1;
}

function lastFocusable(items: readonly FSMItem[]): number {
  for (let i = items.length - 1; i >= 0; i--) {
    if (!items[i]?.disabled) return i;
  }
  return -1;
}

/**
 * Mnemonic resolution.
 *
 *   - 0 matches     → no-op.
 *   - 1 match       → focus + activate (or open submenu on hasSubmenu).
 *   - 2+ matches    → cycle focus; never auto-activate.
 *
 * This matches native-menu behavior where a unique letter fires the
 * action but ambiguous letters just move focus.
 */
function mnemonicJump(
  state: KeyboardState,
  rawChar: string,
  items: readonly FSMItem[],
  list: 'main' | 'submenu'
): FSMResult {
  const char = rawChar.toLowerCase();
  const matches: number[] = [];
  for (let i = 0; i < items.length; i++) {
    const m = items[i]?.mnemonic?.toLowerCase();
    if (m === char && !items[i]?.disabled) matches.push(i);
  }
  if (matches.length === 0) return { state };
  if (matches.length === 1) {
    const target = matches[0]!;
    const item = items[target]!;
    const nextState =
      list === 'main'
        ? { ...state, focusedIndex: target }
        : { ...state, submenuFocusedIndex: target };
    if (item.hasSubmenu && list === 'main') {
      return {
        state: {
          ...nextState,
          submenuOpen: true,
          submenuFocusedIndex: -1
        },
        effect: { type: 'openSubmenu', parentIndex: target }
      };
    }
    return {
      state: nextState,
      effect: { type: 'activate', list, index: target }
    };
  }
  // Cycle: find the next match strictly after the current focus.
  const current =
    list === 'main' ? state.focusedIndex : state.submenuFocusedIndex;
  const next =
    matches.find((m) => m > current) ?? matches[0]!;
  const nextState =
    list === 'main'
      ? { ...state, focusedIndex: next }
      : { ...state, submenuFocusedIndex: next };
  return { state: nextState };
}
