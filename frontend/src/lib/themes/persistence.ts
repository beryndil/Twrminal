/**
 * Theme persistence — read/write to localStorage + OS-color-scheme
 * fallback. The store owns "what theme is active"; this module owns
 * "where does the persisted choice live, and what does the OS report
 * when no choice is on file."
 *
 * Behavior anchors:
 *
 * - ``docs/behavior/themes.md`` §"Persistence boundary" — per-device
 *   persistence; the doc prescribes server-sync as well, deferred
 *   to a future item per ``TODO.md`` §"Item 2.9 — theme server-sync
 *   layer (deferred)".
 * - §"Theme picker UI" — first-paint default: ``paper-light`` when
 *   the OS reports a light scheme, ``evergreen`` otherwise.
 * - §"Failure modes" — a localStorage write failure (quota / private
 *   mode) translates to the "couldn't save your theme" toast; the
 *   active theme reverts to whatever the previously-saved value was.
 *   The doc's "removed theme" branch — a persisted name no longer in
 *   :data:`KNOWN_THEMES` resolves to the OS fallback — is the
 *   ``isThemeId`` guard below.
 */
import {
  KNOWN_THEMES,
  THEME_EVERGREEN,
  THEME_PAPER_LIGHT,
  THEME_STORAGE_KEY,
  type ThemeId,
} from "../config";

/**
 * OS color-scheme fallback per the doc's first-paint rules.
 * Returns the dark theme on non-DOM environments (SSR / prerender)
 * since :file:`src/app.html` boots with ``evergreen``.
 */
export function resolveOsFallbackTheme(): ThemeId {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return THEME_EVERGREEN;
  }
  return window.matchMedia("(prefers-color-scheme: light)").matches
    ? THEME_PAPER_LIGHT
    : THEME_EVERGREEN;
}

/**
 * Type guard — returns true when the value is one of the alphabet's
 * known theme ids. A persisted value that is neither in the alphabet
 * nor a string is treated as unset (the "removed theme" branch in
 * the doc's failure modes).
 */
export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === "string" && (KNOWN_THEMES as readonly string[]).includes(value);
}

/**
 * Read the persisted theme from localStorage. Returns ``null`` if no
 * persisted value exists (first paint), the value is invalid (a future
 * removed theme), or storage is inaccessible (private mode / SSR).
 *
 * The caller layers OS fallback on top of the ``null`` case via
 * :func:`resolveOsFallbackTheme`.
 */
export function loadStoredTheme(): ThemeId | null {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeId(raw) ? raw : null;
  } catch {
    return null;
  }
}

/**
 * Persist the chosen theme. Returns ``true`` on success, ``false`` on
 * failure (quota / private mode / SSR). The caller surfaces the
 * "couldn't save your theme" toast on ``false`` and reverts the local
 * preview to whatever was on file before per the doc §"Failure modes".
 */
export function saveStoredTheme(theme: ThemeId): boolean {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") {
    return false;
  }
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    return true;
  } catch {
    return false;
  }
}

/**
 * Boot-time resolver — the single function the runtime store calls
 * once at construction to settle on an initial value.
 *
 * If a persisted choice exists it is returned as-is. If none exists
 * the OS fallback is computed **and immediately persisted** so that
 * subsequent page loads read the stored value and the ``app.html``
 * boot-time static attribute stays consistent. Without this write the
 * static ``data-theme="evergreen"`` flashes to the OS fallback on the
 * first ``ThemeProvider`` mount for users who never explicitly picked
 * a theme (the "silent flip" bug logged in ``TODO.md`` 2026-05-02).
 *
 * The persist call is best-effort — private mode / quota failures are
 * silently ignored (the fallback still applies in-memory for this page
 * load, and the flash recurs on the next boot).
 */
export function resolveBootTheme(): ThemeId {
  const stored = loadStoredTheme();
  if (stored !== null) {
    return stored;
  }
  const osFallback = resolveOsFallbackTheme();
  // Persist so the next page load reads the stored value and the
  // static HTML boot attribute stays in sync (no flash on reload).
  saveStoredTheme(osFallback);
  return osFallback;
}
