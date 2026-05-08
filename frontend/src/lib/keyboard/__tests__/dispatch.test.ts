/**
 * Keybinding dispatch tests — registration / conflict resolution +
 * context routing.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  KEYBINDING_ACTION_NEW_CHAT_DEFAULTS,
  KEYBINDING_ACTION_SIDEBAR_DOWN_FORCE,
  KEYBINDING_ACTION_SIDEBAR_JUMP_PREFIX,
  KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET,
  KEYBINDING_SECTION_CREATE,
} from "../../config";
import {
  bindingAllowedInContext,
  buildRegistry,
  dispatchKeyEvent,
  lookupBindingForEvent,
} from "../dispatch";
import { _resetForTests, bindHandler, setComposerFocused, setModalOpen } from "../store.svelte";
import type { KeybindingSpec } from "../bindings";

beforeEach(() => {
  _resetForTests();
  setComposerFocused(false);
  setModalOpen(false);
});

afterEach(() => {
  _resetForTests();
});

describe("buildRegistry", () => {
  it("indexes a code-based chord", () => {
    const list: readonly KeybindingSpec[] = [
      {
        id: "x",
        chord: { code: "KeyX", display: ["X"] },
        section: KEYBINDING_SECTION_CREATE,
        global: false,
      },
    ];
    const registry = buildRegistry(list);
    expect(registry.has("code:KeyX")).toBe(true);
  });

  it("inserts both shift-on and shift-off variants for named-key chords without explicit shift", () => {
    const list: readonly KeybindingSpec[] = [
      {
        id: "qmark",
        chord: { key: "?", display: ["?"] },
        section: KEYBINDING_SECTION_CREATE,
        global: false,
      },
    ];
    const registry = buildRegistry(list);
    expect(registry.has("key:?")).toBe(true);
    expect(registry.has("shift+key:?")).toBe(true);
  });

  it("throws on a duplicate chord registration (fail-fast at boot)", () => {
    const list: readonly KeybindingSpec[] = [
      {
        id: "a",
        chord: { code: "KeyC", display: ["C"] },
        section: KEYBINDING_SECTION_CREATE,
        global: false,
      },
      {
        id: "b",
        chord: { code: "KeyC", display: ["C"] },
        section: KEYBINDING_SECTION_CREATE,
        global: false,
      },
    ];
    expect(() => buildRegistry(list)).toThrow(/Duplicate keybinding chord/);
  });

  it("skips displayOnly bindings", () => {
    const list: readonly KeybindingSpec[] = [
      {
        id: "ctrl-k",
        chord: { code: "KeyK", ctrl: true, display: ["Ctrl", "K"] },
        section: KEYBINDING_SECTION_CREATE,
        global: true,
        displayOnly: true,
      },
    ];
    const registry = buildRegistry(list);
    expect(registry.size).toBe(0);
  });
});

describe("lookupBindingForEvent", () => {
  it("matches the new-chat chord on the bare KeyC event", () => {
    const event = new KeyboardEvent("keydown", { code: "KeyC", key: "c" });
    const spec = lookupBindingForEvent(event);
    expect(spec?.id).toBe(KEYBINDING_ACTION_NEW_CHAT_DEFAULTS);
  });

  it("matches Alt+1 slot-jump via event.code", () => {
    const event = new KeyboardEvent("keydown", { code: "Digit1", key: "1", altKey: true });
    const spec = lookupBindingForEvent(event);
    expect(spec?.id).toBe(`${KEYBINDING_ACTION_SIDEBAR_JUMP_PREFIX}1`);
  });

  it("matches the cheat-sheet chord when ? is produced with Shift held", () => {
    const event = new KeyboardEvent("keydown", { code: "Slash", key: "?", shiftKey: true });
    const spec = lookupBindingForEvent(event);
    expect(spec?.id).toBe(KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET);
  });

  it("matches the cheat-sheet chord when ? is produced without Shift (alt layout)", () => {
    const event = new KeyboardEvent("keydown", { code: "IntlBackslash", key: "?" });
    const spec = lookupBindingForEvent(event);
    expect(spec?.id).toBe(KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET);
  });

  it("returns undefined for unbound chords", () => {
    const event = new KeyboardEvent("keydown", { code: "KeyZ", key: "z" });
    expect(lookupBindingForEvent(event)).toBeUndefined();
  });
});

describe("bindingAllowedInContext", () => {
  const bareLetter: KeybindingSpec = {
    id: "x",
    chord: { code: "KeyX", display: ["X"] },
    section: KEYBINDING_SECTION_CREATE,
    global: false,
  };
  const globalChord: KeybindingSpec = {
    id: "y",
    chord: { code: "KeyY", ctrl: true, shift: true, display: ["Ctrl", "Shift", "Y"] },
    section: KEYBINDING_SECTION_CREATE,
    global: true,
  };
  const modalToggle: KeybindingSpec = {
    id: "z",
    chord: { key: "?", display: ["?"] },
    section: KEYBINDING_SECTION_CREATE,
    global: false,
    allowInModalContext: true,
  };

  it("blocks bare-letter chords when composer is focused", () => {
    expect(bindingAllowedInContext(bareLetter, { composerFocused: true, modalOpen: false })).toBe(
      false,
    );
  });

  it("blocks bare-letter chords when a modal is open", () => {
    expect(bindingAllowedInContext(bareLetter, { composerFocused: false, modalOpen: true })).toBe(
      false,
    );
  });

  it("allows global chords even with composer focused or modal open", () => {
    expect(bindingAllowedInContext(globalChord, { composerFocused: true, modalOpen: true })).toBe(
      true,
    );
  });

  it("allows allowInModalContext chords even when a modal is open", () => {
    expect(bindingAllowedInContext(modalToggle, { composerFocused: false, modalOpen: true })).toBe(
      true,
    );
  });

  it("still blocks allowInModalContext chords when composer is focused", () => {
    expect(bindingAllowedInContext(modalToggle, { composerFocused: true, modalOpen: true })).toBe(
      false,
    );
  });
});

describe("dispatchKeyEvent", () => {
  it("invokes the registered handler when the chord matches and context allows", () => {
    const handler = vi.fn();
    bindHandler(KEYBINDING_ACTION_NEW_CHAT_DEFAULTS, handler);
    const event = new KeyboardEvent("keydown", { code: "KeyC", key: "c", cancelable: true });
    const fired = dispatchKeyEvent(event);
    expect(fired).toBe(KEYBINDING_ACTION_NEW_CHAT_DEFAULTS);
    expect(handler).toHaveBeenCalledOnce();
    expect(event.defaultPrevented).toBe(true);
  });

  it("does not invoke a bare-letter handler when composer is focused", () => {
    const handler = vi.fn();
    bindHandler(KEYBINDING_ACTION_NEW_CHAT_DEFAULTS, handler);
    setComposerFocused(true);
    const event = new KeyboardEvent("keydown", { code: "KeyC", key: "c" });
    expect(dispatchKeyEvent(event)).toBeUndefined();
    expect(handler).not.toHaveBeenCalled();
  });

  it("does invoke a global handler with composer focused", () => {
    const handler = vi.fn();
    bindHandler(KEYBINDING_ACTION_SIDEBAR_DOWN_FORCE, handler);
    setComposerFocused(true);
    const event = new KeyboardEvent("keydown", { key: "]", altKey: true });
    expect(dispatchKeyEvent(event)).toBe(KEYBINDING_ACTION_SIDEBAR_DOWN_FORCE);
    expect(handler).toHaveBeenCalledOnce();
  });

  it("returns undefined when no handler is bound for the matched chord", () => {
    const event = new KeyboardEvent("keydown", { code: "KeyC", key: "c" });
    expect(dispatchKeyEvent(event)).toBeUndefined();
  });

  // gap-cycle-02-003: ? must toggle (open AND close) the cheat sheet.
  it("fires the cheat-sheet toggle when no modal is open (opens the sheet)", () => {
    const handler = vi.fn();
    bindHandler(KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET, handler);
    setModalOpen(false);
    const event = new KeyboardEvent("keydown", {
      code: "Slash",
      key: "?",
      shiftKey: true,
      cancelable: true,
    });
    expect(dispatchKeyEvent(event)).toBe(KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET);
    expect(handler).toHaveBeenCalledOnce();
  });

  it("fires the cheat-sheet toggle even when modal is open (closes the sheet)", () => {
    const handler = vi.fn();
    bindHandler(KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET, handler);
    // Simulate state after the sheet has been opened: modalOpen = true.
    setModalOpen(true);
    const event = new KeyboardEvent("keydown", {
      code: "Slash",
      key: "?",
      shiftKey: true,
      cancelable: true,
    });
    expect(dispatchKeyEvent(event)).toBe(KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET);
    expect(handler).toHaveBeenCalledOnce();
  });

  it("does NOT fire bare-letter chords (c, t) while cheat-sheet modal is open", () => {
    const cHandler = vi.fn();
    bindHandler(KEYBINDING_ACTION_NEW_CHAT_DEFAULTS, cHandler);
    setModalOpen(true);
    const cEvent = new KeyboardEvent("keydown", { code: "KeyC", key: "c" });
    expect(dispatchKeyEvent(cEvent)).toBeUndefined();
    expect(cHandler).not.toHaveBeenCalled();
  });
});
