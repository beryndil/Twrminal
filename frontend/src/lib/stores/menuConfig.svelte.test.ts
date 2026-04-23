import { afterEach, describe, expect, it, vi } from 'vitest';

import type { MenuConfig, UiConfig } from '$lib/api';
import { menuConfig } from './menuConfig.svelte';

function emptyConfig(): MenuConfig {
  return { by_target: {} };
}

function uiConfig(cm: MenuConfig): UiConfig {
  return { billing_mode: 'payg', billing_plan: null, context_menus: cm };
}

afterEach(() => {
  vi.restoreAllMocks();
  menuConfig.config = emptyConfig();
  menuConfig.loaded = false;
  menuConfig.error = null;
});

describe('menuConfig.hydrate', () => {
  it('replaces the in-memory config with the provided payload', () => {
    menuConfig.hydrate({
      by_target: {
        session: { pinned: ['session.pin'], hidden: [], shortcuts: {} }
      }
    });
    expect(menuConfig.loaded).toBe(true);
    expect(menuConfig.error).toBeNull();
    expect(menuConfig.forTarget('session').pinned).toEqual(['session.pin']);
  });

  it('resets error state on a fresh hydrate', () => {
    menuConfig.error = 'stale';
    menuConfig.hydrate(emptyConfig());
    expect(menuConfig.error).toBeNull();
  });

  // Regression: a backend that predates Phase 10 returns `/api/ui-config`
  // without the `context_menus` field, so `cfg.context_menus` is
  // `undefined`. Prior versions set `config = undefined`, which made
  // `forTarget()` throw on the very next right-click and silently
  // bricked every Bearings context menu in the app. We now latch the
  // empty default and flag `.error` so the store stays usable.
  it('latches the empty default when the payload is undefined', () => {
    menuConfig.hydrate(undefined);
    expect(menuConfig.loaded).toBe(true);
    expect(menuConfig.error).toContain('stale backend');
    expect(() => menuConfig.forTarget('session')).not.toThrow();
    expect(menuConfig.forTarget('session').pinned).toEqual([]);
  });

  it('latches the empty default when the payload is null', () => {
    menuConfig.hydrate(null);
    expect(menuConfig.loaded).toBe(true);
    expect(menuConfig.error).toContain('stale backend');
    expect(menuConfig.forTarget('message').hidden).toEqual([]);
  });

  it('latches the empty default when by_target is missing or wrong type', () => {
    // Shapes we've seen or could plausibly see from a half-upgraded
    // backend or a misconfigured proxy: object without `by_target`,
    // `by_target` as an array, primitive payload, etc.
    const badShapes = [
      {},
      { by_target: [] },
      { by_target: null },
      'not an object',
      42
    ];
    for (const shape of badShapes) {
      menuConfig.hydrate(shape as unknown as MenuConfig);
      expect(menuConfig.error).toContain('stale backend');
      expect(() => menuConfig.forTarget('session')).not.toThrow();
    }
  });
});

describe('menuConfig.forTarget', () => {
  it('returns an empty shape for unknown target types', () => {
    const cfg = menuConfig.forTarget('session');
    expect(cfg.pinned).toEqual([]);
    expect(cfg.hidden).toEqual([]);
    expect(cfg.shortcuts).toEqual({});
  });

  it('returns the configured entry when present', () => {
    menuConfig.hydrate({
      by_target: {
        message: {
          pinned: ['message.copy_id'],
          hidden: ['message.delete'],
          shortcuts: { 'message.pin': 'ctrl+p' }
        }
      }
    });
    const cfg = menuConfig.forTarget('message');
    expect(cfg.pinned).toEqual(['message.copy_id']);
    expect(cfg.hidden).toEqual(['message.delete']);
    expect(cfg.shortcuts).toEqual({ 'message.pin': 'ctrl+p' });
  });
});

describe('menuConfig.init', () => {
  it('fetches /api/ui-config and stores the context_menus payload', async () => {
    const payload: MenuConfig = {
      by_target: { tag: { pinned: ['tag.rename'], hidden: [], shortcuts: {} } }
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        async json() {
          return uiConfig(payload);
        },
        async text() {
          return '';
        }
      }))
    );
    await menuConfig.init();
    expect(menuConfig.loaded).toBe(true);
    expect(menuConfig.error).toBeNull();
    expect(menuConfig.forTarget('tag').pinned).toEqual(['tag.rename']);
  });

  it('swallows fetch failures and leaves defaults in place', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 500,
        async json() {
          return {};
        },
        async text() {
          return 'boom';
        }
      }))
    );
    await menuConfig.init();
    expect(menuConfig.loaded).toBe(true);
    expect(menuConfig.error).toContain('500');
    expect(menuConfig.forTarget('session').pinned).toEqual([]);
  });
});
