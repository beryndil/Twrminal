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

/** Always-safe default. Used whenever hydrate receives a missing or
 * malformed payload — a stale backend that predates Phase 10 returns
 * `/api/ui-config` without the `context_menus` field, so `cfg.context_menus`
 * is `undefined`. Prior versions crashed `forTarget()` on the very next
 * right-click; this default keeps the registry rendering built-in
 * ordering until the backend catches up. */
const EMPTY_MENU_CONFIG: api.MenuConfig = Object.freeze({
  by_target: Object.freeze({}) as Record<string, api.TargetMenuConfig>
});

/** Runtime shape check for payloads coming off the wire. TypeScript
 * declares `UiConfig.context_menus` as non-optional `MenuConfig`, but
 * a stale or mismatched backend can still send `undefined`, `null`, or
 * a missing `by_target`. Narrow here so the store never latches a
 * broken shape. */
function isMenuConfig(value: unknown): value is api.MenuConfig {
  if (value === null || typeof value !== 'object') return false;
  const maybe = value as { by_target?: unknown };
  return (
    maybe.by_target !== null &&
    typeof maybe.by_target === 'object' &&
    !Array.isArray(maybe.by_target)
  );
}

class MenuConfigStore {
  config = $state<api.MenuConfig>({ by_target: {} });
  loaded = $state(false);
  error = $state<string | null>(null);

  /** Replace the in-memory config with a freshly-fetched payload.
   * Called from `billing.init()` so a single `/api/ui-config` round
   * trip at boot populates both stores. Accepts `undefined` because
   * backends that predate Phase 10 omit the field entirely — in that
   * case we latch the empty default and flag `.error` so consumers
   * can observe the skew without crashing. */
  hydrate(cfg: api.MenuConfig | undefined | null): void {
    if (!isMenuConfig(cfg)) {
      this.config = EMPTY_MENU_CONFIG;
      this.loaded = true;
      this.error = 'menuConfig: /api/ui-config returned no context_menus (stale backend?)';
      return;
    }
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
      this.hydrate(cfg.context_menus);
    } catch (e) {
      this.config = EMPTY_MENU_CONFIG;
      this.error = e instanceof Error ? e.message : String(e);
      this.loaded = true;
    }
  }

  /** Overrides for one target type. Returns an empty (frozen) shape
   * when the target has no entry — callers can always destructure
   * `.pinned`, `.hidden`, `.shortcuts` without a null guard. The
   * `?? EMPTY_MENU_CONFIG.by_target` fallback on `by_target` itself
   * guards the one path that can still slip through: a direct
   * `config = ...` write that bypasses `hydrate` (tests do this). */
  forTarget(type: TargetType): api.TargetMenuConfig {
    const by = this.config?.by_target ?? EMPTY_MENU_CONFIG.by_target;
    return by[type] ?? EMPTY_TARGET_CONFIG;
  }
}

export const menuConfig = new MenuConfigStore();
