import { afterEach, describe, expect, it } from 'vitest';

import { menuConfig } from '$lib/stores/menuConfig.svelte';
import { collectMenuShortcuts } from './shortcuts';

afterEach(() => {
  menuConfig.config = { by_target: {} };
  menuConfig.loaded = false;
  menuConfig.error = null;
});

describe('collectMenuShortcuts', () => {
  it('returns an empty list when no overrides are set', () => {
    expect(collectMenuShortcuts()).toEqual([]);
  });

  it('surfaces bound chords with their action label', () => {
    menuConfig.hydrate({
      by_target: {
        session: {
          pinned: [],
          hidden: [],
          shortcuts: { 'session.delete': 'CTRL+D' }
        }
      }
    });
    const entries = collectMenuShortcuts();
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      target: 'session',
      id: 'session.delete',
      label: 'Delete session',
      chord: 'ctrl+d'
    });
  });

  it('falls back to the raw id when the action is unknown', () => {
    // A TOML binding for an action that never existed (typo) or that
    // was retired between releases: the row still renders so the user
    // knows their file references a dangling id.
    menuConfig.hydrate({
      by_target: {
        session: {
          pinned: [],
          hidden: [],
          shortcuts: { 'session.does_not_exist': 'ctrl+x' }
        }
      }
    });
    const [entry] = collectMenuShortcuts();
    expect(entry?.label).toBe('session.does_not_exist');
  });

  it('orders entries alphabetically within a target', () => {
    menuConfig.hydrate({
      by_target: {
        session: {
          pinned: [],
          hidden: [],
          shortcuts: {
            'session.pin': 'ctrl+p',
            'session.archive': 'ctrl+a'
          }
        }
      }
    });
    const ids = collectMenuShortcuts().map((e) => e.id);
    expect(ids).toEqual(['session.archive', 'session.pin']);
  });

  it('groups by target in registry order', () => {
    menuConfig.hydrate({
      by_target: {
        message: {
          pinned: [],
          hidden: [],
          shortcuts: { 'message.copy_id': 'ctrl+m' }
        },
        session: {
          pinned: [],
          hidden: [],
          shortcuts: { 'session.pin': 'ctrl+p' }
        }
      }
    });
    // `session` precedes `message` in TARGET_TYPES even though the
    // object literal lists them in the other order.
    const targets = collectMenuShortcuts().map((e) => e.target);
    expect(targets).toEqual(['session', 'message']);
  });
});
