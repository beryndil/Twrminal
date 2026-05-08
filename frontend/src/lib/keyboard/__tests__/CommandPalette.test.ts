/**
 * CommandPalette.svelte — unit tests.
 *
 * Covers the acceptance criteria from gap-cycle-01-003:
 *
 * - Toggle on chord (open prop).
 * - Fuzzy filter by label and id.
 * - Activate on Enter — calls the registered palette handler.
 * - Close on Esc.
 * - Backdrop click closes.
 *
 * Also covers gap-cycle-02-006:
 *
 * - Esc cascade closes the palette regardless of focus owner.
 * - Priority-1 (context menu) preempts the palette when both open.
 *
 * Also covers gap-cycle-13-005:
 *
 * - Slash commands are fetched from ``listCommands`` with the active
 *   session's ``workingDir``.
 * - Changing ``workingDir`` (session switch) triggers a re-fetch.
 *
 * Behavior anchor: ``docs/behavior/keyboard-shortcuts.md``
 * §"Command palette", §"Focus".
 * ``docs/behavior/chat.md`` §"Per-session project command scoping".
 */
import { cleanup, fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CommandPalette from "../CommandPalette.svelte";
import { registerPaletteHandler, _resetPaletteHandlers } from "../../context-menu/palette";
import {
  ESC_PRIORITY_CONTEXT_MENU,
  _resetForTests as resetEscCascade,
  registerEscEntry,
  runEscCascade,
} from "../escCascade";

// ---- mock listCommands so tests never hit the network -------------------
// vi.mock factories are hoisted; use vi.hoisted to keep the ref available.
const { mockListCommands, mockPasteIntoComposer } = vi.hoisted(() => ({
  mockListCommands:
    vi.fn<
      (cwd?: string | null) => Promise<{ name: string; description: string; source: string }[]>
    >(),
  mockPasteIntoComposer: vi.fn(),
}));

vi.mock("../../api/commands", () => ({
  listCommands: mockListCommands,
}));

// ---- mock inspectorStore (CommandPalette reads activeSessionId) ----------
vi.mock("../../stores/inspector.svelte", () => ({
  inspectorStore: { activeSessionId: "test-session-id" },
}));

// ---- mock pasteIntoComposer (CommandPalette writes here on cmd select) --
vi.mock("../../stores/composerBridge.svelte", () => ({
  pasteIntoComposer: mockPasteIntoComposer,
}));

// ---- mock allPaletteActions so tests don't depend on the full registry ----
vi.mock("../../context-menu/palette", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../context-menu/palette")>();
  return {
    ...real,
    allPaletteActions: vi.fn(() => [
      { id: "session.rename", label: "Rename…" },
      { id: "session.copy_id", label: "Copy session ID" },
      { id: "message.copy_content", label: "Copy message text" },
    ]),
  };
});

beforeEach(() => {
  resetEscCascade();
  _resetPaletteHandlers();
  mockListCommands.mockReset();
  mockListCommands.mockResolvedValue([]);
  mockPasteIntoComposer.mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  resetEscCascade();
  _resetPaletteHandlers();
});

describe("CommandPalette", () => {
  it("renders nothing when closed", () => {
    const { queryByTestId } = render(CommandPalette, {
      props: { open: false, onClose: vi.fn() },
    });
    expect(queryByTestId("command-palette-panel")).toBeNull();
  });

  it("renders the panel when open", () => {
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose: vi.fn() },
    });
    expect(getByTestId("command-palette-panel")).toBeTruthy();
  });

  it("shows all actions when query is empty", () => {
    const { getAllByTestId } = render(CommandPalette, {
      props: { open: true, onClose: vi.fn() },
    });
    const items = getAllByTestId("command-palette-item");
    expect(items.length).toBe(3);
  });

  it("filters by label (case-insensitive)", async () => {
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose: vi.fn() },
    });
    const input = getByTestId("command-palette-search");
    await fireEvent.input(input, { target: { value: "rename" } });

    const items = getByTestId("command-palette-list").querySelectorAll(
      "[data-testid='command-palette-item']",
    );
    expect(items.length).toBe(1);
    expect(items[0].getAttribute("data-action-id")).toBe("session.rename");
  });

  it("filters by action id (case-insensitive)", async () => {
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose: vi.fn() },
    });
    const input = getByTestId("command-palette-search");
    await fireEvent.input(input, { target: { value: "copy_id" } });

    const items = getByTestId("command-palette-list").querySelectorAll(
      "[data-testid='command-palette-item']",
    );
    expect(items.length).toBe(1);
    expect(items[0].getAttribute("data-action-id")).toBe("session.copy_id");
  });

  it("shows no-results message when filter has no matches", async () => {
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose: vi.fn() },
    });
    const input = getByTestId("command-palette-search");
    await fireEvent.input(input, { target: { value: "zzznomatch" } });
    expect(getByTestId("command-palette-no-results")).toBeTruthy();
  });

  it("Enter fires the registered palette handler and closes", async () => {
    const handler = vi.fn();
    registerPaletteHandler("session.rename", handler);

    const onClose = vi.fn();
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose },
    });

    const input = getByTestId("command-palette-search");
    // First item (session.rename) is active by default (index 0).
    await fireEvent.keyDown(input, { key: "Enter" });

    expect(handler).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("Enter with no registered handler still closes", async () => {
    // session.rename has no handler registered.
    const onClose = vi.fn();
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose },
    });

    const input = getByTestId("command-palette-search");
    await fireEvent.keyDown(input, { key: "Enter" });

    // No handler registered — palette still closes; no throw.
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("Esc closes the palette", async () => {
    const onClose = vi.fn();
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose },
    });
    const input = getByTestId("command-palette-search");
    await fireEvent.keyDown(input, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("backdrop click closes the palette", async () => {
    const onClose = vi.fn();
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose },
    });
    await fireEvent.click(getByTestId("command-palette-backdrop"));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("clicking an item fires its handler and closes", async () => {
    const handler = vi.fn();
    registerPaletteHandler("message.copy_content", handler);

    const onClose = vi.fn();
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose },
    });

    // Third item is message.copy_content.
    const items = getByTestId("command-palette-list").querySelectorAll(
      "[data-testid='command-palette-item']",
    );
    await fireEvent.click(items[2] as HTMLElement);

    expect(handler).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  // ---- gap-cycle-12-002: Home / End jump-to-ends ----------------------

  it("Home moves activeIndex to 0 from a non-zero position", async () => {
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose: vi.fn() },
    });
    const input = getByTestId("command-palette-search");
    // Move to index 2 via ArrowDown twice.
    await fireEvent.keyDown(input, { key: "ArrowDown" });
    await fireEvent.keyDown(input, { key: "ArrowDown" });
    // Confirm index 2 is active before pressing Home.
    const items = getByTestId("command-palette-list").querySelectorAll(
      "[data-testid='command-palette-item']",
    );
    expect(items[2]?.getAttribute("aria-selected")).toBe("true");
    // Press Home — should jump to index 0.
    await fireEvent.keyDown(input, { key: "Home" });
    expect(items[0]?.getAttribute("aria-selected")).toBe("true");
    expect(items[2]?.getAttribute("aria-selected")).toBe("false");
  });

  it("End moves activeIndex to the last result from index 0", async () => {
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose: vi.fn() },
    });
    const input = getByTestId("command-palette-search");
    const items = getByTestId("command-palette-list").querySelectorAll(
      "[data-testid='command-palette-item']",
    );
    // Index 0 is active by default.
    expect(items[0]?.getAttribute("aria-selected")).toBe("true");
    // Press End — should jump to the last item (index 2 for 3 results).
    await fireEvent.keyDown(input, { key: "End" });
    expect(items[2]?.getAttribute("aria-selected")).toBe("true");
    expect(items[0]?.getAttribute("aria-selected")).toBe("false");
  });

  it("Home and End are no-ops when filtered list is empty", async () => {
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose: vi.fn() },
    });
    const input = getByTestId("command-palette-search");
    // Filter to empty.
    await fireEvent.input(input, { target: { value: "zzznomatch" } });
    expect(getByTestId("command-palette-no-results")).toBeTruthy();
    // Both keys must not throw.
    await expect(fireEvent.keyDown(input, { key: "Home" })).resolves.not.toThrow();
    await expect(fireEvent.keyDown(input, { key: "End" })).resolves.not.toThrow();
  });

  // ---- gap-cycle-02-006: Esc cascade integration ----------------------

  it("Esc cascade closes the palette regardless of focus owner (gap-cycle-02-006)", () => {
    // The palette is open; focus is on document.body (not the search input).
    const onClose = vi.fn();
    render(CommandPalette, { props: { open: true, onClose } });

    // Move focus away from the search input so the local onkeydown handler
    // is not the active path.
    document.body.focus();

    const result = runEscCascade();

    expect(result).toBe(ESC_PRIORITY_CONTEXT_MENU + 1); // priority 2
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("priority-1 context menu preempts the palette when both are open (gap-cycle-02-006)", () => {
    const closeMenu = vi.fn();
    const onClose = vi.fn();

    // Register a context-menu entry at priority 1 that claims to be open.
    registerEscEntry({
      priority: ESC_PRIORITY_CONTEXT_MENU,
      isOpen: () => true,
      close: closeMenu,
    });

    render(CommandPalette, { props: { open: true, onClose } });

    const result = runEscCascade();

    expect(result).toBe(ESC_PRIORITY_CONTEXT_MENU);
    expect(closeMenu).toHaveBeenCalledOnce();
    // Palette must NOT have been closed — only the highest-priority overlay fires.
    expect(onClose).not.toHaveBeenCalled();
  });
});

// ---- gap-cycle-13-005: per-session cwd scoping --------------------------

describe("CommandPalette — slash command scoping (gap-cycle-13-005)", () => {
  it("fetches commands with the supplied workingDir", async () => {
    render(CommandPalette, {
      props: { open: true, onClose: vi.fn(), workingDir: "/home/user/project" },
    });

    await waitFor(() => {
      expect(mockListCommands).toHaveBeenCalledWith("/home/user/project");
    });
  });

  it("fetches commands with null when workingDir is omitted", async () => {
    render(CommandPalette, {
      props: { open: true, onClose: vi.fn() },
    });

    await waitFor(() => {
      expect(mockListCommands).toHaveBeenCalledWith(null);
    });
  });

  it("re-fetches on session switch (workingDir prop change)", async () => {
    mockListCommands.mockResolvedValue([]);

    const { rerender } = render(CommandPalette, {
      props: { open: true, onClose: vi.fn(), workingDir: "/session/a" },
    });

    await waitFor(() => {
      expect(mockListCommands).toHaveBeenCalledWith("/session/a");
    });

    await rerender({ workingDir: "/session/b" });

    // After the prop change the $effect should fire and fetch with the new cwd.
    await waitFor(() => {
      expect(mockListCommands).toHaveBeenCalledWith("/session/b");
    });
  });

  it("shows fetched slash commands in the list", async () => {
    mockListCommands.mockResolvedValue([
      { name: "build", description: "Run build", source: "project_commands" },
    ]);

    const { getAllByTestId } = render(CommandPalette, {
      props: { open: true, onClose: vi.fn(), workingDir: "/some/dir" },
    });

    await waitFor(() => {
      // 3 action items + 1 slash command = 4 total.
      const items = getAllByTestId("command-palette-item");
      expect(items.length).toBe(4);
    });
  });

  it("slash command label is prefixed with /", async () => {
    mockListCommands.mockResolvedValue([
      { name: "deploy", description: "Deploy", source: "project_commands" },
    ]);

    const { getAllByTestId } = render(CommandPalette, {
      props: { open: true, onClose: vi.fn(), workingDir: "/some/dir" },
    });

    await waitFor(() => {
      const items = getAllByTestId("command-palette-item");
      const labels = Array.from(items).map((el) => el.textContent ?? "");
      expect(labels.some((l) => l.includes("/deploy"))).toBe(true);
    });
  });
});
