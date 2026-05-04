/**
 * Session sort-mode preference store — persists the user's chosen
 * sidebar sort order to ``localStorage`` so the preference survives
 * page reloads.
 *
 * Sort modes:
 *
 * - ``SESSION_SORT_LAST_ACTION`` (default) — flat list ordered by
 *   ``updated_at DESC`` (the backend's native return order).
 * - ``SESSION_SORT_GROUPED`` — sessions grouped alphabetically by
 *   tag, matching the original sidebar behaviour.
 *
 * Failure modes: ``localStorage`` access throws in private-browsing
 * contexts. Both read and write degrade silently — the in-memory
 * default (``last_action``) applies for the life of the page load.
 */
import {
  SESSION_SORT_GROUPED,
  SESSION_SORT_LAST_ACTION,
  SESSION_SORT_STORAGE_KEY,
  type SessionSortMode,
} from "../config";

// ---------------------------------------------------------------------------
// localStorage helpers (SSR-safe)
// ---------------------------------------------------------------------------

function loadSortPref(): SessionSortMode {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") {
    return SESSION_SORT_LAST_ACTION;
  }
  try {
    const raw = window.localStorage.getItem(SESSION_SORT_STORAGE_KEY);
    return raw === SESSION_SORT_GROUPED ? SESSION_SORT_GROUPED : SESSION_SORT_LAST_ACTION;
  } catch {
    return SESSION_SORT_LAST_ACTION;
  }
}

function saveSortPref(mode: SessionSortMode): void {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(SESSION_SORT_STORAGE_KEY, mode);
  } catch {
    // Quota / private-mode — degrade silently; the in-memory state still
    // reflects the user's choice for this page load.
  }
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

interface SessionSortState {
  /** Currently active sort mode. */
  mode: SessionSortMode;
}

const state: SessionSortState = $state({ mode: loadSortPref() });

/** Reactive snapshot. Read ``sessionSortStore.mode`` in ``$derived``. */
export const sessionSortStore = state;

/** Update the sort mode and persist it to ``localStorage``. */
export function setSessionSort(mode: SessionSortMode): void {
  state.mode = mode;
  saveSortPref(mode);
}

/** Test seam — resets to the default (``last_action``) without touching localStorage. */
export function _resetForTests(): void {
  state.mode = SESSION_SORT_LAST_ACTION;
}
