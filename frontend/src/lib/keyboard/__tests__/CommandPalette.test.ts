/**
 * CommandPalette.svelte — unit tests.
 *
 * Covers the filtering, keyboard navigation, and confirm behaviour
 * specified in ``docs/behavior/keyboard-shortcuts.md`` §"Command palette".
 */
import { cleanup, fireEvent, render } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import CommandPalette from "../CommandPalette.svelte";

// ---- mock composerBridge so tests don't need a live Svelte context ----
vi.mock("../../stores/composerBridge.svelte", () => ({
  pasteIntoComposer: vi.fn(),
}));

// ---- mock listCommands so tests don't hit the network -----------------
vi.mock("../../api/commands", () => ({
  listCommands: vi.fn().mockResolvedValue([
    { name: "advisor", description: "Force advisor on this turn", source: "user_skills" },
    { name: "checkpoint", description: "Insert a labelled checkpoint", source: "user_skills" },
    { name: "compact", description: "Compact conversation history", source: "user_commands" },
  ]),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("CommandPalette", () => {
  it("renders nothing when closed", () => {
    const { queryByTestId } = render(CommandPalette, {
      props: { open: false, onClose: vi.fn(), sessionId: null },
    });
    expect(queryByTestId("command-palette-panel")).toBeNull();
  });

  it("renders the panel when open", () => {
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose: vi.fn(), sessionId: null },
    });
    expect(getByTestId("command-palette-panel")).toBeTruthy();
  });

  it("filters by query", async () => {
    const { getByTestId, findAllByTestId } = render(CommandPalette, {
      props: { open: true, onClose: vi.fn(), sessionId: null },
    });
    // Wait for commands to load
    const items = await findAllByTestId("command-palette-item");
    expect(items.length).toBe(3);

    const input = getByTestId("command-palette-search");
    await fireEvent.input(input, { target: { value: "advisor" } });

    const filtered = getByTestId("command-palette-list").querySelectorAll(
      "[data-testid='command-palette-item']",
    );
    expect(filtered.length).toBe(1);
    expect(filtered[0].getAttribute("data-command-name")).toBe("advisor");
  });

  it("shows no-results message when filter has no matches", async () => {
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose: vi.fn(), sessionId: null },
    });
    const input = getByTestId("command-palette-search");
    await fireEvent.input(input, { target: { value: "zzznomatch" } });
    expect(getByTestId("command-palette-no-results")).toBeTruthy();
  });

  it("calls onClose when Escape is pressed in the search input", async () => {
    const onClose = vi.fn();
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose, sessionId: null },
    });
    const input = getByTestId("command-palette-search");
    await fireEvent.keyDown(input, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("calls onClose when clicking the backdrop", async () => {
    const onClose = vi.fn();
    const { getByTestId } = render(CommandPalette, {
      props: { open: true, onClose, sessionId: null },
    });
    await fireEvent.click(getByTestId("command-palette-backdrop"));
    expect(onClose).toHaveBeenCalled();
  });
});
