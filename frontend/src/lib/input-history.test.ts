import { describe, expect, it } from 'vitest';
import {
  caretOnFirstLine,
  caretOnLastLine,
  emptyHistoryState,
  nextHistory,
  prevHistory,
  resetHistory
} from './input-history';

describe('input-history state machine', () => {
  const entries = ['oldest', 'middle', 'newest'];

  it('prev from empty state jumps to the newest entry and stashes the draft', () => {
    const step = prevHistory(emptyHistoryState(), entries, 'in-progress');
    expect(step.changed).toBe(true);
    expect(step.text).toBe('newest');
    expect(step.state.index).toBe(2);
    expect(step.state.stashedDraft).toBe('in-progress');
  });

  it('prev walks one step older per call and stops at oldest', () => {
    let s = emptyHistoryState();
    let out = prevHistory(s, entries, 'draft');
    expect(out.text).toBe('newest');
    s = out.state;
    out = prevHistory(s, entries, 'draft');
    expect(out.text).toBe('middle');
    s = out.state;
    out = prevHistory(s, entries, 'draft');
    expect(out.text).toBe('oldest');
    s = out.state;
    // Already at oldest — stays put, but still reports changed so
    // the caller preventDefault's the keypress.
    out = prevHistory(s, entries, 'draft');
    expect(out.text).toBe('oldest');
    expect(out.changed).toBe(true);
  });

  it('prev with empty entries list is a no-op', () => {
    const step = prevHistory(emptyHistoryState(), [], 'draft');
    expect(step.changed).toBe(false);
    expect(step.text).toBe('draft');
    expect(step.state.index).toBe(null);
  });

  it('next when not walking is a no-op', () => {
    const step = nextHistory(emptyHistoryState(), entries);
    expect(step.changed).toBe(false);
  });

  it('next walks forward from a walking state', () => {
    const prev = prevHistory(emptyHistoryState(), entries, 'draft');
    // prev took us to index 2 (newest). Walk back once to middle.
    const back = prevHistory(prev.state, entries, 'draft');
    expect(back.text).toBe('middle');
    const fwd = nextHistory(back.state, entries);
    expect(fwd.changed).toBe(true);
    expect(fwd.text).toBe('newest');
    expect(fwd.state.index).toBe(2);
  });

  it('next past newest exits history mode and restores the stashed draft', () => {
    const prev = prevHistory(emptyHistoryState(), entries, 'the-stash');
    // prev → newest, stash=the-stash
    const fwd = nextHistory(prev.state, entries);
    expect(fwd.changed).toBe(true);
    expect(fwd.text).toBe('the-stash');
    expect(fwd.state.index).toBe(null);
    expect(fwd.state.stashedDraft).toBe('');
  });

  it('resetHistory returns empty state when currently walking', () => {
    const walking = { index: 1, stashedDraft: 'x' };
    const reset = resetHistory(walking);
    expect(reset.index).toBe(null);
    expect(reset.stashedDraft).toBe('');
  });

  it('resetHistory on an already-empty state returns the same object (no churn)', () => {
    const s = emptyHistoryState();
    expect(resetHistory(s)).toBe(s);
  });
});

describe('caret-line guards', () => {
  it('caretOnFirstLine is true for single-line drafts', () => {
    expect(caretOnFirstLine('hello', 0, 0)).toBe(true);
    expect(caretOnFirstLine('hello', 5, 5)).toBe(true);
  });

  it('caretOnFirstLine is false when caret is past a newline', () => {
    expect(caretOnFirstLine('one\ntwo', 5, 5)).toBe(false);
  });

  it('caretOnFirstLine is false when there is a selection', () => {
    expect(caretOnFirstLine('hello', 0, 3)).toBe(false);
  });

  it('caretOnLastLine is true when no newline follows the caret', () => {
    expect(caretOnLastLine('one\ntwo', 7, 7)).toBe(true);
  });

  it('caretOnLastLine is false when a newline follows the caret', () => {
    expect(caretOnLastLine('one\ntwo', 0, 0)).toBe(false);
  });

  it('caretOnLastLine is false with an active selection', () => {
    expect(caretOnLastLine('hello', 1, 4)).toBe(false);
  });
});
