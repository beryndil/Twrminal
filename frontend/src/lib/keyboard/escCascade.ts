/**
 * Esc-cascade registry — the priority-ordered list of overlays Esc
 * dismisses.
 *
 * Priorities (per ``docs/behavior/keyboard-shortcuts.md`` §"Focus"):
 *
 * 1. Context menu
 * 2. Command palette
 * 3. Pending-operations floating card
 * 4. Other overlays (cheat sheet, modals, dropdowns)
 * 5. Blur a focused input / textarea / contenteditable
 * 6. No-op
 *
 * Each overlay registers an entry with its priority + ``isOpen`` /
 * ``close`` callbacks. The cascade walks ascending priority, fires
 * the first matching ``close``, and stops. If no overlay is open,
 * the cascade blurs the active element when it owns one.
 *
 * Numeric priorities live in :data:`ESC_PRIORITY_*` constants so a
 * future overlay slots in by name rather than magic number.
 */

export const ESC_PRIORITY_CONTEXT_MENU = 1;
export const ESC_PRIORITY_COMMAND_PALETTE = 2;
export const ESC_PRIORITY_PENDING_OPS_CARD = 3;
export const ESC_PRIORITY_OVERLAY = 4;
/** Multi-select — cleared after overlays, before the input-blur step. */
export const ESC_PRIORITY_MULTI_SELECT = 5;

interface EscEntry {
  readonly priority: number;
  readonly isOpen: () => boolean;
  readonly close: () => void;
}

const entries: EscEntry[] = [];

/**
 * Register an Esc cascade entry. Returns a cleanup function the
 * caller invokes on teardown.
 */
export function registerEscEntry(entry: EscEntry): () => void {
  entries.push(entry);
  return () => {
    const idx = entries.indexOf(entry);
    if (idx >= 0) {
      entries.splice(idx, 1);
    }
  };
}

/**
 * Run the cascade. Returns the priority that fired (>=1), ``"blur"``
 * when an input was blurred, or ``"noop"`` when nothing happened.
 *
 * Called from the dispatch layer when ``KEYBINDING_ACTION_ESC_CASCADE``
 * is registered to it.
 */
export function runEscCascade(): "noop" | "blur" | number {
  const sorted = entries.slice().sort((a, b) => a.priority - b.priority);
  for (const entry of sorted) {
    if (entry.isOpen()) {
      entry.close();
      return entry.priority;
    }
  }
  if (typeof document !== "undefined") {
    const active = document.activeElement;
    if (active instanceof HTMLElement && isBlurrableInput(active)) {
      active.blur();
      return "blur";
    }
  }
  return "noop";
}

function isBlurrableInput(el: HTMLElement): boolean {
  if (el instanceof HTMLInputElement) return true;
  if (el instanceof HTMLTextAreaElement) return true;
  if (el instanceof HTMLSelectElement) return true;
  return el.isContentEditable;
}

/** Test seam — drop every registered entry. */
export function _resetForTests(): void {
  entries.length = 0;
}
