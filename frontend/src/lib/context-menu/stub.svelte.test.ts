import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  STUB_DEFAULT_WINDOW_MS,
  STUB_MAX_VISIBLE,
  notYetImplemented,
  stubStore
} from './stub.svelte';

describe('stubStore', () => {
  beforeEach(() => {
    stubStore._resetForTests();
    vi.useFakeTimers();
    stubStore._setTimeSource({
      set: (fn, ms) => globalThis.setTimeout(fn, ms),
      clear: (t) => globalThis.clearTimeout(t)
    });
  });

  afterEach(() => {
    stubStore._resetForTests();
    stubStore._setTimeSource(null);
    vi.useRealTimers();
  });

  it('show pushes a new toast with an auto-id', () => {
    const id = stubStore.show({ actionId: 'session.export_zip' });
    expect(id).toBe(1);
    expect(stubStore.items).toHaveLength(1);
    expect(stubStore.items[0]!.actionId).toBe('session.export_zip');
  });

  it('auto-dismisses after the default window', () => {
    stubStore.show({ actionId: 'a' });
    vi.advanceTimersByTime(STUB_DEFAULT_WINDOW_MS - 1);
    expect(stubStore.items).toHaveLength(1);
    vi.advanceTimersByTime(2);
    expect(stubStore.items).toHaveLength(0);
  });

  it('deduplicates by actionId — re-show resets the timer', () => {
    stubStore.show({ actionId: 'repeat' });
    vi.advanceTimersByTime(STUB_DEFAULT_WINDOW_MS - 500);
    // Re-show before the timer expires — should refresh, not stack.
    stubStore.show({ actionId: 'repeat', reason: 'second press' });
    expect(stubStore.items).toHaveLength(1);
    // Original window would have expired by now; reset window is fresh.
    vi.advanceTimersByTime(600);
    expect(stubStore.items).toHaveLength(1);
    vi.advanceTimersByTime(STUB_DEFAULT_WINDOW_MS);
    expect(stubStore.items).toHaveLength(0);
  });

  it('caps at STUB_MAX_VISIBLE by evicting the oldest', () => {
    for (let i = 0; i < STUB_MAX_VISIBLE + 2; i++) {
      stubStore.show({ actionId: `a${i}` });
    }
    expect(stubStore.items).toHaveLength(STUB_MAX_VISIBLE);
    expect(stubStore.items.map((x) => x.actionId)).toEqual([
      'a2',
      'a3',
      'a4'
    ]);
  });

  it('dismiss removes the toast and cancels the timer', () => {
    const id = stubStore.show({ actionId: 'dismiss-me' });
    stubStore.dismiss(id);
    expect(stubStore.items).toHaveLength(0);
    vi.advanceTimersByTime(STUB_DEFAULT_WINDOW_MS + 1000);
    expect(stubStore.items).toHaveLength(0);
  });

  it('notYetImplemented is a thin alias over show', () => {
    notYetImplemented('session.delete', 'Arrives in v0.9.1');
    expect(stubStore.items).toHaveLength(1);
    expect(stubStore.items[0]!.reason).toBe('Arrives in v0.9.1');
  });
});
