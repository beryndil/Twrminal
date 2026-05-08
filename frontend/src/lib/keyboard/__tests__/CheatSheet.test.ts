/**
 * Cheat sheet component tests — renders every binding from
 * :data:`KEYBINDINGS` grouped by section, renders non-registry context
 * sections from :data:`NON_REGISTRY_SECTIONS`, close button fires onClose.
 */
import { fireEvent, render } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  KEYBINDING_ACTION_NEW_CHAT_DEFAULTS,
  KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET,
  KEYBINDING_ACTION_TOGGLE_COMMAND_PALETTE,
  KEYBOARD_SHORTCUT_STRINGS,
} from "../../config";
import { _resetForTests as resetEsc } from "../escCascade";
import CheatSheet from "../CheatSheet.svelte";
import { NON_REGISTRY_SECTIONS } from "../nonRegistryBindings";

beforeEach(() => {
  resetEsc();
});

afterEach(() => {
  resetEsc();
});

describe("CheatSheet", () => {
  it("renders nothing when closed", () => {
    const { queryByTestId } = render(CheatSheet, {
      props: { open: false, onClose: vi.fn() },
    });
    expect(queryByTestId("cheat-sheet")).toBeNull();
  });

  it("renders the dialog and the title when open", () => {
    const { getByTestId } = render(CheatSheet, {
      props: { open: true, onClose: vi.fn() },
    });
    expect(getByTestId("cheat-sheet")).toBeInTheDocument();
    expect(getByTestId("cheat-sheet")).toHaveAttribute(
      "aria-label",
      KEYBOARD_SHORTCUT_STRINGS.cheatSheetAriaLabel,
    );
  });

  it("renders one row per registered binding", () => {
    const { getAllByTestId } = render(CheatSheet, {
      props: { open: true, onClose: vi.fn() },
    });
    const rows = getAllByTestId("cheat-sheet-row");
    // Sanity check: at least the three Create chords + Esc are in the v1 table.
    const ids = rows.map((r) => r.getAttribute("data-action"));
    expect(ids).toContain(KEYBINDING_ACTION_NEW_CHAT_DEFAULTS);
    expect(ids).toContain(KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET);
  });

  it("renders ⌘/Ctrl glyph for Ctrl-prefixed chords (Mac equivalence)", () => {
    const { getAllByTestId } = render(CheatSheet, {
      props: { open: true, onClose: vi.fn() },
    });
    // Find the row for the command-palette toggle (Ctrl+Shift+P).
    const rows = getAllByTestId("cheat-sheet-row");
    const cpRow = rows.find(
      (r) => r.getAttribute("data-action") === KEYBINDING_ACTION_TOGGLE_COMMAND_PALETTE,
    );
    expect(cpRow).toBeDefined();
    // The rendered chord caps must include the Mac equivalence glyph.
    const chordEl = cpRow!.querySelector('[data-testid="cheat-sheet-chord"]');
    expect(chordEl).toBeDefined();
    expect(chordEl!.textContent).toContain("⌘");
  });

  it("close button fires onClose", async () => {
    const onClose = vi.fn();
    const { getByTestId } = render(CheatSheet, { props: { open: true, onClose } });
    await fireEvent.click(getByTestId("cheat-sheet-close"));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("backdrop click fires onClose", async () => {
    const onClose = vi.fn();
    const { getByTestId } = render(CheatSheet, { props: { open: true, onClose } });
    await fireEvent.click(getByTestId("cheat-sheet-backdrop"));
    expect(onClose).toHaveBeenCalledOnce();
  });

  describe("non-registry sections", () => {
    it("renders the Conversation section with at least one row", () => {
      const { getAllByTestId } = render(CheatSheet, {
        props: { open: true, onClose: vi.fn() },
      });
      const sections = getAllByTestId("cheat-sheet-section");
      const conversationSection = sections.find(
        (s) => s.getAttribute("data-section") === "conversation",
      );
      expect(conversationSection).toBeDefined();
      const rows = conversationSection!.querySelectorAll('[data-testid="cheat-sheet-row"]');
      expect(rows.length).toBeGreaterThanOrEqual(1);
    });

    it("renders the Context menu section with at least one row", () => {
      const { getAllByTestId } = render(CheatSheet, {
        props: { open: true, onClose: vi.fn() },
      });
      const sections = getAllByTestId("cheat-sheet-section");
      const contextMenuSection = sections.find(
        (s) => s.getAttribute("data-section") === "context_menu",
      );
      expect(contextMenuSection).toBeDefined();
      const rows = contextMenuSection!.querySelectorAll('[data-testid="cheat-sheet-row"]');
      expect(rows.length).toBeGreaterThanOrEqual(1);
    });

    it("renders the Checklist section with at least one row", () => {
      const { getAllByTestId } = render(CheatSheet, {
        props: { open: true, onClose: vi.fn() },
      });
      const sections = getAllByTestId("cheat-sheet-section");
      const checklistSection = sections.find((s) => s.getAttribute("data-section") === "checklist");
      expect(checklistSection).toBeDefined();
      const rows = checklistSection!.querySelectorAll('[data-testid="cheat-sheet-row"]');
      expect(rows.length).toBeGreaterThanOrEqual(1);
    });

    it("renders all three non-registry sections defined in NON_REGISTRY_SECTIONS", () => {
      const { getAllByTestId } = render(CheatSheet, {
        props: { open: true, onClose: vi.fn() },
      });
      const sections = getAllByTestId("cheat-sheet-section");
      const sectionIds = sections.map((s) => s.getAttribute("data-section"));
      for (const group of NON_REGISTRY_SECTIONS) {
        expect(sectionIds).toContain(group.id);
      }
    });

    it("Conversation section includes Enter (send) and Shift+Enter (newline) rows", () => {
      const { getAllByTestId } = render(CheatSheet, {
        props: { open: true, onClose: vi.fn() },
      });
      const sections = getAllByTestId("cheat-sheet-section");
      const conversationSection = sections.find(
        (s) => s.getAttribute("data-section") === "conversation",
      );
      expect(conversationSection).toBeDefined();
      const text = conversationSection!.textContent ?? "";
      expect(text).toContain("Send message");
      expect(text).toContain("Insert newline");
    });
  });
});
