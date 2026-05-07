/**
 * ContextMenu component tests — open / close, action invocation,
 * advanced reveal, keyboard nav, stale target.
 */
import { fireEvent, render } from "@testing-library/svelte";
import { flushSync } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CONTEXT_MENU_STRINGS,
  MENU_ACTION_CHECKPOINT_COPY_ID,
  MENU_ACTION_CHECKPOINT_COPY_LABEL,
  MENU_ACTION_CHECKPOINT_DELETE,
  MENU_ACTION_CHECKPOINT_FORK,
  MENU_ACTION_SESSION_CHANGE_MODEL,
  MENU_ACTION_SESSION_RENAME,
  MENU_ACTION_SESSION_REOPEN,
  MENU_TARGET_CHECKPOINT,
  MENU_TARGET_SESSION,
} from "../../config";
import { _resetForTests as resetEsc } from "../../keyboard/escCascade";
import ContextMenu from "../ContextMenu.svelte";
import { _resetForTests, closeMenu, contextMenuStore, openMenu } from "../store.svelte";
import type { HandlerEntry } from "../store.svelte";

function openSessionMenu(
  opts: {
    handlers?: Record<string, HandlerEntry>;
  } = {},
): void {
  flushSync(() => {
    openMenu({
      target: MENU_TARGET_SESSION,
      x: 100,
      y: 200,
      handlers: opts.handlers ?? {},
      advancedRevealed: false,
      stale: false,
      data: null,
    });
  });
}

function openCheckpointMenu(
  opts: {
    handlers?: Record<string, HandlerEntry>;
    advanced?: boolean;
    stale?: boolean;
  } = {},
): void {
  flushSync(() => {
    openMenu({
      target: MENU_TARGET_CHECKPOINT,
      x: 100,
      y: 200,
      handlers: opts.handlers ?? {},
      advancedRevealed: opts.advanced ?? false,
      stale: opts.stale ?? false,
      data: { checkpointId: 7 },
    });
  });
}

beforeEach(() => {
  _resetForTests();
  resetEsc();
});

afterEach(() => {
  _resetForTests();
  resetEsc();
});

describe("ContextMenu", () => {
  it("renders nothing when no menu is open", () => {
    const { queryByTestId } = render(ContextMenu);
    expect(queryByTestId("context-menu")).toBeNull();
  });

  it("renders the menu at the recorded coordinates and target", () => {
    const { getByTestId } = render(ContextMenu);
    openCheckpointMenu();
    const menu = getByTestId("context-menu");
    expect(menu).toHaveAttribute("data-target", MENU_TARGET_CHECKPOINT);
    expect((menu as HTMLElement).style.left).toBe("100px");
    expect((menu as HTMLElement).style.top).toBe("200px");
  });

  it("hides advanced rows by default", () => {
    const { queryByTestId, getAllByTestId } = render(ContextMenu);
    openCheckpointMenu();
    const ids = getAllByTestId("context-menu-row").map((el) => el.getAttribute("data-action"));
    expect(ids).toContain(MENU_ACTION_CHECKPOINT_FORK);
    expect(ids).toContain(MENU_ACTION_CHECKPOINT_COPY_LABEL);
    expect(ids).not.toContain(MENU_ACTION_CHECKPOINT_COPY_ID); // advanced
    expect(queryByTestId("context-menu-advanced-caption")).toBeNull();
  });

  it("reveals advanced rows + caption when Shift was held", () => {
    const { getByTestId, getAllByTestId } = render(ContextMenu);
    openCheckpointMenu({ advanced: true });
    const ids = getAllByTestId("context-menu-row").map((el) => el.getAttribute("data-action"));
    expect(ids).toContain(MENU_ACTION_CHECKPOINT_COPY_ID);
    expect(getByTestId("context-menu-advanced-caption")).toHaveTextContent(
      CONTEXT_MENU_STRINGS.advancedRevealedCaption,
    );
  });

  it("clicking an enabled row fires the matching handler and closes", async () => {
    const fork = vi.fn();
    const { getAllByTestId, queryByTestId } = render(ContextMenu);
    openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_FORK]: fork } });
    const row = getAllByTestId("context-menu-row").find(
      (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_FORK,
    );
    expect(row).toBeDefined();
    await fireEvent.click(row as HTMLElement);
    expect(fork).toHaveBeenCalledOnce();
    expect(queryByTestId("context-menu")).toBeNull();
  });

  it("rows without a registered handler render disabled", () => {
    const { getAllByTestId } = render(ContextMenu);
    openCheckpointMenu({ handlers: {} });
    const rows = getAllByTestId("context-menu-row");
    for (const row of rows) {
      expect(row).toHaveAttribute("aria-disabled", "true");
    }
  });

  describe("disabled-reason tooltip (gap-cycle-05-001)", () => {
    it("row gets a title attribute when the handler entry supplies a disabledReason", () => {
      const { getAllByTestId } = render(ContextMenu);
      openCheckpointMenu({
        handlers: {
          [MENU_ACTION_CHECKPOINT_FORK]: { disabledReason: "Cannot fork — no checkpoint yet" },
        },
      });
      const forkRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_FORK,
      );
      expect(forkRow).toBeDefined();
      expect(forkRow).toHaveAttribute("title", "Cannot fork — no checkpoint yet");
    });

    it("row has no title attribute when the action is disabled by omission (absent from handler map)", () => {
      const { getAllByTestId } = render(ContextMenu);
      // No handler for FORK → disabled by omission, no tooltip.
      openCheckpointMenu({ handlers: {} });
      const forkRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_FORK,
      );
      expect(forkRow).toBeDefined();
      expect(forkRow).not.toHaveAttribute("title");
    });

    it("row with disabledReason is aria-disabled and clicking it does not fire a handler", async () => {
      const fork = vi.fn();
      const { getAllByTestId } = render(ContextMenu);
      openCheckpointMenu({
        handlers: {
          [MENU_ACTION_CHECKPOINT_FORK]: { disabledReason: "Not available" },
          // Register a real handler for a different action so the menu isn't
          // entirely empty of callable entries.
          [MENU_ACTION_CHECKPOINT_COPY_LABEL]: fork,
        },
      });
      const forkRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_FORK,
      );
      expect(forkRow).toHaveAttribute("aria-disabled", "true");
      await fireEvent.click(forkRow as HTMLElement);
      // The stub fn registered on a different action must not have been called.
      expect(fork).not.toHaveBeenCalled();
      // Menu stays open — no handler fired, so closeMenu was not called.
      expect(contextMenuStore.open).not.toBeNull();
    });
  });

  it("backdrop click closes the menu", async () => {
    const { getByTestId, queryByTestId } = render(ContextMenu);
    openCheckpointMenu();
    await fireEvent.click(getByTestId("context-menu-backdrop"));
    expect(queryByTestId("context-menu")).toBeNull();
  });

  it("stale target greys every action and shows the explanation", () => {
    const handlers = {
      [MENU_ACTION_CHECKPOINT_FORK]: vi.fn(),
      [MENU_ACTION_CHECKPOINT_DELETE]: vi.fn(),
    };
    const { getByTestId, getAllByTestId } = render(ContextMenu);
    openCheckpointMenu({ handlers, stale: true });
    expect(getByTestId("context-menu-stale-caption")).toHaveTextContent(
      CONTEXT_MENU_STRINGS.staleTargetMessage,
    );
    const rows = getAllByTestId("context-menu-row");
    for (const row of rows) {
      expect(row).toHaveAttribute("aria-disabled", "true");
    }
  });

  it("ArrowDown / Enter activates the highlighted row via keyboard", async () => {
    const fork = vi.fn();
    render(ContextMenu);
    openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_FORK]: fork } });

    // Highlight defaults to index 0 — Fork. Pressing Enter activates it.
    await fireEvent.keyDown(window, { key: "Enter" });
    expect(fork).toHaveBeenCalledOnce();
  });

  it("destructive action label has the destructive marker", () => {
    const { getAllByTestId } = render(ContextMenu);
    openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_DELETE]: vi.fn() } });
    const deleteRow = getAllByTestId("context-menu-row").find(
      (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_DELETE,
    );
    expect(deleteRow).toHaveAttribute("data-destructive", "true");
  });

  it("openMenu replaces an already-open menu (single-menu invariant)", () => {
    render(ContextMenu);
    openCheckpointMenu();
    openMenu({
      target: MENU_TARGET_CHECKPOINT,
      x: 50,
      y: 60,
      handlers: {},
      advancedRevealed: false,
      stale: false,
      data: null,
    });
    expect(contextMenuStore.open?.x).toBe(50);
    closeMenu();
  });

  describe("mnemonic navigation", () => {
    it("pressing a mnemonic letter jumps the highlight to the matching action", async () => {
      const { getAllByTestId } = render(ContextMenu);
      // CHECKPOINT_FORK → "Fork from here" → mnemonic 'f'
      openCheckpointMenu();

      await fireEvent.keyDown(window, { key: "f" });

      const forkRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_FORK,
      );
      expect(forkRow).toHaveClass("context-menu__row--highlighted");
    });

    it("repeat mnemonic press cycles through multiple matching actions", async () => {
      const { getAllByTestId } = render(ContextMenu);
      // SESSION: 'r' matches "Rename…" (flat section edit) then "Reopen session" (organize).
      // Section order: navigate → create → edit → copy → organize → destructive.
      // Flat indices: Rename is in edit (idx 3), Reopen is in organize (idx 10).
      openSessionMenu();

      await fireEvent.keyDown(window, { key: "r" });
      let renameRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_SESSION_RENAME,
      );
      expect(renameRow).toHaveClass("context-menu__row--highlighted");

      await fireEvent.keyDown(window, { key: "r" });
      let reopenRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_SESSION_REOPEN,
      );
      expect(reopenRow).toHaveClass("context-menu__row--highlighted");

      // Third press wraps back to Rename.
      await fireEvent.keyDown(window, { key: "r" });
      renameRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_SESSION_RENAME,
      );
      expect(renameRow).toHaveClass("context-menu__row--highlighted");
    });

    it("mnemonic key press has no effect when the menu is closed", async () => {
      const { queryByTestId } = render(ContextMenu);
      // No menu open — pressing a letter must not throw or open the menu.
      await fireEvent.keyDown(window, { key: "f" });
      expect(queryByTestId("context-menu")).toBeNull();
    });

    it("mnemonic char is rendered underlined in the action label", () => {
      const { getAllByTestId } = render(ContextMenu);
      openCheckpointMenu();
      const forkRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_FORK,
      );
      // "Fork from here" — first char 'F' should be inside a <u> element.
      const underlined = forkRow?.querySelector("u.context-menu__mnemonic");
      expect(underlined).toBeTruthy();
      expect(underlined?.textContent).toBe("F");
    });

    it("uppercase and lowercase key presses both match the same mnemonic", async () => {
      const { getAllByTestId } = render(ContextMenu);
      openCheckpointMenu();

      // Pressing capital 'F' should also jump to CHECKPOINT_FORK.
      await fireEvent.keyDown(window, { key: "F" });
      const forkRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_FORK,
      );
      expect(forkRow).toHaveClass("context-menu__row--highlighted");
    });
  });

  describe("DOM focus management", () => {
    // Checkpoint non-advanced flat order (primary → copy → destructive):
    //   0 = FORK, 1 = COPY_LABEL, 2 = DELETE

    it("first action row receives DOM focus when the menu opens", () => {
      const { getAllByTestId } = render(ContextMenu);
      openCheckpointMenu();
      const rows = getAllByTestId("context-menu-row");
      expect(document.activeElement).toBe(rows[0]);
    });

    it("ArrowDown moves DOM focus to the next row", async () => {
      const { getAllByTestId } = render(ContextMenu);
      openCheckpointMenu();

      await fireEvent.keyDown(window, { key: "ArrowDown" });

      const rows = getAllByTestId("context-menu-row");
      // Flat index 0 → 1 (FORK → COPY_LABEL)
      expect(document.activeElement).toBe(rows[1]);
    });

    it("ArrowUp wraps DOM focus to the last row when on the first row", async () => {
      const { getAllByTestId } = render(ContextMenu);
      openCheckpointMenu();

      await fireEvent.keyDown(window, { key: "ArrowUp" });

      const rows = getAllByTestId("context-menu-row");
      // Wraps from index 0 to last (DELETE)
      expect(document.activeElement).toBe(rows[rows.length - 1]);
    });

    it("mnemonic navigation moves DOM focus to the matching row", async () => {
      const { getAllByTestId } = render(ContextMenu);
      openCheckpointMenu();

      // 'c' → COPY_LABEL ("Copy label") — flat index 1
      await fireEvent.keyDown(window, { key: "c" });

      const copyRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_COPY_LABEL,
      );
      expect(copyRow).toBeDefined();
      expect(document.activeElement).toBe(copyRow);
    });

    it("closing the menu restores DOM focus to the element focused before opening", () => {
      const trigger = document.createElement("button");
      document.body.appendChild(trigger);
      trigger.focus();

      render(ContextMenu);
      openCheckpointMenu(); // savedFocus = trigger; first row focused

      flushSync(() => {
        closeMenu();
      });

      expect(document.activeElement).toBe(trigger);
      trigger.remove();
    });

    it("Enter on a focused row fires the handler exactly once (no double-handling)", async () => {
      const fork = vi.fn();
      const { getAllByTestId } = render(ContextMenu);
      openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_FORK]: fork } });

      // First row (FORK) is focused after open. Fire Enter directly on it —
      // the <li> handler activates and stopPropagation prevents the <ul>
      // onkeydown from also calling handleKeyDown(Enter).
      const forkRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_FORK,
      )!;
      await fireEvent.keyDown(forkRow, { key: "Enter" });

      expect(fork).toHaveBeenCalledOnce();
    });
  });

  describe("Home / End keyboard navigation", () => {
    // Checkpoint non-advanced flat order (primary → copy → destructive):
    //   0 = FORK, 1 = COPY_LABEL, 2 = DELETE

    it("Home key highlights and focuses the first enabled action", async () => {
      const { getAllByTestId } = render(ContextMenu);
      openCheckpointMenu({
        handlers: {
          [MENU_ACTION_CHECKPOINT_FORK]: vi.fn(),
          [MENU_ACTION_CHECKPOINT_COPY_LABEL]: vi.fn(),
          [MENU_ACTION_CHECKPOINT_DELETE]: vi.fn(),
        },
      });

      // Move highlight away from index 0 first.
      await fireEvent.keyDown(window, { key: "ArrowDown" });
      await fireEvent.keyDown(window, { key: "ArrowDown" });

      // Home must jump back to index 0 (FORK).
      await fireEvent.keyDown(window, { key: "Home" });
      const rows = getAllByTestId("context-menu-row");
      expect(document.activeElement).toBe(rows[0]);
      expect(rows[0]).toHaveClass("context-menu__row--highlighted");
    });

    it("End key highlights and focuses the last enabled action", async () => {
      const { getAllByTestId } = render(ContextMenu);
      openCheckpointMenu({
        handlers: {
          [MENU_ACTION_CHECKPOINT_FORK]: vi.fn(),
          [MENU_ACTION_CHECKPOINT_COPY_LABEL]: vi.fn(),
          [MENU_ACTION_CHECKPOINT_DELETE]: vi.fn(),
        },
      });

      await fireEvent.keyDown(window, { key: "End" });
      const rows = getAllByTestId("context-menu-row");
      // Last row is DELETE at index 2.
      expect(document.activeElement).toBe(rows[2]);
      expect(rows[2]).toHaveClass("context-menu__row--highlighted");
    });

    it("Home skips leading disabled rows and lands on the first enabled action", async () => {
      const { getAllByTestId } = render(ContextMenu);
      // FORK disabled (no handler), COPY_LABEL and DELETE enabled.
      openCheckpointMenu({
        handlers: {
          [MENU_ACTION_CHECKPOINT_COPY_LABEL]: vi.fn(),
          [MENU_ACTION_CHECKPOINT_DELETE]: vi.fn(),
        },
      });

      // Move to End first so we are not already at index 0.
      await fireEvent.keyDown(window, { key: "End" });
      // Home → first enabled is COPY_LABEL at flat index 1 (FORK at 0 is disabled).
      await fireEvent.keyDown(window, { key: "Home" });
      const rows = getAllByTestId("context-menu-row");
      expect(document.activeElement).toBe(rows[1]);
      expect(rows[1]).toHaveClass("context-menu__row--highlighted");
      expect(rows[0]).not.toHaveClass("context-menu__row--highlighted");
    });

    it("End skips trailing disabled rows and lands on the last enabled action", async () => {
      const { getAllByTestId } = render(ContextMenu);
      // FORK and COPY_LABEL enabled; DELETE disabled (no handler).
      openCheckpointMenu({
        handlers: {
          [MENU_ACTION_CHECKPOINT_FORK]: vi.fn(),
          [MENU_ACTION_CHECKPOINT_COPY_LABEL]: vi.fn(),
        },
      });

      await fireEvent.keyDown(window, { key: "End" });
      const rows = getAllByTestId("context-menu-row");
      // Last enabled is COPY_LABEL at flat index 1; DELETE at 2 is disabled.
      expect(document.activeElement).toBe(rows[1]);
      expect(rows[1]).toHaveClass("context-menu__row--highlighted");
      expect(rows[2]).not.toHaveClass("context-menu__row--highlighted");
    });

    it("Home has no effect when all actions are disabled (no crash)", async () => {
      render(ContextMenu);
      openCheckpointMenu({ handlers: {} }); // all disabled

      // Should not throw; menu stays open.
      await fireEvent.keyDown(window, { key: "Home" });
      expect(contextMenuStore.open).not.toBeNull();
    });

    it("End has no effect when all actions are disabled (no crash)", async () => {
      render(ContextMenu);
      openCheckpointMenu({ handlers: {} }); // all disabled

      await fireEvent.keyDown(window, { key: "End" });
      expect(contextMenuStore.open).not.toBeNull();
    });
  });

  describe("central destructive-confirmation bridge (gap-cycle-05-003)", () => {
    it("clicking a destructive action with a plain handler shows ConfirmDialog, not calling handler yet", async () => {
      const del = vi.fn();
      const { getAllByTestId, queryByTestId } = render(ContextMenu);
      openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_DELETE]: del } });

      const deleteRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_DELETE,
      );
      expect(deleteRow).toBeDefined();
      await fireEvent.click(deleteRow as HTMLElement);

      // Menu must have closed.
      expect(queryByTestId("context-menu")).toBeNull();
      // ConfirmDialog must be open.
      expect(queryByTestId("confirm-dialog")).not.toBeNull();
      // Handler must NOT have fired yet.
      expect(del).not.toHaveBeenCalled();
    });

    it("clicking Confirm in the central bridge fires the handler and closes the dialog", async () => {
      const del = vi.fn();
      const { getAllByTestId, queryByTestId, getByTestId } = render(ContextMenu);
      openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_DELETE]: del } });

      const deleteRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_DELETE,
      );
      await fireEvent.click(deleteRow as HTMLElement);
      expect(queryByTestId("confirm-dialog")).not.toBeNull();

      await fireEvent.click(getByTestId("confirm-dialog-confirm"));
      expect(del).toHaveBeenCalledOnce();
      expect(queryByTestId("confirm-dialog")).toBeNull();
    });

    it("clicking Cancel in the central bridge skips the handler", async () => {
      const del = vi.fn();
      const { getAllByTestId, queryByTestId, getByTestId } = render(ContextMenu);
      openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_DELETE]: del } });

      const deleteRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_DELETE,
      );
      await fireEvent.click(deleteRow as HTMLElement);

      await fireEvent.click(getByTestId("confirm-dialog-cancel"));
      expect(del).not.toHaveBeenCalled();
      expect(queryByTestId("confirm-dialog")).toBeNull();
    });

    it("Esc on the confirm-dialog-backdrop skips the handler", async () => {
      const del = vi.fn();
      const { getAllByTestId, queryByTestId } = render(ContextMenu);
      openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_DELETE]: del } });

      const deleteRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_DELETE,
      );
      await fireEvent.click(deleteRow as HTMLElement);
      expect(queryByTestId("confirm-dialog")).not.toBeNull();

      await fireEvent.keyDown(queryByTestId("confirm-dialog-backdrop") as HTMLElement, {
        key: "Escape",
      });
      expect(del).not.toHaveBeenCalled();
      expect(queryByTestId("confirm-dialog")).toBeNull();
    });

    it("destructive action with { handler, confirmMessage } shows the custom message", async () => {
      const del = vi.fn();
      const { getAllByTestId, getByTestId } = render(ContextMenu);
      openCheckpointMenu({
        handlers: {
          [MENU_ACTION_CHECKPOINT_DELETE]: {
            handler: del,
            confirmMessage: 'Delete checkpoint "my-cp"?',
            confirmLabel: "Delete",
          },
        },
      });

      const deleteRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_DELETE,
      );
      await fireEvent.click(deleteRow as HTMLElement);

      expect(getByTestId("confirm-dialog-message")).toHaveTextContent(
        'Delete checkpoint "my-cp"?',
      );
      expect(getByTestId("confirm-dialog-confirm")).toHaveTextContent("Delete");
    });

    it("destructive action with skipMenuConfirm fires handler directly without showing dialog", async () => {
      const del = vi.fn();
      const { getAllByTestId, queryByTestId } = render(ContextMenu);
      openCheckpointMenu({
        handlers: {
          [MENU_ACTION_CHECKPOINT_DELETE]: {
            handler: del,
            skipMenuConfirm: true,
          },
        },
      });

      const deleteRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_DELETE,
      );
      await fireEvent.click(deleteRow as HTMLElement);

      // Handler fires immediately, no dialog.
      expect(del).toHaveBeenCalledOnce();
      expect(queryByTestId("confirm-dialog")).toBeNull();
      expect(queryByTestId("context-menu")).toBeNull();
    });

    it("non-destructive action with { handler } fires directly without showing dialog", async () => {
      const fork = vi.fn();
      const { getAllByTestId, queryByTestId } = render(ContextMenu);
      openCheckpointMenu({
        handlers: {
          [MENU_ACTION_CHECKPOINT_FORK]: { handler: fork },
        },
      });

      const forkRow = getAllByTestId("context-menu-row").find(
        (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_FORK,
      );
      await fireEvent.click(forkRow as HTMLElement);

      expect(fork).toHaveBeenCalledOnce();
      expect(queryByTestId("confirm-dialog")).toBeNull();
    });
  });

  describe("don't-ask-again suppression (gap-cycle-10-004)", () => {
    it("unticked confirm fires handler without suppressing; second invocation shows dialog again", async () => {
      const del = vi.fn();
      const { getAllByTestId, queryByTestId, getByTestId, unmount } = render(ContextMenu);

      // First invocation — open dialog.
      openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_DELETE]: del } });
      const deleteRow = () =>
        getAllByTestId("context-menu-row").find(
          (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_DELETE,
        )!;
      await fireEvent.click(deleteRow());
      expect(queryByTestId("confirm-dialog")).not.toBeNull();

      // Confirm WITHOUT ticking the checkbox.
      await fireEvent.click(getByTestId("confirm-dialog-confirm"));
      expect(del).toHaveBeenCalledOnce();
      expect(queryByTestId("confirm-dialog")).toBeNull();

      // Second invocation — dialog must appear again (no suppression recorded).
      openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_DELETE]: del } });
      await fireEvent.click(deleteRow());
      expect(queryByTestId("confirm-dialog")).not.toBeNull();

      unmount();
    });

    it("ticked confirm adds action to suppression set; second invocation skips dialog and fires handler directly", async () => {
      const del = vi.fn();
      const { getAllByTestId, queryByTestId, getByTestId, unmount } = render(ContextMenu);

      // First invocation — open dialog.
      openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_DELETE]: del } });
      const deleteRow = () =>
        getAllByTestId("context-menu-row").find(
          (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_DELETE,
        )!;
      await fireEvent.click(deleteRow());
      expect(queryByTestId("confirm-dialog")).not.toBeNull();

      // Tick "Don't ask again" then confirm.
      const checkbox = getByTestId("confirm-dialog-suppress-checkbox") as HTMLInputElement;
      await fireEvent.click(checkbox);
      expect(checkbox.checked).toBe(true);
      await fireEvent.click(getByTestId("confirm-dialog-confirm"));
      expect(del).toHaveBeenCalledOnce();
      expect(queryByTestId("confirm-dialog")).toBeNull();

      // Second invocation — suppressed: dialog must NOT appear; handler fires directly.
      openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_DELETE]: del } });
      await fireEvent.click(deleteRow());
      expect(queryByTestId("confirm-dialog")).toBeNull();
      expect(del).toHaveBeenCalledTimes(2);

      unmount();
    });

    it("cancel does NOT suppress; second invocation still shows the dialog", async () => {
      const del = vi.fn();
      const { getAllByTestId, queryByTestId, getByTestId, unmount } = render(ContextMenu);

      // First invocation — open dialog, tick checkbox, then cancel.
      openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_DELETE]: del } });
      const deleteRow = () =>
        getAllByTestId("context-menu-row").find(
          (el) => el.getAttribute("data-action") === MENU_ACTION_CHECKPOINT_DELETE,
        )!;
      await fireEvent.click(deleteRow());
      expect(queryByTestId("confirm-dialog")).not.toBeNull();

      // Tick checkbox but cancel — suppression must NOT be recorded.
      const checkbox = getByTestId("confirm-dialog-suppress-checkbox") as HTMLInputElement;
      await fireEvent.click(checkbox);
      expect(checkbox.checked).toBe(true);
      await fireEvent.click(getByTestId("confirm-dialog-cancel"));
      expect(del).not.toHaveBeenCalled();
      expect(queryByTestId("confirm-dialog")).toBeNull();

      // Second invocation — NOT suppressed; dialog appears again.
      openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_DELETE]: del } });
      await fireEvent.click(deleteRow());
      expect(queryByTestId("confirm-dialog")).not.toBeNull();

      unmount();
    });
  });

  describe("ArrowRight / ArrowLeft submenu keyboard handling", () => {
    // Session non-advanced flat order (MENU_SECTION_ORDER: primary, navigate, create,
    // edit, view, copy, organize, destructive):
    //   0 = SESSION_OPEN_IN_NEW_TAB                (navigate)
    //   1 = SESSION_DUPLICATE                      (create)
    //   2 = SESSION_SAVE_AS_TEMPLATE               (create; FORK is advanced, hidden)
    //   3 = SESSION_RENAME                         (edit)
    //   4 = SESSION_EDIT_TAGS                      (edit)
    //   5 = SESSION_CHANGE_MODEL   (edit, submenu:true)  ← target
    //   6 = SESSION_COPY_TITLE                     (copy; advanced ones hidden)
    //   7 = SESSION_PIN, 8 = SESSION_UNPIN, 9 = SESSION_ARCHIVE, 10 = SESSION_REOPEN
    //   11 = SESSION_DELETE                        (destructive)

    it("ArrowRight on a submenu row activates the action (forward-compat: no submenu rendering host)", async () => {
      const changeModel = vi.fn();
      render(ContextMenu);
      openSessionMenu({ handlers: { [MENU_ACTION_SESSION_CHANGE_MODEL]: changeModel } });

      // Navigate to flat index 5 — SESSION_CHANGE_MODEL (submenu: true).
      await fireEvent.keyDown(window, { key: "ArrowDown" }); // 0 → 1
      await fireEvent.keyDown(window, { key: "ArrowDown" }); // 1 → 2
      await fireEvent.keyDown(window, { key: "ArrowDown" }); // 2 → 3
      await fireEvent.keyDown(window, { key: "ArrowDown" }); // 3 → 4
      await fireEvent.keyDown(window, { key: "ArrowDown" }); // 4 → 5

      await fireEvent.keyDown(window, { key: "ArrowRight" });
      expect(changeModel).toHaveBeenCalledOnce();
    });

    it("ArrowRight on a non-submenu row is a no-op (handler not called, menu stays open)", async () => {
      const fork = vi.fn();
      render(ContextMenu);
      // CHECKPOINT_FORK at flat index 0 has no submenu flag.
      openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_FORK]: fork } });

      await fireEvent.keyDown(window, { key: "ArrowRight" });

      expect(fork).not.toHaveBeenCalled();
      expect(contextMenuStore.open).not.toBeNull();
    });

    it("ArrowLeft is a no-op at root menu level (menu stays open, highlight unchanged)", async () => {
      const { getAllByTestId } = render(ContextMenu);
      openCheckpointMenu();

      // Move to index 1 so we can confirm index didn't change.
      await fireEvent.keyDown(window, { key: "ArrowDown" }); // 0 → 1
      const rows = getAllByTestId("context-menu-row");
      expect(document.activeElement).toBe(rows[1]);

      await fireEvent.keyDown(window, { key: "ArrowLeft" });

      // Highlight and focus must remain on index 1; menu must stay open.
      expect(document.activeElement).toBe(rows[1]);
      expect(contextMenuStore.open).not.toBeNull();
    });
  });

  describe("editable-outside-menu auto-close guard", () => {
    it("focusin on an outside INPUT closes the menu", async () => {
      const input = document.createElement("input");
      document.body.appendChild(input);

      render(ContextMenu);
      openCheckpointMenu();
      expect(contextMenuStore.open).not.toBeNull();

      await fireEvent.focusIn(input);

      expect(contextMenuStore.open).toBeNull();
      input.remove();
    });

    it("focusin on an outside TEXTAREA closes the menu", async () => {
      const textarea = document.createElement("textarea");
      document.body.appendChild(textarea);

      render(ContextMenu);
      openCheckpointMenu();
      expect(contextMenuStore.open).not.toBeNull();

      await fireEvent.focusIn(textarea);

      expect(contextMenuStore.open).toBeNull();
      textarea.remove();
    });

    it("focusin on an outside contentEditable element closes the menu", async () => {
      const div = document.createElement("div");
      div.contentEditable = "true";
      document.body.appendChild(div);

      render(ContextMenu);
      openCheckpointMenu();
      expect(contextMenuStore.open).not.toBeNull();

      await fireEvent.focusIn(div);

      expect(contextMenuStore.open).toBeNull();
      div.remove();
    });

    it("focusin on a non-editable element outside the menu does not close it", async () => {
      const button = document.createElement("button");
      document.body.appendChild(button);

      render(ContextMenu);
      openCheckpointMenu();

      await fireEvent.focusIn(button);

      expect(contextMenuStore.open).not.toBeNull();
      button.remove();
    });

    it("keystrokes from an outside textarea are not consumed by the menu handler", async () => {
      // The checkpoint menu has 'f' as a mnemonic for FORK. Without the
      // guard a keydown(f) from a textarea would match and call
      // preventDefault, silently dropping the character.
      const textarea = document.createElement("textarea");
      document.body.appendChild(textarea);

      render(ContextMenu);
      openCheckpointMenu();

      // Fire keydown from the textarea (bubbles to window).
      // If the guard works, handleKeyDown returns early without
      // calling preventDefault — dispatchEvent returns true.
      const notPrevented = await fireEvent.keyDown(textarea, { key: "f" });
      expect(notPrevented).toBe(true);

      textarea.remove();
    });

    it("arrow keys and Enter still navigate while a menu row has focus", async () => {
      const fork = vi.fn();
      const { getAllByTestId } = render(ContextMenu);
      openCheckpointMenu({ handlers: { [MENU_ACTION_CHECKPOINT_FORK]: fork } });

      // First row (FORK) is focused — fire ArrowDown from it.
      // The guard must not block navigation for elements inside the menu.
      const rows = getAllByTestId("context-menu-row");
      await fireEvent.keyDown(rows[0]!, { key: "ArrowDown" });

      // Focus should have advanced to row 1 (COPY_LABEL).
      expect(document.activeElement).toBe(rows[1]);
    });
  });
});
