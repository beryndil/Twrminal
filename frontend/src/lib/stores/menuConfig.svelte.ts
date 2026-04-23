import * as api from '$lib/api';
import type { TargetType } from '$lib/context-menu/types';

/**
 * Global store for the parsed `~/.config/bearings/menus.toml` overrides
 * that the backend ships via `/api/ui-config` at boot. Single source of
 * truth the context-menu `resolveMenu` consults when filtering and
 * reordering a target's actions.
 *
 * Lifecycle:
 *   - Empty by default so uninitialised callers behave like "no
 *     overrides in effect" — registry falls back to built-in ordering.
 *   - `hydrate()` is the preferred entry point: `billing.init()` owns
 *     the single `/api/ui-config` fetch at boot and pushes the parsed
 *     `context_menus` shape in here so we don't duplicate the request.
 *   - `init()` is a standalone fallback for tests and any caller that
 *     wants the store to drive its own fetch.
 *
 * Overrides are latched for the tab's lifetime. `menus.toml` only
 * reloads on a server restart (Phase 10 design decision) and the
 * WebSocket reconnects on restart anyway, so we don't need hot-reload
 * semantics here.
 */

/** Empty shape returned when a target has no overrides configured.
 * Frozen so accidental writes through `forTarget` can't leak into the
 * store — callers must clone before mutating (no caller currently
 * does, but defence-in-depth against future regressions). */
const EMPTY_TARGET_CONFIG: api.TargetMenuConfig = Object.freeze({
  pinned: Object.freeze([]) as readonly string[] as string[],
  hidden: Object.freeze([]) as readonly string[] as string[],
  shortcuts: Object.freeze({}) as Record<string, string>
});

class MenuConfigStore {
  config = $state<api.MenuConfig>({ by_target: {} });
  loaded = $state(false);
  error = $state<string | null>(null);

  /** Replace the in-memory config with a freshly-fetched payload.
   * Called from `billing.init()` so a single `/api/ui-config` round
   * trip at boot populates both stores. */
  hydrate(cfg: api.MenuConfig): void {
    this.config = cfg;
    this.loaded = true;
    this.error = null;
  }

  /** Standalone fetch path. Used by tests and any future boot
   * sequence that wants menuConfig to own its own network call. Errors
   * leave the (empty) defaults in place so the registry continues to
   * render built-in ordering instead of crashing on a transient
   * `/ui-config` failure. */
  async init(): Promise<void> {
    try {
      const cfg = await api.fetchUiConfig();
      this.config = cfg.context_menus;
      this.error = null;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    } finally {
      this.loaded = true;
    }
  }

  /** Overrides for one target type. Returns an empty (frozen) shape
   * when the target has no entry — callers can always destructure
   * `.pinned`, `.hidden`, `.shortcuts` without a null guard. */
  forTarget(type: TargetType): api.TargetMenuConfig {
    return this.config.by_target[type] ?? EMPTY_TARGET_CONFIG;
  }
}

export const menuConfig = new MenuConfigStore();
