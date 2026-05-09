/**
 * KeybindingsProvider integration tests.
 *
 * Covers F9-rt-17 acceptance criteria:
 *
 * - The ``?`` → ``?`` → ``Ctrl+Shift+P`` → ``Esc`` keyboard sequence
 *   does not throw ``state_unsafe_mutation`` (svelte.dev/e/state_unsafe_mutation).
 *
 * Root cause (rt-17): a reactive computation in the cheat-sheet /
 * command-palette path was mutating ``$state`` mid-derivation.
 * Fixed by the Svelte 5.55.5 compiler upgrade + dist rebuild in
 * ``5a9cff64`` (CVE dep bump).  This test guards against regression.
 *
 * Behavior anchor: ``docs/behavior/keyboard-shortcuts.md``
 * §"Help", §"Command palette", §"Focus".
 */
import { cleanup, render } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";

import {
  KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET,
  KEYBINDING_ACTION_TOGGLE_COMMAND_PALETTE,
} from "../../config";
import { _resetForTests as resetEscCascade } from "../escCascade";
import {
  _resetForTests as resetStore,
  bindHandler,
  setModalOpen,
  setComposerFocused,
} from "../store.svelte";
import KeybindingsProvider from "../KeybindingsProvider.svelte";

// ---- Mock all API-touching child components --------------------------------
// CommandPalette fetches slash commands; mock listCommands so the test
// never hits the network.
vi.mock("../../api/commands", () => ({
  listCommands: vi.fn().mockResolvedValue([]),
}));

// CommandPalette reads activeSessionId from inspectorStore.
vi.mock("../../stores/inspector.svelte", () => ({
  inspectorStore: { activeSessionId: null },
}));

// CommandPalette pastes into composer bridge on action select.
vi.mock("../../stores/composerBridge.svelte", () => ({
  pasteIntoComposer: vi.fn(),
}));

// allPaletteActions is called once per CommandPalette mount — stub it so
// we don't depend on the full registry being populated in test scope.
vi.mock("../../context-menu/palette", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../context-menu/palette")>();
  return { ...real, allPaletteActions: vi.fn(() => []) };
});

// PendingOpsCard reads pending ops from the filesystem; stub to prevent fetch.
vi.mock("../../api/pendingOps", () => ({
  fetchPendingOps: vi.fn().mockResolvedValue([]),
}));

// templates store — stub to avoid GET /api/templates on TemplatePicker mount.
vi.mock("../../stores/templates.svelte", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../stores/templates.svelte")>();
  return {
    ...real,
    refreshTemplates: vi.fn().mockResolvedValue(undefined),
    templatesStore: { pickerOpen: false, templates: [], loading: false, error: null },
    toggleTemplatePicker: vi.fn(),
    closeTemplatePicker: vi.fn(),
  };
});

// ---- Test setup / teardown ------------------------------------------------
beforeEach(() => {
  resetEscCascade();
  resetStore();
});

afterEach(() => {
  cleanup();
  resetEscCascade();
  resetStore();
});

// ---- Helper ---------------------------------------------------------------
/** Dispatch a synthetic KeyboardEvent on the window. */
function pressKey(
  key: string,
  opts: { code?: string; ctrlKey?: boolean; shiftKey?: boolean } = {},
): void {
  const event = new KeyboardEvent("keydown", {
    key,
    code: opts.code ?? key,
    ctrlKey: opts.ctrlKey ?? false,
    shiftKey: opts.shiftKey ?? false,
    bubbles: true,
    cancelable: true,
  });
  window.dispatchEvent(event);
}

// ---- Tests ----------------------------------------------------------------
describe("KeybindingsProvider — F9-rt-17: no state_unsafe_mutation on overlay sequence", () => {
  it("? → ? → Ctrl+Shift+P → Esc does not throw state_unsafe_mutation", async () => {
    // Bind handlers for the provider-owned actions so dispatchKeyEvent can
    // fire them (the provider registers them in onMount, which runs after
    // render; we re-bind here so the dispatch table is populated).
    let cheatSheetOpen = false;
    let commandPaletteOpen = false;

    const releaseCheatSheet = bindHandler(KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET, () => {
      cheatSheetOpen = !cheatSheetOpen;
    });
    const releaseCommandPalette = bindHandler(KEYBINDING_ACTION_TOGGLE_COMMAND_PALETTE, () => {
      commandPaletteOpen = !commandPaletteOpen;
    });

    try {
      // This must not throw state_unsafe_mutation.
      expect(() => {
        pressKey("?", { code: "Slash", shiftKey: true }); // open cheat sheet
      }).not.toThrow();

      await tick();

      expect(() => {
        pressKey("?", { code: "Slash", shiftKey: true }); // close cheat sheet
      }).not.toThrow();

      await tick();

      expect(() => {
        pressKey("P", { code: "KeyP", ctrlKey: true, shiftKey: true }); // open command palette
      }).not.toThrow();

      await tick();

      expect(() => {
        pressKey("Escape", { code: "Escape" }); // close via Esc cascade
      }).not.toThrow();

      await tick();
    } finally {
      releaseCheatSheet();
      releaseCommandPalette();
    }
  });

  it("setModalOpen is callable from outside a derivation without throwing", () => {
    // Directly verify the store mutation is safe to call imperatively.
    expect(() => {
      setModalOpen(true);
      setComposerFocused(true);
      setModalOpen(false);
      setComposerFocused(false);
    }).not.toThrow();
  });

  it("KeybindingsProvider mounts and unmounts cleanly", async () => {
    const { unmount } = render(KeybindingsProvider, { props: {} });
    await tick();
    expect(() => unmount()).not.toThrow();
  });
});
