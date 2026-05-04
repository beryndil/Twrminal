/**
 * Multi-selection store — tracks the set of session IDs currently
 * selected in the sidebar via shift-click / ctrl-click / checkbox.
 *
 * Consumers:
 *
 * - :class:`SessionList.svelte` — owns selection logic (range-select,
 *   clear-on-Esc, selection bar) and wires the multi-select context
 *   menu handlers.
 * - :class:`SessionRow.svelte` — reads ``ids`` to know whether the
 *   row is in the current selection so it can swap the context-menu
 *   target to ``MENU_TARGET_MULTI_SELECT``.
 *
 * Mutation functions are intentionally imperative so that the caller
 * can make atomic changes without exposing internal state.
 */

interface MultiSelectionState {
  /** Set of session IDs currently selected. Read-only externally. */
  ids: ReadonlySet<string>;
}

const state: MultiSelectionState = $state({ ids: new Set<string>() });

/** Reactive snapshot. Read ``multiSelectionStore.ids`` in ``$derived``. */
export const multiSelectionStore = state;

/** Flip a single session ID in or out of the selection. */
export function toggleId(sessionId: string): void {
  const next = new Set(state.ids);
  if (next.has(sessionId)) {
    next.delete(sessionId);
  } else {
    next.add(sessionId);
  }
  state.ids = next;
}

/** Replace the selection with an exact set of IDs (used for range-select). */
export function setIds(ids: Iterable<string>): void {
  state.ids = new Set(ids);
}

/** Empty the selection. */
export function clearSelection(): void {
  if (state.ids.size === 0) return;
  state.ids = new Set<string>();
}

/** Test seam — resets to empty state. */
export function _resetForTests(): void {
  state.ids = new Set<string>();
}
