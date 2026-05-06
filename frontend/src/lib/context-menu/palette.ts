/**
 * Command-palette action registry.
 *
 * Two responsibilities:
 *
 * 1. **Static entry list** — :func:`allPaletteActions` returns every
 *    action from the context-menu registry (:mod:`registry`) as a flat,
 *    deduplicated list with human-readable labels sourced from
 *    :data:`CONTEXT_MENU_STRINGS.actionLabels`. This drives the palette
 *    display and fuzzy filter.
 *
 * 2. **Global handler registry** — components that want their
 *    context-menu actions to be directly activatable from the palette
 *    call :func:`registerPaletteHandler`. The palette invokes the
 *    handler on Enter. Registration uses the same "most-recently-mounted
 *    wins" convention as :func:`bindHandler` in
 *    :mod:`keyboard/store.svelte`.
 *
 * Behavior anchor: ``docs/behavior/keyboard-shortcuts.md``
 * §"Command palette".
 */
import { CONTEXT_MENU_STRINGS } from "../config";
import { MENU_ACTIONS_BY_TARGET } from "./registry";

/** A single entry shown in the command palette. */
export interface PaletteEntry {
  /** Context-menu action id. Stable and public. */
  readonly id: string;
  /** Human-readable label from :data:`CONTEXT_MENU_STRINGS.actionLabels`. */
  readonly label: string;
}

/**
 * Return every action from the context-menu registry as a flat,
 * deduplicated list in registry-insertion order.
 *
 * Actions that appear in multiple per-target lists (e.g.
 * ``MENU_ACTION_LINK_OPEN_IN_EDITOR``) are included only once — the
 * first occurrence wins.
 */
export function allPaletteActions(): readonly PaletteEntry[] {
  const seen = new Set<string>();
  const entries: PaletteEntry[] = [];
  const labels = CONTEXT_MENU_STRINGS.actionLabels as Record<string, string>;
  for (const actions of Object.values(MENU_ACTIONS_BY_TARGET)) {
    for (const action of actions) {
      if (!seen.has(action.id)) {
        seen.add(action.id);
        const label = labels[action.id];
        if (label !== undefined) {
          entries.push({ id: action.id, label });
        }
      }
    }
  }
  return entries;
}

// ---------------------------------------------------------------------------
// Global palette handler map
// ---------------------------------------------------------------------------

/**
 * Map from action id to the currently registered palette handler.
 * Entries are absent when no component has registered a handler for
 * that action id, or after the registering component has unmounted.
 */
const _paletteHandlers = new Map<string, () => void>();

/**
 * Register a handler that the command palette will call when the user
 * activates the given action id. Returns a cleanup function to
 * unregister on component teardown.
 *
 * Re-registering an id replaces the previous handler — the
 * most-recently-mounted component wins, matching the
 * :func:`bindHandler` convention.
 */
export function registerPaletteHandler(id: string, handler: () => void): () => void {
  const previous = _paletteHandlers.get(id);
  _paletteHandlers.set(id, handler);
  return () => {
    if (_paletteHandlers.get(id) === handler) {
      if (previous !== undefined) {
        _paletteHandlers.set(id, previous);
      } else {
        _paletteHandlers.delete(id);
      }
    }
  };
}

/** Look up a registered palette handler. Returns ``undefined`` when unbound. */
export function getPaletteHandler(id: string): (() => void) | undefined {
  return _paletteHandlers.get(id);
}

/** Test seam — clears all registered palette handlers. */
export function _resetPaletteHandlers(): void {
  _paletteHandlers.clear();
}
