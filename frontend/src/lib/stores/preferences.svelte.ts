/** Server-synced user preferences (migration 0026 / commit `2871877`).
 *
 * Boot sequence:
 *   1. Construct: read the localStorage cache key (`bearings:preferences-
 *      cache`) so we have something to render before the network round-
 *      trip completes. This is best-effort — a fresh browser shows
 *      defaults until the GET returns.
 *   2. `init(fetch)`: fire `GET /api/preferences`. On success, replace
 *      the in-memory state and write the cache. On failure (server
 *      down, auth required, transient 500) keep whatever the cache
 *      gave us and try again on next boot.
 *   3. One-shot localStorage migration: if the GET landed on the seed
 *      row (every preference still NULL/default) AND any of the three
 *      legacy `bearings:` keys exist (`defaultModel`, `defaultWorkingDir`,
 *      `notifyOnComplete`), fire one PATCH to hydrate the server, then
 *      clear those three keys. If the PATCH fails the legacy keys stay
 *      put and the next boot retries — fully idempotent.
 *
 * Mutation: `update(patch)` PATCHes the server, swaps the local state
 * to the response, and writes the cache. The previous state snapshot is
 * restored on rejection so the UI doesn't show optimistic-then-reverted
 * flicker on a transient 500. The auth token deliberately stays in
 * `prefs.svelte.ts` — it's client-side by design (the server can't
 * authorize itself on its own stored token).
 */

import * as api from '$lib/api';

const CACHE_KEY = 'bearings:preferences-cache';

/** Mobile browser chrome color per bundled theme. Mirrors the table
 * in `app.html`'s no-flash boot script so `<meta name="theme-color">`
 * stays in sync across (a) initial paint, (b) picker save, and
 * (c) reload. Keep both in sync if a new theme lands. */
const THEME_COLORS: Record<string, string> = {
  'midnight-glass': '#0A0E1C',
  'default': '#020617',
  'paper-light': '#FAF7F0'
};
const LEGACY_MODEL_KEY = 'bearings:defaultModel';
const LEGACY_WORKDIR_KEY = 'bearings:defaultWorkingDir';
const LEGACY_NOTIFY_KEY = 'bearings:notifyOnComplete';

/** Snapshot the singleton row in a shape mirrored 1:1 from the wire
 * DTO. Stored in localStorage as JSON so a reload renders the last
 * known values before the server round-trip completes. */
type CachedPrefs = {
  display_name: string | null;
  theme: string | null;
  default_model: string | null;
  default_working_dir: string | null;
  notify_on_complete: boolean;
  updated_at: string;
};

const EMPTY_PREFS: CachedPrefs = {
  display_name: null,
  theme: null,
  default_model: null,
  default_working_dir: null,
  notify_on_complete: false,
  updated_at: ''
};

function readCache(): CachedPrefs | null {
  if (typeof localStorage === 'undefined') return null;
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<CachedPrefs>;
    // Defensive: if a stale build wrote a different shape, fall back
    // to defaults rather than crash on shape mismatch downstream.
    return { ...EMPTY_PREFS, ...parsed };
  } catch {
    return null;
  }
}

function writeCache(prefs: CachedPrefs): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(prefs));
  } catch {
    // Quota / private-mode — UI keeps working in-memory; next boot
    // just falls back to a server-fresh fetch.
  }
}

function readLegacy(key: string): string | null {
  if (typeof localStorage === 'undefined') return null;
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function clearLegacyKeys(): void {
  if (typeof localStorage === 'undefined') return;
  for (const key of [LEGACY_MODEL_KEY, LEGACY_WORKDIR_KEY, LEGACY_NOTIFY_KEY]) {
    try {
      localStorage.removeItem(key);
    } catch {
      // best-effort
    }
  }
}

/** A row is "still at seed state" when every server-owned field
 * matches the migration's defaults (NULL strings, false bool). The
 * `updated_at` timestamp is independently checked at the call site —
 * the migration writes a SQLite-format timestamp without `T`, every
 * Pydantic-bumped one is ISO-8601 with `T`, so a populated `updated_at`
 * that lacks `T` is the strongest seed-state signal. We use the
 * combined check so an admin who manually `UPDATE`s the row to seed
 * defaults doesn't get a re-migration on next boot (that's the bug
 * tradeoff: re-migrate is one PATCH, not destructive). */
function isSeedState(prefs: api.Preferences): boolean {
  const allUnset =
    prefs.display_name === null &&
    prefs.theme === null &&
    prefs.default_model === null &&
    prefs.default_working_dir === null &&
    prefs.notify_on_complete === false;
  // Seed row is created with `datetime('now')` (no `T`); every
  // application-driven write uses `_now()` which is `datetime.now(UTC)
  // .isoformat()` (always contains `T`). A timestamp without `T` is
  // therefore an unmistakable "never been PATCHed" signal.
  const seedTimestamp = !prefs.updated_at.includes('T');
  return allUnset && seedTimestamp;
}

class PreferencesStore {
  /** The full row, mirroring the server shape. Components reactively
   * derive the fields they need (`displayName`, `defaultModel`, etc.)
   * via the getters below — components shouldn't reach into `.row`
   * directly so the public surface stays stable if the wire shape
   * changes. */
  private row = $state<CachedPrefs>(readCache() ?? EMPTY_PREFS);
  loaded = $state(false);

  // --- public getters (component-friendly accessors) ----------------
  // Using getters rather than `$derived` so consumers can read them
  // outside reactive contexts (e.g. inside a click handler) without
  // needing `.value`.

  get displayName(): string | null {
    return this.row.display_name;
  }
  get theme(): string | null {
    return this.row.theme;
  }
  get defaultModel(): string {
    return this.row.default_model ?? '';
  }
  get defaultWorkingDir(): string {
    return this.row.default_working_dir ?? '';
  }
  get notifyOnComplete(): boolean {
    return this.row.notify_on_complete;
  }

  /** Apply a server response (or cached snapshot) to the in-memory
   * state. Pulled out so `init` and `update` share the same shape-
   * normalisation step. */
  private apply(prefs: api.Preferences): void {
    this.row = {
      display_name: prefs.display_name,
      theme: prefs.theme,
      default_model: prefs.default_model,
      default_working_dir: prefs.default_working_dir,
      notify_on_complete: prefs.notify_on_complete,
      updated_at: prefs.updated_at
    };
    writeCache(this.row);
    this.applyTheme();
  }

  /** Reflect the active theme on `<html data-theme="...">` and update
   * `<meta name="theme-color">` so mobile browser chrome tracks the
   * picked theme without waiting for a reload. The no-flash boot
   * script in `app.html` also writes `data-theme` and `theme-color`
   * synchronously before first paint based on the cached row; this
   * runtime path covers the in-session picker change. NULL preference
   * leaves whatever the boot script resolved in place — the desired
   * "I haven't picked one" UX. */
  private applyTheme(): void {
    if (typeof document === 'undefined') return;
    if (!this.row.theme) return;
    document.documentElement.dataset.theme = this.row.theme;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      const color = THEME_COLORS[this.row.theme];
      if (color) meta.setAttribute('content', color);
    }
  }

  /** Run the boot fetch. Idempotent — calling twice is a no-op after
   * the first success. Errors are swallowed so a server-down boot
   * keeps the cached preferences visible; the next refresh / focus /
   * navigation tries again. */
  async init(fetchImpl: typeof fetch = fetch): Promise<void> {
    try {
      const fresh = await api.fetchPreferences(fetchImpl);
      const wasSeed = isSeedState(fresh);
      this.apply(fresh);
      this.loaded = true;
      if (wasSeed) await this.maybeMigrateLegacy(fetchImpl);
    } catch {
      // Cached state stays in place; loaded remains false so the next
      // boot retries. We deliberately don't surface this — auth-gated
      // boots will show the auth gate first; once the token is in
      // place the next attempt succeeds.
    }
  }

  /** PATCH the server with a partial body. Optimistic: applies the
   * response on success, leaves state unchanged on failure (the call
   * site rethrows so a Save handler can keep the modal open + show an
   * error). */
  async update(
    patch: api.PreferencesPatch,
    fetchImpl: typeof fetch = fetch
  ): Promise<void> {
    const fresh = await api.patchPreferences(patch, fetchImpl);
    this.apply(fresh);
  }

  /** Hydrate the server from the three legacy localStorage keys. Only
   * runs on the boot path where the GET landed on the seed row. After
   * a successful PATCH the legacy keys are cleared; on failure they
   * stay so a future boot can retry. */
  private async maybeMigrateLegacy(fetchImpl: typeof fetch): Promise<void> {
    const model = readLegacy(LEGACY_MODEL_KEY);
    const workdir = readLegacy(LEGACY_WORKDIR_KEY);
    const notifyRaw = readLegacy(LEGACY_NOTIFY_KEY);
    const hasAny = model !== null || workdir !== null || notifyRaw !== null;
    if (!hasAny) return;
    const patch: api.PreferencesPatch = {};
    if (model !== null && model !== '') patch.default_model = model;
    if (workdir !== null && workdir !== '') patch.default_working_dir = workdir;
    if (notifyRaw !== null) patch.notify_on_complete = notifyRaw === '1';
    if (Object.keys(patch).length === 0) {
      // All three keys were present but empty — nothing useful to
      // migrate, but do clear the empty husks so we don't keep
      // spinning on this branch.
      clearLegacyKeys();
      return;
    }
    try {
      await this.update(patch, fetchImpl);
      clearLegacyKeys();
    } catch {
      // Leave legacy keys intact — next boot retries the migration
      // unchanged. Idempotent because the seed-state check stays true
      // until a successful PATCH lands.
    }
  }
}

export const preferences = new PreferencesStore();
