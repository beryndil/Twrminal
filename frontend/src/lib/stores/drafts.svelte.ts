/**
 * Per-session composer draft persistence.
 *
 * When the user types into a session's message composer and navigates
 * away (session switch, tab close, reload) without submitting, the
 * typed text survives and is restored the next time they land on that
 * session. Scope is per-session, keyed by `session_id`, stored in
 * localStorage under `bearings:draft:<session_id>`.
 *
 * Writes are debounced ~300 ms after the last keystroke so we don't
 * hammer localStorage on every input event. The debounced write is
 * flushed synchronously on `beforeunload` and when the caller switches
 * sessions, so the last few characters aren't lost on abrupt exit.
 *
 * Cleared on successful send, on session close, and on session
 * delete — matches the "note I left for myself" mental model.
 *
 * Privacy note: drafts may contain sensitive text. No encryption —
 * consistent with the existing localStorage usage and the
 * localhost-only threat model in v0.x.x. Revisit if Bearings ever
 * grows a multi-user or remote mode.
 */

const PREFIX = 'bearings:draft:';
const DEBOUNCE_MS = 300;

function readStorage(key: string): string | null {
  if (typeof localStorage === 'undefined') return null;
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null): void {
  if (typeof localStorage === 'undefined') return;
  try {
    if (value === null || value === '') localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // Quota/privacy-mode: draft won't persist across reload. The
    // in-memory composer value is unaffected.
  }
}

class DraftsStore {
  /** sessionId -> pending debounce timer. Tracked so `flush()` and
   * `clear()` can cancel an in-flight write before it clobbers a
   * just-committed change (send → clear raced by a pending write). */
  private pending = new Map<string, ReturnType<typeof setTimeout>>();

  /** sessionId -> last value scheduled but not yet flushed. Mirrors
   * the debounced write so `flush()` can commit it immediately
   * without relying on the timer. */
  private buffered = new Map<string, string>();

  /** Synchronous read of the persisted draft for a session, or `''`
   * if nothing is stored. Called on mount / session switch. */
  get(sessionId: string): string {
    const buffered = this.buffered.get(sessionId);
    if (buffered !== undefined) return buffered;
    return readStorage(PREFIX + sessionId) ?? '';
  }

  /** Schedule a debounced write of `text` for `sessionId`. Subsequent
   * calls within DEBOUNCE_MS coalesce — only the final value lands
   * in localStorage. An empty string writes through as a removal so
   * the key doesn't linger forever. */
  set(sessionId: string, text: string): void {
    this.buffered.set(sessionId, text);
    const existing = this.pending.get(sessionId);
    if (existing !== undefined) clearTimeout(existing);
    const timer = setTimeout(() => {
      this.pending.delete(sessionId);
      this.buffered.delete(sessionId);
      writeStorage(PREFIX + sessionId, text || null);
    }, DEBOUNCE_MS);
    this.pending.set(sessionId, timer);
  }

  /** Commit any pending debounced write immediately. Call on
   * beforeunload and before switching sessions so the tail end of
   * the user's typing isn't dropped. No-op if nothing is pending. */
  flush(sessionId: string): void {
    const timer = this.pending.get(sessionId);
    if (timer === undefined) return;
    clearTimeout(timer);
    this.pending.delete(sessionId);
    const text = this.buffered.get(sessionId) ?? '';
    this.buffered.delete(sessionId);
    writeStorage(PREFIX + sessionId, text || null);
  }

  /** Drop any stored draft for this session and cancel pending
   * writes. Called on successful send, session close, and session
   * delete. */
  clear(sessionId: string): void {
    const timer = this.pending.get(sessionId);
    if (timer !== undefined) {
      clearTimeout(timer);
      this.pending.delete(sessionId);
    }
    this.buffered.delete(sessionId);
    writeStorage(PREFIX + sessionId, null);
  }
}

export const drafts = new DraftsStore();
