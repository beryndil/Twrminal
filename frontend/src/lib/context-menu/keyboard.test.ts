import { describe, expect, it } from 'vitest';

import {
  INITIAL_STATE,
  reduce,
  type FSMItem,
  type ItemsSnapshot,
  type KeyboardState
} from './keyboard';

// Plan §6.2 asks for every FSM transition to be unit-tested. The
// reducer is pure, so each test constructs its own state + items and
// asserts the returned state + optional effect.

function items(
  main: FSMItem[],
  submenu: FSMItem[] = []
): ItemsSnapshot {
  return { main, submenu };
}

const plain: FSMItem = {};
const plainB: FSMItem = { mnemonic: 'b' };
const disabled: FSMItem = { disabled: true };
const withSubmenu: FSMItem = { hasSubmenu: true };
const mnemA: FSMItem = { mnemonic: 'a' };
const mnemA2: FSMItem = { mnemonic: 'a' };

describe('reduce — main menu navigation', () => {
  const snap = items([plain, plain, plain]);

  it('ArrowDown from closed state focuses the first item', () => {
    const r = reduce(INITIAL_STATE, { type: 'ArrowDown' }, snap);
    expect(r.state.focusedIndex).toBe(0);
    expect(r.effect).toBeUndefined();
  });

  it('ArrowUp from closed state focuses the last item', () => {
    const r = reduce(INITIAL_STATE, { type: 'ArrowUp' }, snap);
    expect(r.state.focusedIndex).toBe(2);
  });

  it('ArrowDown wraps past the end', () => {
    const r = reduce(
      { ...INITIAL_STATE, focusedIndex: 2 },
      { type: 'ArrowDown' },
      snap
    );
    expect(r.state.focusedIndex).toBe(0);
  });

  it('ArrowUp wraps before the start', () => {
    const r = reduce(
      { ...INITIAL_STATE, focusedIndex: 0 },
      { type: 'ArrowUp' },
      snap
    );
    expect(r.state.focusedIndex).toBe(2);
  });

  it('ArrowDown skips disabled rows', () => {
    const snap2 = items([plain, disabled, plain]);
    const r = reduce(
      { ...INITIAL_STATE, focusedIndex: 0 },
      { type: 'ArrowDown' },
      snap2
    );
    expect(r.state.focusedIndex).toBe(2);
  });

  it('Home jumps to first focusable; End jumps to last focusable', () => {
    const snap2 = items([disabled, plain, plain, disabled]);
    const h = reduce(INITIAL_STATE, { type: 'Home' }, snap2);
    expect(h.state.focusedIndex).toBe(1);
    const e = reduce(INITIAL_STATE, { type: 'End' }, snap2);
    expect(e.state.focusedIndex).toBe(2);
  });

  it('arrow nav on an all-disabled list leaves focus at -1', () => {
    const snap2 = items([disabled, disabled]);
    const r = reduce(INITIAL_STATE, { type: 'ArrowDown' }, snap2);
    expect(r.state.focusedIndex).toBe(-1);
  });

  it('arrow nav on an empty list leaves focus at -1', () => {
    const r = reduce(INITIAL_STATE, { type: 'ArrowDown' }, items([]));
    expect(r.state.focusedIndex).toBe(-1);
  });
});

describe('reduce — Enter and Escape', () => {
  const snap = items([plain, plain, plain]);

  it('Enter with no focus is a no-op', () => {
    const r = reduce(INITIAL_STATE, { type: 'Enter' }, snap);
    expect(r.effect).toBeUndefined();
  });

  it('Enter on a focused plain item fires activate', () => {
    const r = reduce(
      { ...INITIAL_STATE, focusedIndex: 1 },
      { type: 'Enter' },
      snap
    );
    expect(r.effect).toEqual({ type: 'activate', list: 'main', index: 1 });
  });

  it('Enter on a disabled item is a no-op', () => {
    const snap2 = items([plain, disabled, plain]);
    const r = reduce(
      { ...INITIAL_STATE, focusedIndex: 1 },
      { type: 'Enter' },
      snap2
    );
    expect(r.effect).toBeUndefined();
  });

  it('Enter on a submenu parent fires openSubmenu', () => {
    const snap2 = items([plain, withSubmenu], [plain]);
    const r = reduce(
      { ...INITIAL_STATE, focusedIndex: 1 },
      { type: 'Enter' },
      snap2
    );
    expect(r.effect).toEqual({ type: 'openSubmenu', parentIndex: 1 });
    expect(r.state.submenuOpen).toBe(true);
    expect(r.state.submenuFocusedIndex).toBe(0);
  });

  it('Escape on root fires close', () => {
    const r = reduce(INITIAL_STATE, { type: 'Escape' }, snap);
    expect(r.effect).toEqual({ type: 'close' });
  });
});

describe('reduce — submenu open / close via arrows', () => {
  const snap = items([plain, withSubmenu], [plain, plain]);

  it('ArrowRight on a focused submenu parent opens the submenu', () => {
    const r = reduce(
      { ...INITIAL_STATE, focusedIndex: 1 },
      { type: 'ArrowRight' },
      snap
    );
    expect(r.state.submenuOpen).toBe(true);
    expect(r.state.submenuFocusedIndex).toBe(0);
    expect(r.effect).toEqual({ type: 'openSubmenu', parentIndex: 1 });
  });

  it('ArrowRight on a non-submenu row is a no-op', () => {
    const r = reduce(
      { ...INITIAL_STATE, focusedIndex: 0 },
      { type: 'ArrowRight' },
      snap
    );
    expect(r.state.submenuOpen).toBe(false);
    expect(r.effect).toBeUndefined();
  });

  it('ArrowLeft in open submenu closes it', () => {
    const state: KeyboardState = {
      focusedIndex: 1,
      submenuOpen: true,
      submenuFocusedIndex: 0
    };
    const r = reduce(state, { type: 'ArrowLeft' }, snap);
    expect(r.state.submenuOpen).toBe(false);
    expect(r.state.submenuFocusedIndex).toBe(-1);
    expect(r.effect).toEqual({ type: 'closeSubmenu' });
  });

  it('ArrowLeft at root is a no-op', () => {
    const r = reduce(INITIAL_STATE, { type: 'ArrowLeft' }, snap);
    expect(r.effect).toBeUndefined();
  });

  it('ArrowRight inside open submenu does not dive deeper', () => {
    const state: KeyboardState = {
      focusedIndex: 1,
      submenuOpen: true,
      submenuFocusedIndex: 0
    };
    const r = reduce(state, { type: 'ArrowRight' }, snap);
    expect(r.state.submenuOpen).toBe(true);
    expect(r.effect).toBeUndefined();
  });

  it('Escape in open submenu closes submenu only', () => {
    const state: KeyboardState = {
      focusedIndex: 1,
      submenuOpen: true,
      submenuFocusedIndex: 0
    };
    const r = reduce(state, { type: 'Escape' }, snap);
    expect(r.state.submenuOpen).toBe(false);
    expect(r.effect).toEqual({ type: 'closeSubmenu' });
  });
});

describe('reduce — submenu nav and activation', () => {
  const snap = items([plain, withSubmenu], [plain, disabled, plain]);
  const opened: KeyboardState = {
    focusedIndex: 1,
    submenuOpen: true,
    submenuFocusedIndex: 0
  };

  it('ArrowDown in submenu skips disabled', () => {
    const r = reduce(opened, { type: 'ArrowDown' }, snap);
    expect(r.state.submenuFocusedIndex).toBe(2);
  });

  it('ArrowUp in submenu wraps', () => {
    const r = reduce(opened, { type: 'ArrowUp' }, snap);
    expect(r.state.submenuFocusedIndex).toBe(2);
  });

  it('Enter in submenu activates the focused item', () => {
    const r = reduce(opened, { type: 'Enter' }, snap);
    expect(r.effect).toEqual({
      type: 'activate',
      list: 'submenu',
      index: 0
    });
  });

  it('Enter on a disabled submenu row is a no-op', () => {
    const state = { ...opened, submenuFocusedIndex: 1 };
    const r = reduce(state, { type: 'Enter' }, snap);
    expect(r.effect).toBeUndefined();
  });

  it('Home in submenu targets the first focusable, End the last', () => {
    const h = reduce(opened, { type: 'Home' }, snap);
    expect(h.state.submenuFocusedIndex).toBe(0);
    const e = reduce(opened, { type: 'End' }, snap);
    expect(e.state.submenuFocusedIndex).toBe(2);
  });
});

describe('reduce — mnemonics', () => {
  it('unique mnemonic focuses and activates', () => {
    const snap = items([plain, mnemA, plainB]);
    const r = reduce(
      INITIAL_STATE,
      { type: 'Mnemonic', char: 'a' },
      snap
    );
    expect(r.state.focusedIndex).toBe(1);
    expect(r.effect).toEqual({ type: 'activate', list: 'main', index: 1 });
  });

  it('unique mnemonic on submenu parent opens the submenu instead', () => {
    const parent: FSMItem = { mnemonic: 'a', hasSubmenu: true };
    const snap = items([plain, parent], [plain]);
    const r = reduce(
      INITIAL_STATE,
      { type: 'Mnemonic', char: 'a' },
      snap
    );
    expect(r.state.submenuOpen).toBe(true);
    expect(r.effect).toEqual({ type: 'openSubmenu', parentIndex: 1 });
  });

  it('duplicate mnemonic cycles focus without activating', () => {
    const snap = items([mnemA, mnemA2, plain]);
    const first = reduce(
      INITIAL_STATE,
      { type: 'Mnemonic', char: 'a' },
      snap
    );
    expect(first.state.focusedIndex).toBe(0);
    expect(first.effect).toBeUndefined();

    const second = reduce(
      first.state,
      { type: 'Mnemonic', char: 'a' },
      snap
    );
    expect(second.state.focusedIndex).toBe(1);
    expect(second.effect).toBeUndefined();

    // Wraps past the last match back to the first.
    const third = reduce(
      second.state,
      { type: 'Mnemonic', char: 'a' },
      snap
    );
    expect(third.state.focusedIndex).toBe(0);
  });

  it('unknown mnemonic is a no-op', () => {
    const snap = items([plain, mnemA]);
    const r = reduce(
      INITIAL_STATE,
      { type: 'Mnemonic', char: 'z' },
      snap
    );
    expect(r.state.focusedIndex).toBe(-1);
    expect(r.effect).toBeUndefined();
  });

  it('mnemonic is case-insensitive', () => {
    const snap = items([plain, mnemA]);
    const r = reduce(
      INITIAL_STATE,
      { type: 'Mnemonic', char: 'A' },
      snap
    );
    expect(r.effect).toEqual({ type: 'activate', list: 'main', index: 1 });
  });

  it('disabled matches are ignored', () => {
    const gated: FSMItem = { mnemonic: 'a', disabled: true };
    const snap = items([gated, plain]);
    const r = reduce(
      INITIAL_STATE,
      { type: 'Mnemonic', char: 'a' },
      snap
    );
    expect(r.state.focusedIndex).toBe(-1);
    expect(r.effect).toBeUndefined();
  });

  it('mnemonic routes to submenu items when submenu is open', () => {
    const subA: FSMItem = { mnemonic: 'a' };
    const snap = items([plain, withSubmenu], [plain, subA]);
    const opened: KeyboardState = {
      focusedIndex: 1,
      submenuOpen: true,
      submenuFocusedIndex: 0
    };
    const r = reduce(opened, { type: 'Mnemonic', char: 'a' }, snap);
    expect(r.effect).toEqual({
      type: 'activate',
      list: 'submenu',
      index: 1
    });
  });
});

describe('reduce — state immutability', () => {
  it('does not mutate the input state object', () => {
    const snap = items([plain, plain]);
    const state = { ...INITIAL_STATE };
    const before = JSON.stringify(state);
    reduce(state, { type: 'ArrowDown' }, snap);
    expect(JSON.stringify(state)).toBe(before);
  });
});
