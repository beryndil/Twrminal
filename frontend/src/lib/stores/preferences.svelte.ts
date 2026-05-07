/**
 * Preferences store — caches the singleton user-preferences row so the
 * sidebar identity block stays in sync with the Profile settings section
 * without issuing redundant requests (gap-cycle-08-002).
 *
 * Observable behavior: ``docs/behavior/preferences.md``
 * §"Profile / Identity".
 *
 * Usage:
 * - The layout shell calls :func:`refreshPreferences` on mount.
 * - The Profile settings section calls :func:`applyPreferences` after
 *   every mutation (save display name, upload/remove avatar, sync from
 *   system) with the already-fetched response body — avoids a redundant
 *   GET and keeps the sidebar update instantaneous.
 *
 * Failure mode: if the initial GET fails, the store retains its null
 * values; the sidebar shows the fallback name and silhouette SVG.
 */
import { getPreferences, type PreferencesOut } from "../api/preferences";

interface PreferencesState {
  /** ``null`` when not yet loaded or when the user has no display name set. */
  displayName: string | null;
  /** ``/api/preferences/avatar`` path, or ``null`` when no avatar is stored. */
  avatarUrl: string | null;
  /**
   * ``updated_at`` timestamp appended as ``?v=<cacheBust>`` to the avatar URL
   * to invalidate the browser's HTTP cache after an upload.  Empty string
   * when not yet loaded.
   */
  cacheBust: string;
}

const state: PreferencesState = $state({
  displayName: null,
  avatarUrl: null,
  cacheBust: "",
});

/**
 * Reactive preferences snapshot.
 *
 * Read ``preferencesStore.displayName`` / ``preferencesStore.avatarUrl``
 * inside ``$derived`` or plain functions called from reactive contexts.
 * Mutate only via :func:`refreshPreferences` or :func:`applyPreferences` —
 * direct writes skip the API round-trip and the cache-bust logic.
 */
export const preferencesStore: PreferencesState = state;

/**
 * Fetch the current preferences from ``GET /api/preferences`` and update the
 * store.
 *
 * Safe to call concurrently — last-write-wins (the row is a singleton).
 * Silently ignores network and auth errors so the sidebar degrades
 * gracefully to the fallback name / silhouette icon rather than throwing.
 */
export async function refreshPreferences(): Promise<void> {
  try {
    applyPreferences(await getPreferences());
  } catch {
    // Silently degrade — sidebar shows fallback name / silhouette SVG.
  }
}

/**
 * Apply a freshly-fetched preferences row to the store.
 *
 * Call this after any mutation that returns an updated ``PreferencesOut``
 * (e.g. ``patchPreferences``, ``uploadAvatar``, ``deleteAvatar``,
 * ``syncFromSystem``) to propagate changes to the sidebar identity block
 * without an extra round-trip.
 */
export function applyPreferences(prefs: PreferencesOut): void {
  state.displayName = prefs.display_name;
  state.avatarUrl = prefs.avatar_url;
  state.cacheBust = prefs.updated_at;
}

// ---------------------------------------------------------------------------
// Test seam
// ---------------------------------------------------------------------------

/**
 * Reset store to initial empty state.
 *
 * Call in ``beforeEach`` alongside the store reset for any other stores
 * touched in the test file.
 */
export function _resetForTests(): void {
  state.displayName = null;
  state.avatarUrl = null;
  state.cacheBust = "";
}
