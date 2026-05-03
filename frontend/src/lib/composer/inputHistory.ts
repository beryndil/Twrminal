/**
 * Input history walker — Up/Down navigation through the user's prior
 * sent messages, shell-readline style.
 *
 * Usage contract:
 *
 * 1. Call :func:`InputHistory.push` immediately after a message is
 *    sent successfully to record it.
 * 2. On ``ArrowUp`` (cursor at position 0): call :func:`up` with the
 *    current textarea text. Write the returned string back to the
 *    textarea and move the cursor to its end. When ``up`` returns
 *    ``null`` the history is empty — let the browser handle the key.
 * 3. On ``ArrowDown`` (cursor at end): call :func:`down`. Write the
 *    returned string back to the textarea.
 * 4. On session switch, call :func:`reset` to clear the in-memory
 *    ring and the cursor — history is per-page-load, not cross-session.
 *
 * Design notes:
 *
 * - History is in-memory only. Cross-session recall is handled by
 *   the backend message list; reading it on every session switch would
 *   be expensive. The walker gives "recall recent messages sent this
 *   page load" which matches v0.17.x convention.
 * - Consecutive identical sends are deduplicated — pressing Enter
 *   twice on the same string produces one history entry.
 * - The walker stores the live draft on the first ``ArrowUp`` press
 *   and restores it when ``ArrowDown`` is pressed past the newest
 *   entry so the user's in-progress text is never discarded.
 */

export class InputHistory {
  /** Sent messages in chronological order (oldest at index 0). */
  private readonly entries: string[] = [];

  /**
   * Current navigation position.
   *
   * ``-1`` means "not in history mode" (live input).
   * ``entries.length - 1`` is the most-recently-sent message.
   * ``0`` is the oldest retained message.
   */
  private cursor = -1;

  /**
   * The textarea text that was present when the user first pressed
   * ``ArrowUp``. Restored by :func:`down` when the cursor passes the
   * newest entry back toward live input.
   */
  private savedDraft = "";

  // ---------------------------------------------------------------------------
  // Mutation
  // ---------------------------------------------------------------------------

  /**
   * Record a sent message.
   *
   * Trims trailing/leading whitespace before storing.  Consecutive
   * identical trimmed values produce only one entry (dedup).  Empty
   * strings are ignored.  Resets the cursor to ``-1`` so the next
   * ``ArrowUp`` always starts from the most-recently-sent entry.
   */
  push(text: string): void {
    const trimmed = text.trim();
    if (trimmed === "") return;
    // Dedup: skip if the previous entry is identical.
    if (this.entries.length > 0 && this.entries[this.entries.length - 1] === trimmed) {
      this.cursor = -1;
      return;
    }
    this.entries.push(trimmed);
    this.cursor = -1;
  }

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  /**
   * Move one step back in history (towards older messages).
   *
   * ``currentDraft`` is the text currently in the textarea.  It is
   * saved on the **first** ``ArrowUp`` press (when ``cursor === -1``)
   * so :func:`down` can restore it when the user navigates back to
   * the live input position.
   *
   * Returns the text to write into the textarea, or ``null`` when the
   * history ring is empty (the caller should let the browser handle
   * the key event rather than preventing default).
   */
  up(currentDraft: string): string | null {
    if (this.entries.length === 0) return null;
    if (this.cursor === -1) {
      // Entering history for the first time — save the live draft.
      this.savedDraft = currentDraft;
      this.cursor = this.entries.length - 1;
    } else if (this.cursor > 0) {
      this.cursor -= 1;
    }
    // Already at the oldest entry: clamp and return it (no no-op).
    return this.entries[this.cursor];
  }

  /**
   * Move one step forward in history (towards the live input).
   *
   * Once past the newest entry, restores ``savedDraft`` and resets
   * the cursor to ``-1``.  Always returns a string — the caller does
   * not need a null-check before writing to the textarea.
   */
  down(): string {
    if (this.cursor === -1) {
      // Already in live-input mode; nothing to advance.
      return this.savedDraft;
    }
    if (this.cursor < this.entries.length - 1) {
      this.cursor += 1;
      return this.entries[this.cursor];
    }
    // Past the newest entry — restore the live draft and clear the
    // saved slot so subsequent down() calls after exit return "".
    const restored = this.savedDraft;
    this.cursor = -1;
    this.savedDraft = "";
    return restored;
  }

  // ---------------------------------------------------------------------------
  // State queries
  // ---------------------------------------------------------------------------

  /** ``true`` when the walker is currently navigating history (cursor ≥ 0). */
  get inHistory(): boolean {
    return this.cursor !== -1;
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  /**
   * Reset the walker without clearing the entry ring.
   *
   * Called on session switch: the in-memory ring is per-page-load, but
   * the cursor and savedDraft are per-navigation-gesture and should
   * not bleed across sessions.
   */
  reset(): void {
    this.cursor = -1;
    this.savedDraft = "";
  }

  /**
   * Fully clear the history ring and reset the cursor.
   *
   * Not called in normal operation (history accumulates for the page
   * lifetime), but useful in tests.
   */
  clear(): void {
    this.entries.length = 0;
    this.cursor = -1;
    this.savedDraft = "";
  }
}
