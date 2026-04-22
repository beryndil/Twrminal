import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  DEFAULT_WINDOW_MS,
  MAX_VISIBLE,
  undoStore
} from './undo.svelte';

describe('undoStore', () => {
  beforeEach(() => {
    undoStore._resetForTests();
    vi.useFakeTimers();
    // Route the store's timers through vitest's fake-timer plane so
    // we can `advanceTimersByTime` deterministically.
    undoStore._setTimeSource({
      set: (fn, ms) => globalThis.setTimeout(fn, ms),
      clear: (t) => globalThis.clearTimeout(t)
    });
  });

  afterEach(() => {
    undoStore._resetForTests();
    undoStore._setTimeSource(null);
    vi.useRealTimers();
  });

  it('push appends and assigns sequential ids', () => {
    const a = undoStore.push({ message: 'one', inverse: () => {} });
    const b = undoStore.push({ message: 'two', inverse: () => {} });
    expect(a).toBe(1);
    expect(b).toBe(2);
    expect(undoStore.items.map((x) => x.message)).toEqual(['one', 'two']);
  });

  it('dismiss removes the item and cancels the timer', () => {
    const id = undoStore.push({ message: 'kill-me', inverse: () => {} });
    expect(undoStore.items).toHaveLength(1);
    undoStore.dismiss(id);
    expect(undoStore.items).toHaveLength(0);
    // Advancing past the window must not re-remove or throw.
    vi.advanceTimersByTime(DEFAULT_WINDOW_MS + 1000);
    expect(undoStore.items).toHaveLength(0);
  });

  it('expires after the default window', () => {
    undoStore.push({ message: 'time-out', inverse: () => {} });
    vi.advanceTimersByTime(DEFAULT_WINDOW_MS - 1);
    expect(undoStore.items).toHaveLength(1);
    vi.advanceTimersByTime(2);
    expect(undoStore.items).toHaveLength(0);
  });

  it('respects per-item windowMs', () => {
    undoStore.push({
      message: 'short',
      windowMs: 1000,
      inverse: () => {}
    });
    vi.advanceTimersByTime(500);
    expect(undoStore.items).toHaveLength(1);
    vi.advanceTimersByTime(501);
    expect(undoStore.items).toHaveLength(0);
  });

  it('caps at MAX_VISIBLE by evicting the oldest', () => {
    for (let i = 0; i < MAX_VISIBLE + 2; i++) {
      undoStore.push({ message: `t${i}`, inverse: () => {} });
    }
    expect(undoStore.items).toHaveLength(MAX_VISIBLE);
    // Oldest two were evicted — the newest MAX_VISIBLE remain.
    expect(undoStore.items.map((x) => x.message)).toEqual([
      't2',
      't3',
      't4'
    ]);
  });

  it('eviction clears the victim timer (no zombie dismiss later)', () => {
    for (let i = 0; i < MAX_VISIBLE + 1; i++) {
      undoStore.push({ message: `t${i}`, inverse: () => {} });
    }
    // Evicted item's timer should have been cancelled — advancing
    // time only fires the remaining visible items' timers.
    vi.advanceTimersByTime(DEFAULT_WINDOW_MS + 1);
    expect(undoStore.items).toHaveLength(0);
  });

  it('invoke runs inverse then removes the item', async () => {
    const inverse = vi.fn();
    const id = undoStore.push({ message: 'hit', inverse });
    await undoStore.invoke(id);
    expect(inverse).toHaveBeenCalledOnce();
    expect(undoStore.items).toHaveLength(0);
  });

  it('invoke twice does not double-run the inverse', async () => {
    const inverse = vi.fn();
    const id = undoStore.push({ message: 'hit', inverse });
    await Promise.all([undoStore.invoke(id), undoStore.invoke(id)]);
    expect(inverse).toHaveBeenCalledOnce();
  });

  it('invoke swallows inverse errors so the toast still clears', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const id = undoStore.push({
      message: 'boom',
      inverse: () => {
        throw new Error('nope');
      }
    });
    await undoStore.invoke(id);
    expect(undoStore.items).toHaveLength(0);
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });

  it('clear removes everything without running inverses', () => {
    const inverse = vi.fn();
    undoStore.push({ message: 'a', inverse });
    undoStore.push({ message: 'b', inverse });
    undoStore.clear();
    expect(undoStore.items).toHaveLength(0);
    expect(inverse).not.toHaveBeenCalled();
  });
});
