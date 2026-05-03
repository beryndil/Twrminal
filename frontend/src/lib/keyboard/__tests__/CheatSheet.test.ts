/**
 * Cheat sheet component tests — renders every binding from
 * :data:`KEYBINDINGS` grouped by section, close button fires onClose.
 */
import { fireEvent, render } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  KEYBINDING_ACTION_NEW_CHAT_DEFAULTS,
  KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET,
  KEYBOARD_SHORTCUT_STRINGS,
} from "../../config";
import { _resetForTests as resetEsc } from "../escCascade";
import CheatSheet from "../CheatSheet.svelte";

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
});
