/**
 * Per-session draft persistence — syncs the composer's in-flight draft
 * to ``localStorage`` so switching sessions doesn't discard unsent text.
 *
 * Key schema: ``${COMPOSER_DRAFT_KEY_PREFIX}${sessionId}`` — see
 * :data:`config.COMPOSER_DRAFT_KEY_PREFIX` for the namespace rationale.
 *
 * Storage format: plain UTF-8 string (no JSON wrapper — the draft is
 * always a plain string; serialising through JSON adds noise with no
 * benefit). An absent key and an empty string are treated as equivalent.
 *
 * Failure modes: ``localStorage`` access throws in private-browsing
 * contexts and when storage is full. Both paths degrade silently —
 * the draft simply isn't persisted this session. The composer retains
 * the draft in ``$state`` for the life of the component regardless, so
 * the user never loses an in-flight message before they navigate away.
 */
import { COMPOSER_DRAFT_KEY_PREFIX } from "../config";

// ---------------------------------------------------------------------------
// Key helper
// ---------------------------------------------------------------------------

function draftKey(sessionId: string): string {
  return `${COMPOSER_DRAFT_KEY_PREFIX}${sessionId}`;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Read the persisted draft for ``sessionId``.
 *
 * Returns an empty string when:
 * - no draft has been saved for this session;
 * - ``localStorage`` is inaccessible (private mode / SSR).
 */
export function loadDraft(sessionId: string): string {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") {
    return "";
  }
  try {
    return window.localStorage.getItem(draftKey(sessionId)) ?? "";
  } catch {
    // Private-browsing or quota error — degrade silently.
    return "";
  }
}

/**
 * Write the current draft for ``sessionId``.
 *
 * Passing an empty string removes the key so stale empty entries
 * don't accumulate in ``localStorage``.
 */
export function saveDraft(sessionId: string, value: string): void {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") {
    return;
  }
  try {
    if (value === "") {
      window.localStorage.removeItem(draftKey(sessionId));
    } else {
      window.localStorage.setItem(draftKey(sessionId), value);
    }
  } catch {
    // Storage-full or security error — degrade silently.
  }
}

/**
 * Remove the persisted draft for ``sessionId``.
 *
 * Called by the composer after a successful 202 send so the draft
 * slot doesn't linger and the next session-open starts clean.
 */
export function clearDraft(sessionId: string): void {
  saveDraft(sessionId, "");
}
