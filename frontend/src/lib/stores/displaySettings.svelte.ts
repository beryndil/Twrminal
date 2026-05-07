/**
 * Display-settings store — persists per-device display preferences to
 * ``localStorage``. Currently manages the display timezone
 * (gap-cycle-07-006).
 *
 * **Timezone key:** ``bearings:display:timezone`` — stores a valid IANA
 * timezone string (e.g. ``"America/New_York"``). Absence means "Auto"
 * (browser default). ``null`` in the store == "Auto"; the stored value is
 * removed rather than written to a sentinel so the absence convention
 * stays clean.
 *
 * This preference is intentionally NOT round-tripped to
 * ``/api/preferences`` — a laptop in CT and a phone abroad each need their
 * own display timezone independently of the user account.
 *
 * Failure modes: ``localStorage`` access throws in private-browsing
 * contexts. Both read and write degrade silently — in-memory null (Auto)
 * applies for the life of the page load.
 */
import {
  DISPLAY_TIMEZONE_STORAGE_KEY,
  KNOWN_DISPLAY_TIMEZONES,
} from "../config";

// ---------------------------------------------------------------------------
// localStorage helpers (SSR-safe)
// ---------------------------------------------------------------------------

/**
 * Read the persisted timezone from ``localStorage``.
 *
 * Returns ``null`` (Auto) if:
 * - no value is stored,
 * - the stored value is not in :data:`KNOWN_DISPLAY_TIMEZONES` (minus
 *   "Auto", which is never persisted), or
 * - ``localStorage`` is unavailable / throws.
 */
function loadTzPref(): string | null {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(DISPLAY_TIMEZONE_STORAGE_KEY);
    if (raw === null) return null;
    // "Auto" is never persisted — its absence is canonical.
    const knownIana = KNOWN_DISPLAY_TIMEZONES.filter(
      (tz): tz is Exclude<(typeof KNOWN_DISPLAY_TIMEZONES)[number], "Auto"> => tz !== "Auto",
    ) as readonly string[];
    return knownIana.includes(raw) ? raw : null;
  } catch {
    return null;
  }
}

/**
 * Write the timezone to ``localStorage``.
 *
 * ``null`` (Auto) removes the key rather than writing a sentinel, so the
 * absence convention is preserved across page reloads.
 */
function saveTzPref(tz: string | null): void {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") {
    return;
  }
  try {
    if (tz === null) {
      window.localStorage.removeItem(DISPLAY_TIMEZONE_STORAGE_KEY);
    } else {
      window.localStorage.setItem(DISPLAY_TIMEZONE_STORAGE_KEY, tz);
    }
  } catch {
    // Quota / private-mode — degrade silently; in-memory state still
    // reflects the user's choice for this page load.
  }
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

interface DisplaySettingsState {
  /**
   * Active IANA timezone string, or ``null`` for "Auto" (browser default).
   *
   * All date helpers (:func:`formatAbsolute`) read this field. Mutate only
   * via :func:`setTimezone` — direct writes skip the ``localStorage`` sync.
   */
  timezone: string | null;
}

const state: DisplaySettingsState = $state({ timezone: loadTzPref() });

/**
 * Reactive display-settings snapshot.
 *
 * Read ``displaySettingsStore.timezone`` inside ``$derived`` or inside
 * plain functions called from reactive contexts.  Components that call
 * :func:`formatAbsolute` from a ``$derived`` automatically re-run when
 * the timezone changes.
 */
export const displaySettingsStore: DisplaySettingsState = state;

/**
 * Update the active display timezone and persist it to ``localStorage``.
 *
 * Pass ``null`` to reset to "Auto" (browser default). The key is removed
 * from storage rather than written to a sentinel so absence == "Auto".
 *
 * @param tz - IANA timezone string (e.g. ``"America/New_York"``), or
 *   ``null`` for Auto.
 */
export function setTimezone(tz: string | null): void {
  state.timezone = tz;
  saveTzPref(tz);
}

// ---------------------------------------------------------------------------
// Test seam
// ---------------------------------------------------------------------------

/**
 * Reset to Auto (null) without touching ``localStorage``.
 *
 * Call in ``beforeEach`` alongside ``window.localStorage.clear()``.
 */
export function _resetForTests(): void {
  state.timezone = null;
}
