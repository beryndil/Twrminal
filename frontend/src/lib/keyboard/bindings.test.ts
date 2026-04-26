import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  _internal,
  bindings,
  chordSegments,
  dispatchShortcut,
  groupedBindings
} from './bindings';
import { uiActions } from '$lib/stores/ui_actions.svelte';
import { palette } from '$lib/context-menu/palette.svelte';
import { contextMenu } from '$lib/context-menu/store.svelte';

const { parseChord, matches } = _internal;

function fakeEvent(init: {
  key?: string;
  code?: string;
  ctrlKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
  metaKey?: boolean;
  target?: EventTarget | null;
}): KeyboardEvent {
  // Real KeyboardEvent so `preventDefault()` works without us mocking
  // the prototype. jsdom exposes the constructor; tests run in jsdom
  // per vitest.config.ts.
  const e = new KeyboardEvent('keydown', {
    key: init.key ?? '',
    code: init.code ?? '',
    ctrlKey: init.ctrlKey ?? false,
    shiftKey: init.shiftKey ?? false,
    altKey: init.altKey ?? false,
    metaKey: init.metaKey ?? false,
    bubbles: true,
    cancelable: true
  });
  if (init.target) Object.defineProperty(e, 'target', { value: init.target });
  return e;
}

describe('parseChord', () => {
  it('splits modifiers and key', () => {
    expect(parseChord('Ctrl+Shift+P')).toEqual({
      ctrl: true,
      shift: true,
      alt: false,
      key: 'P'
    });
  });
  it('handles bare letter chords', () => {
    expect(parseChord('c')).toEqual({
      ctrl: false,
      shift: false,
      alt: false,
      key: 'c'
    });
  });
  it('handles bracket chords', () => {
    expect(parseChord('Alt+[')).toEqual({
      ctrl: false,
      shift: false,
      alt: true,
      key: '['
    });
  });
  it('rejects empty chords', () => {
    expect(() => parseChord('')).toThrow();
  });
});

describe('matches', () => {
  it('matches by physical code for letters', () => {
    expect(matches(fakeEvent({ key: 'c', code: 'KeyC' }), parseChord('c'))).toBe(
      true
    );
  });

  it('matches Shift+C only with Shift held', () => {
    const req = parseChord('Shift+C');
    expect(
      matches(fakeEvent({ key: 'C', code: 'KeyC', shiftKey: true }), req)
    ).toBe(true);
    expect(matches(fakeEvent({ key: 'c', code: 'KeyC' }), req)).toBe(false);
  });

  it('matches Alt+1 by Digit code', () => {
    expect(
      matches(
        fakeEvent({ key: '1', code: 'Digit1', altKey: true }),
        parseChord('Alt+1')
      )
    ).toBe(true);
  });

  it('matches Ctrl+Shift+P with metaKey on mac', () => {
    expect(
      matches(
        fakeEvent({
          key: 'P',
          code: 'KeyP',
          metaKey: true,
          shiftKey: true
        }),
        parseChord('Ctrl+Shift+P')
      )
    ).toBe(true);
  });

  it('rejects Ctrl modifier when chord has none', () => {
    expect(
      matches(fakeEvent({ key: 'c', code: 'KeyC', ctrlKey: true }), parseChord('c'))
    ).toBe(false);
  });

  it('matches Alt+] / Alt+[ via key', () => {
    expect(
      matches(
        fakeEvent({ key: ']', code: 'BracketRight', altKey: true }),
        parseChord('Alt+]')
      )
    ).toBe(true);
    expect(
      matches(
        fakeEvent({ key: '[', code: 'BracketLeft', altKey: true }),
        parseChord('Alt+[')
      )
    ).toBe(true);
  });

  it('matches Esc via Escape key', () => {
    expect(matches(fakeEvent({ key: 'Escape' }), parseChord('Esc'))).toBe(true);
  });
});

describe('groupedBindings', () => {
  it('preserves registry order within groups', () => {
    const groups = groupedBindings();
    const groupNames = groups.map((g) => g.group);
    // Create comes before Navigate; Navigate before Focus; Focus
    // before Help.
    expect(groupNames.indexOf('Create')).toBeLessThan(
      groupNames.indexOf('Navigate')
    );
    expect(groupNames.indexOf('Navigate')).toBeLessThan(
      groupNames.indexOf('Focus')
    );
  });

  it('renders all v1 picks', () => {
    const ids = bindings.map((b) => b.id);
    for (const id of [
      'create.new-chat',
      'create.new-chat-with-options',
      'create.from-template',
      'navigate.next',
      'navigate.prev',
      'navigate.bracket-next',
      'navigate.bracket-prev',
      'focus.escape',
      'palette.toggle',
      'help.cheat-sheet'
    ]) {
      expect(ids).toContain(id);
    }
    // Alt+1..9 generator
    for (let n = 1; n <= 9; n++) {
      expect(ids).toContain(`navigate.jump-${n}`);
    }
  });
});

describe('chordSegments', () => {
  it('splits chords on +', () => {
    expect(chordSegments('Ctrl+Shift+P')).toEqual(['Ctrl', 'Shift', 'P']);
    expect(chordSegments('c')).toEqual(['c']);
    expect(chordSegments('Alt+[')).toEqual(['Alt', '[']);
  });
});

describe('dispatchShortcut', () => {
  beforeEach(() => {
    // Reset overlay state between tests so dispatch consequences are
    // deterministic.
    uiActions.cheatSheetOpen = false;
    uiActions.newSessionOpen = false;
    uiActions.newSessionFresh = false;
    uiActions.templatePickerOpen = false;
    palette.hide();
    contextMenu.close();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns false when no binding matches', () => {
    const e = fakeEvent({ key: 'q', code: 'KeyQ' });
    expect(dispatchShortcut(e)).toBe(false);
  });

  it('opens the new-session form on bare `c`', () => {
    const e = fakeEvent({ key: 'c', code: 'KeyC' });
    expect(dispatchShortcut(e)).toBe(true);
    expect(uiActions.newSessionOpen).toBe(true);
    expect(uiActions.newSessionFresh).toBe(false);
  });

  it('flags fresh on Shift+C', () => {
    const e = fakeEvent({ key: 'C', code: 'KeyC', shiftKey: true });
    expect(dispatchShortcut(e)).toBe(true);
    expect(uiActions.newSessionOpen).toBe(true);
    expect(uiActions.newSessionFresh).toBe(true);
  });

  it('opens template picker on `t`', () => {
    const e = fakeEvent({ key: 't', code: 'KeyT' });
    expect(dispatchShortcut(e)).toBe(true);
    expect(uiActions.templatePickerOpen).toBe(true);
  });

  it('toggles cheatsheet on `?`', () => {
    const e = fakeEvent({ key: '?', shiftKey: true });
    // Shift is required to type `?` on a US layout; the chord is
    // declared bare-`?` which means "key === '?'", so a Shift modifier
    // must NOT be required to match. Confirm both branches.
    expect(dispatchShortcut(e)).toBe(false); // Shift held → mismatch
    expect(uiActions.cheatSheetOpen).toBe(false);

    const e2 = fakeEvent({ key: '?' });
    expect(dispatchShortcut(e2)).toBe(true);
    expect(uiActions.cheatSheetOpen).toBe(true);
  });

  it('skips bare-letter bindings when an input is focused', () => {
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    const e = fakeEvent({
      key: 'c',
      code: 'KeyC',
      target: input
    });
    expect(dispatchShortcut(e)).toBe(false);
    expect(uiActions.newSessionOpen).toBe(false);
    input.remove();
  });

  it('still fires global bindings inside an input', () => {
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    const e = fakeEvent({
      key: 'P',
      code: 'KeyP',
      ctrlKey: true,
      shiftKey: true,
      target: input
    });
    expect(dispatchShortcut(e)).toBe(true);
    expect(palette.open).toBe(true);
    input.remove();
  });

  it('Esc closes the context menu before any other overlay', () => {
    // Wedge fix (2026-04-26): the context menu's document-capture
    // keydown listener swallows alphanumerics from focused fields,
    // so its open state must close ahead of every other overlay.
    contextMenu.open(
      { type: 'session', id: 'sess-1' },
      0,
      0,
      false
    );
    palette.show();
    uiActions.cheatSheetOpen = true;
    const e = fakeEvent({ key: 'Escape' });
    expect(dispatchShortcut(e)).toBe(true);
    expect(contextMenu.state.open).toBe(false);
    // Lower-priority overlays untouched on the same Esc.
    expect(palette.open).toBe(true);
    expect(uiActions.cheatSheetOpen).toBe(true);
  });

  it('Esc closes context menu even when an input is focused', () => {
    // The wedge: a programmatic textarea.focus() leaves the menu open
    // with focus on the textarea. The menu's own Esc handler defers to
    // the focused field, so without bindings handleEscape closing the
    // menu, Esc would never dismiss it.
    contextMenu.open(
      { type: 'session', id: 'sess-1' },
      0,
      0,
      false
    );
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    const e = fakeEvent({ key: 'Escape', target: input });
    expect(dispatchShortcut(e)).toBe(true);
    expect(contextMenu.state.open).toBe(false);
    input.remove();
  });

  it('Esc dismisses the highest-priority overlay first', () => {
    uiActions.cheatSheetOpen = true;
    uiActions.newSessionOpen = true;
    palette.show();
    const e = fakeEvent({ key: 'Escape' });
    expect(dispatchShortcut(e)).toBe(true);
    // Palette closed first.
    expect(palette.open).toBe(false);
    // Other overlays still open.
    expect(uiActions.cheatSheetOpen).toBe(true);
    expect(uiActions.newSessionOpen).toBe(true);

    const e2 = fakeEvent({ key: 'Escape' });
    dispatchShortcut(e2);
    expect(uiActions.cheatSheetOpen).toBe(false);
    expect(uiActions.newSessionOpen).toBe(false);
  });

  it('Esc blurs a focused input when no overlay is open', () => {
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    expect(document.activeElement).toBe(input);
    const e = fakeEvent({ key: 'Escape', target: input });
    expect(dispatchShortcut(e)).toBe(true);
    expect(document.activeElement).not.toBe(input);
    input.remove();
  });

  it('chord-conflict guard fired at import (sanity check)', () => {
    // Re-import would re-run the module init and re-validate; if the
    // module is in cache it skips. The fact that this test file's
    // import succeeded means the guard didn't trip — covered.
    expect(bindings.length).toBeGreaterThan(0);
  });
});
