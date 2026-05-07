/**
 * Inspector store — the single source of truth for *which* tab the
 * inspector is showing and *which* session it is reading.
 *
 * Per arch §1.2 + §2.2 the inspector is one canonical store, one file.
 * The two pieces of state live together because every consumer that
 * cares about one cares about the other: the tab strip switches which
 * subsection renders, the subsection renders against the active
 * session row. Splitting them across two stores would force every
 * subsection component to import from two places without a net win.
 *
 * Components subscribe by reading the proxy fields directly:
 *
 * ```svelte
 * import { inspectorStore } from "$lib/stores/inspector.svelte";
 * $: tab = inspectorStore.activeTabId;
 * ```
 *
 * All mutation flows through the imperative helpers below; components
 * never write into the proxy directly. That keeps the dependency graph
 * one-way (components → helpers → store) and matches the
 * tags/sessions/conversation store conventions already established in
 * items 2.2 + 2.3.
 */
import {
  DEFAULT_INSPECTOR_TAB,
  INSPECTOR_TAB_STORAGE_KEY,
  KNOWN_INSPECTOR_TABS,
  type InspectorTabId,
} from "../config";

// ---------------------------------------------------------------------------
// localStorage helpers (SSR-safe)
// ---------------------------------------------------------------------------

/**
 * Read the persisted inspector tab from ``localStorage``.
 *
 * Returns :data:`DEFAULT_INSPECTOR_TAB` when:
 *
 * - no value is stored,
 * - the stored value is not in :data:`KNOWN_INSPECTOR_TABS`, or
 * - ``localStorage`` is unavailable / throws (private-browsing, quota).
 */
function loadTabPref(): InspectorTabId {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") {
    return DEFAULT_INSPECTOR_TAB;
  }
  try {
    const raw = window.localStorage.getItem(INSPECTOR_TAB_STORAGE_KEY);
    if (raw !== null && (KNOWN_INSPECTOR_TABS as readonly string[]).includes(raw)) {
      return raw as InspectorTabId;
    }
    return DEFAULT_INSPECTOR_TAB;
  } catch {
    return DEFAULT_INSPECTOR_TAB;
  }
}

/**
 * Persist the active tab id to ``localStorage``.
 *
 * Best-effort — private-browsing / quota errors are caught and swallowed
 * so the in-memory selection still flips even when storage is unavailable.
 */
function saveTabPref(id: InspectorTabId): void {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(INSPECTOR_TAB_STORAGE_KEY, id);
  } catch {
    // Quota / private-mode — degrade silently; the in-memory state still
    // reflects the user's choice for this page load.
  }
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

interface InspectorState {
  /**
   * Currently-rendered subsection. Always one of
   * :data:`KNOWN_INSPECTOR_TABS`; a caller passing an unknown id is
   * silently ignored (defense-in-depth — a future migration that drops
   * a tab id leaves stale local-storage values harmless).
   */
  activeTabId: InspectorTabId;
  /**
   * Session id the inspector is reading. Mirrors the conversation
   * pane's selection — both are driven from the sidebar's row click in
   * ``+layout.svelte``. ``null`` means "no session selected" (boot
   * state, or every row deselected after a tag-filter change emptied
   * the list).
   */
  activeSessionId: string | null;
}

const state: InspectorState = $state({
  activeTabId: loadTabPref(),
  activeSessionId: null,
});

/**
 * Reactive proxy. Read fields off this object inside ``$derived`` /
 * template expressions; mutation is goes through :func:`setInspectorTab`
 * / :func:`setActiveSession` rather than direct field writes so the
 * lone "valid id" check stays in one place.
 */
export const inspectorStore = state;

/**
 * Switch the active subsection. Unknown ids are ignored; the existing
 * tab id stays in place. The check is structural, not throw-on-error:
 * a stale id from a removed feature flag should be a no-op rather than
 * a crash, and a typo at a call site is caught by the
 * :type:`InspectorTabId` parameter type at compile time anyway.
 */
export function setInspectorTab(id: InspectorTabId): void {
  if (!KNOWN_INSPECTOR_TABS.includes(id)) {
    return;
  }
  state.activeTabId = id;
  saveTabPref(id);
}

/**
 * Set (or clear) the inspector's active session. ``null`` clears it —
 * the inspector renders its empty state until the next selection.
 */
export function setActiveSession(sessionId: string | null): void {
  state.activeSessionId = sessionId;
}

/**
 * Test seam — re-hydrates the store from ``localStorage`` (just as the
 * module initialiser does at boot) and clears ``activeSessionId``.
 *
 * Callers should call ``window.localStorage.clear()`` **before** this to
 * start from a blank slate, or seed specific keys **before** this to
 * exercise hydration paths.
 */
export function _resetForTests(): void {
  state.activeTabId = loadTabPref();
  state.activeSessionId = null;
}
