/**
 * Shell-style input history for session composers.
 *
 * Given an ordered list of previously-submitted prompts (oldest→newest),
 * the helper state machine tracks which history entry the user is
 * currently viewing and stashes the in-progress draft so pressing Down
 * past the newest entry restores it.
 *
 * Pure functions over a plain-object state — state lives in the calling
 * Svelte component so reactivity stays under the component's control.
 * That also means the helper is trivially unit-testable without a DOM.
 *
 * Semantics match bash/readline:
 *   - Up from not-walking: stash the current draft, jump to the newest
 *     history entry.
 *   - Up repeatedly: walk backwards through history. Stops at oldest
 *     (no wrap).
 *   - Down: walk forward. Past the newest entry, exit history mode and
 *     restore the stashed draft.
 *   - Down when not walking: no-op; caller can fall through to normal
 *     caret behavior.
 */

export type HistoryState = {
  /** Pointer into `entries` or null when not walking history. */
  index: number | null;
  /** Text the user was editing before they started walking. Only
   * populated when `index !== null`. Restored on Down past newest. */
  stashedDraft: string;
};

/** Fresh state — not walking, no stash. */
export function emptyHistoryState(): HistoryState {
  return { index: null, stashedDraft: '' };
}

/** Reset to not-walking. Called on successful send, on session switch,
 * and when the user types a character (so a subsequent Up stashes the
 * edited text as the new baseline). */
export function resetHistory(state: HistoryState): HistoryState {
  if (state.index === null && state.stashedDraft === '') return state;
  return emptyHistoryState();
}

/** Walk one step older. Returns the updated state and the text the
 * composer should now show. If `entries` is empty, a no-op signalled by
 * `changed: false`; the caller should fall through so Up behaves like a
 * normal caret movement when there's nothing to show. The first Up also
 * stashes `currentDraft` so Down-past-newest can restore it. */
export function prevHistory(
  state: HistoryState,
  entries: readonly string[],
  currentDraft: string
): { state: HistoryState; text: string; changed: boolean } {
  if (entries.length === 0) {
    return { state, text: currentDraft, changed: false };
  }
  if (state.index === null) {
    const newest = entries.length - 1;
    return {
      state: { index: newest, stashedDraft: currentDraft },
      text: entries[newest],
      changed: true
    };
  }
  if (state.index === 0) {
    // Already at oldest — stay put. Still "changed: true" so the
    // caller consumes the key event instead of letting the caret
    // bounce around.
    return { state, text: entries[0], changed: true };
  }
  const nextIndex = state.index - 1;
  return {
    state: { ...state, index: nextIndex },
    text: entries[nextIndex],
    changed: true
  };
}

/** Walk one step newer. If not currently walking history, returns
 * `changed: false` so the caller can fall through to normal caret
 * behavior. Past the newest entry, exits history mode and restores
 * the stashed draft. */
export function nextHistory(
  state: HistoryState,
  entries: readonly string[]
): { state: HistoryState; text: string; changed: boolean } {
  if (state.index === null) {
    return { state, text: '', changed: false };
  }
  if (state.index >= entries.length - 1) {
    // Past newest → restore the stash and exit history mode.
    const restored = state.stashedDraft;
    return { state: emptyHistoryState(), text: restored, changed: true };
  }
  const nextIndex = state.index + 1;
  return {
    state: { ...state, index: nextIndex },
    text: entries[nextIndex],
    changed: true
  };
}

/** True when a textarea's caret is on the first visual line AND the
 * user has no active selection — the condition under which Up should
 * trigger history instead of normal caret movement. Mirroring shell
 * behavior: "if there's no way to usefully move the caret up, use it
 * as a history key." */
export function caretOnFirstLine(
  value: string,
  selectionStart: number,
  selectionEnd: number
): boolean {
  if (selectionStart !== selectionEnd) return false;
  // `slice(0, start).includes('\n')` is O(n) in draft length. Drafts
  // are rarely huge and this only runs on ArrowUp, so the naive check
  // is fine.
  return !value.slice(0, selectionStart).includes('\n');
}

/** Symmetric to `caretOnFirstLine` — true when the caret is on the
 * last visual line with no selection. */
export function caretOnLastLine(
  value: string,
  selectionStart: number,
  selectionEnd: number
): boolean {
  if (selectionStart !== selectionEnd) return false;
  return !value.slice(selectionEnd).includes('\n');
}
