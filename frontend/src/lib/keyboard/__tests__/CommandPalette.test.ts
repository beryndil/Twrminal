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
 * Behavior anchor: ``docs/behavior/keyboard-shortcuts.md``
 * §"Command palette".
 */
import { cleanup, fireEvent, render } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CommandPalette from "../CommandPalette.svelte";
import { registerPaletteHandler, _resetPaletteHandlers } from "../../context-menu/palette";

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
  _resetPaletteHandlers();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
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
});
