/**
 * General-purpose undo store — tracks reversible destructive context-menu
 * actions and surfaces them as a transient bottom-right toast
 * (``UndoToast.svelte``).
 *
 * Behavior anchor: ``docs/behavior/context-menus.md``
 * §"Common behavior — Toast feedback" — "Destructive completions show an
 * undo toast for a few seconds: clicking it reverses the action when the
 * operation is reversible (close, archive, detach), or restores from a
 * soft-delete buffer (delete) when supported by the target."
 *
 * Design:
 * - Stack cap = 3 (v17 parity). The oldest entry is evicted when a fourth
 *   push arrives so the queue never grows unbounded.
 * - Default auto-dismiss window = 5 000 ms ("a few seconds").
 * - The ``UndoToast`` renders only index 0 (most-recent entry). The rest
 *   wait in the stack and surface one by one as each is dismissed.
 * - Pushing a new entry restarts the auto-dismiss timer for the new top.
 *
 * This store is intentionally independent of ``ReorgUndoToast`` /
 * ``reorgStore``; the two operate in different UI domains and must NOT
 * share state.
 */

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/** One reversible action kept in the stack. */
export interface UndoEntry {
  /** Client-generated id for keying and targeted dismissal. */
  id: string;
  /** Human-readable label shown in the toast (e.g. "Session archived"). */
  message: string;
  /** Called when the user clicks Undo. May return a Promise. */
  inverse: () => void | Promise<void>;
  /** Auto-dismiss window in ms. Set from ``PushParams.windowMs`` or the default. */
  windowMs: number;
}

/** Parameters for :func:`undoStore.push`. */
export interface PushParams {
  message: string;
  inverse: () => void | Promise<void>;
  /** Defaults to ``DEFAULT_UNDO_WINDOW_MS`` when omitted. */
  windowMs?: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Maximum number of entries kept in the stack simultaneously. */
export const UNDO_STACK_CAP = 3;

/** Default auto-dismiss window in milliseconds. */
export const DEFAULT_UNDO_WINDOW_MS = 5_000;

// ---------------------------------------------------------------------------
// Module-level reactive state (Svelte 5 runes)
// ---------------------------------------------------------------------------

/** Ordered stack — index 0 is the most-recent entry (shown in the toast). */
let _stack = $state<UndoEntry[]>([]);

/** Handle for the auto-dismiss timer of the current top entry. */
let _timer: ReturnType<typeof setTimeout> | null = null;

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function makeId(): string {
  return Math.random().toString(36).slice(2, 10);
}

function clearTimer(): void {
  if (_timer !== null) {
    clearTimeout(_timer);
    _timer = null;
  }
}

function startTimerForTop(): void {
  clearTimer();
  const top = _stack[0];
  if (top === undefined) return;
  _timer = setTimeout(() => {
    dismissEntry(top.id);
  }, top.windowMs);
}

function dismissEntry(id: string): void {
  clearTimer();
  _stack = _stack.filter((e) => e.id !== id);
  if (_stack.length > 0) {
    startTimerForTop();
  }
}

// ---------------------------------------------------------------------------
// Public store object
// ---------------------------------------------------------------------------

export const undoStore = {
  /**
   * Reactive stack of pending undo entries. Index 0 = most-recent (shown
   * in the toast). Read-only from outside the module.
   */
  get stack(): readonly UndoEntry[] {
    return _stack;
  },

  /**
   * Push a new reversible action onto the undo stack.
   *
   * If the stack is already at :const:`UNDO_STACK_CAP` the oldest entry
   * (highest index) is evicted to keep the stack bounded. The new entry
   * becomes index 0 and its auto-dismiss timer starts immediately.
   */
  push(params: PushParams): void {
    const entry: UndoEntry = {
      id: makeId(),
      message: params.message,
      inverse: params.inverse,
      windowMs: params.windowMs ?? DEFAULT_UNDO_WINDOW_MS,
    };
    // Trim to cap-1 before prepending so we never exceed the cap.
    const trimmed =
      _stack.length >= UNDO_STACK_CAP ? _stack.slice(0, UNDO_STACK_CAP - 1) : _stack;
    _stack = [entry, ...trimmed];
    startTimerForTop();
  },

  /**
   * Dismiss the entry with the given ``id`` (called by the Dismiss button
   * or after a successful ``inverse()`` call).
   */
  dismiss(id: string): void {
    dismissEntry(id);
  },
} as const;

// ---------------------------------------------------------------------------
// Test helper — NOT part of the public API
// ---------------------------------------------------------------------------

/**
 * Reset all store state and cancel pending timers.
 * Call in ``beforeEach`` when unit-testing this module.
 */
export function _resetForTests(): void {
  clearTimer();
  _stack = [];
}
