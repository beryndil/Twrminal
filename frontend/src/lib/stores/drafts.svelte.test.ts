import { beforeEach, describe, expect, it, vi } from 'vitest';
import { drafts } from './drafts.svelte';

// Keep each test isolated: localStorage is shared process-global in
// jsdom, and the DraftsStore's internal debounce/buffer maps need a
// known starting point. Fake timers give us deterministic control
// over the 300 ms write debounce.
beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers();
  // Clear any in-flight debounced writes from a prior test so they
  // don't leak into this one via the module-singleton `drafts`.
  drafts.clear('sess-a');
  drafts.clear('sess-b');
});

describe('DraftsStore', () => {
  it('get returns empty string when nothing is stored', () => {
    expect(drafts.get('sess-a')).toBe('');
  });

  it('set buffers the value immediately so get sees the latest write', () => {
    drafts.set('sess-a', 'hello');
    // Before the debounce fires, localStorage is empty — but the
    // store buffers pending values so get() stays consistent.
    expect(localStorage.getItem('bearings:draft:sess-a')).toBeNull();
    expect(drafts.get('sess-a')).toBe('hello');
  });

  it('set commits to localStorage after the debounce window', () => {
    drafts.set('sess-a', 'hello');
    vi.advanceTimersByTime(299);
    expect(localStorage.getItem('bearings:draft:sess-a')).toBeNull();
    vi.advanceTimersByTime(1);
    expect(localStorage.getItem('bearings:draft:sess-a')).toBe('hello');
  });

  it('coalesces rapid writes and commits only the last value', () => {
    drafts.set('sess-a', 'h');
    drafts.set('sess-a', 'he');
    drafts.set('sess-a', 'hello');
    vi.advanceTimersByTime(300);
    expect(localStorage.getItem('bearings:draft:sess-a')).toBe('hello');
  });

  it('flush commits the pending write synchronously', () => {
    drafts.set('sess-a', 'urgent');
    drafts.flush('sess-a');
    expect(localStorage.getItem('bearings:draft:sess-a')).toBe('urgent');
  });

  it('clear removes the key and cancels any pending write', () => {
    drafts.set('sess-a', 'hello');
    drafts.clear('sess-a');
    vi.advanceTimersByTime(300);
    expect(localStorage.getItem('bearings:draft:sess-a')).toBeNull();
    expect(drafts.get('sess-a')).toBe('');
  });

  it('set with an empty string removes the key (no lingering blank drafts)', () => {
    localStorage.setItem('bearings:draft:sess-a', 'old');
    drafts.set('sess-a', '');
    vi.advanceTimersByTime(300);
    expect(localStorage.getItem('bearings:draft:sess-a')).toBeNull();
  });

  it('keys sessions independently', () => {
    drafts.set('sess-a', 'for A');
    drafts.set('sess-b', 'for B');
    vi.advanceTimersByTime(300);
    expect(localStorage.getItem('bearings:draft:sess-a')).toBe('for A');
    expect(localStorage.getItem('bearings:draft:sess-b')).toBe('for B');
  });

  it('get reads a value persisted in a prior page load', () => {
    localStorage.setItem('bearings:draft:sess-a', 'yesterday');
    expect(drafts.get('sess-a')).toBe('yesterday');
  });
});
