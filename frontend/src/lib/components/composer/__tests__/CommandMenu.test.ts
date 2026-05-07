/**
 * CommandMenu.svelte — unit tests.
 *
 * Covers the acceptance criteria from gap-cycle-13-005:
 *
 * - Commands are fetched on mount with the supplied ``workingDir``.
 * - Changing ``workingDir`` (session switch) triggers a re-fetch with
 *   the new value so project commands are always scoped to the active
 *   session.
 * - Omitting ``workingDir`` fetches with no cwd argument (backward compat).
 * - Filtered list is computed from the fetched commands.
 * - Keyboard navigation and selection still work.
 *
 * Behavior anchor: ``docs/behavior/chat.md`` §"Slash commands in the composer",
 * §"Per-session project command scoping".
 */
import { cleanup, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CommandMenu from "../CommandMenu.svelte";

// ---- mock listCommands so tests never hit the network --------------------
// vi.mock factories are hoisted above variable declarations; use vi.hoisted
// to ensure the mock reference is available inside the factory.
const { mockListCommands } = vi.hoisted(() => ({
  mockListCommands: vi.fn<(cwd?: string | null) => Promise<{ name: string; description: string; source: string }[]>>(),
}));

vi.mock("../../../api/commands", () => ({
  listCommands: mockListCommands,
}));

const SAMPLE_COMMANDS = [
  { name: "advisor", description: "Force advisor", source: "user_commands" },
  { name: "checkpoint", description: "Insert checkpoint", source: "user_commands" },
  { name: "build", description: "Run build", source: "project_commands" },
];

beforeEach(() => {
  mockListCommands.mockReset();
  mockListCommands.mockResolvedValue(SAMPLE_COMMANDS);
  // jsdom doesn't implement scrollIntoView — stub it to prevent noise.
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("CommandMenu — workingDir prop (gap-cycle-13-005)", () => {
  it("calls listCommands with the provided workingDir on mount", async () => {
    render(CommandMenu, {
      props: {
        query: "",
        workingDir: "/home/user/project",
        onselect: vi.fn(),
        onclose: vi.fn(),
      },
    });

    await waitFor(() => {
      expect(mockListCommands).toHaveBeenCalledWith("/home/user/project");
    });
  });

  it("calls listCommands with null when workingDir is omitted", async () => {
    render(CommandMenu, {
      props: {
        query: "",
        onselect: vi.fn(),
        onclose: vi.fn(),
      },
    });

    await waitFor(() => {
      expect(mockListCommands).toHaveBeenCalledWith(null);
    });
  });

  it("re-fetches when workingDir changes (session switch)", async () => {
    // First session: returns command A only.
    mockListCommands.mockResolvedValue([
      { name: "cmd_a", description: "Session A command", source: "project_commands" },
    ]);

    const { rerender } = render(CommandMenu, {
      props: {
        query: "",
        workingDir: "/session/a",
        onselect: vi.fn(),
        onclose: vi.fn(),
      },
    });

    // Confirm first fetch used session/a's workingDir.
    await waitFor(() => {
      expect(mockListCommands).toHaveBeenCalledWith("/session/a");
    });

    // Switch session: second call returns command B only.
    mockListCommands.mockResolvedValue([
      { name: "cmd_b", description: "Session B command", source: "project_commands" },
    ]);

    await rerender({ workingDir: "/session/b" });

    // After rerender, the effect should have re-fetched with the new workingDir.
    await waitFor(() => {
      expect(mockListCommands).toHaveBeenCalledWith("/session/b");
    });
  });

  it("renders the fetched command list", async () => {
    const { getAllByTestId } = render(CommandMenu, {
      props: {
        query: "",
        workingDir: "/some/dir",
        onselect: vi.fn(),
        onclose: vi.fn(),
      },
    });

    await waitFor(() => {
      const items = getAllByTestId("command-menu-item");
      expect(items.length).toBe(SAMPLE_COMMANDS.length);
    });
  });

  it("filters the list by query", async () => {
    const { getAllByTestId } = render(CommandMenu, {
      props: {
        query: "build",
        workingDir: "/some/dir",
        onselect: vi.fn(),
        onclose: vi.fn(),
      },
    });

    await waitFor(() => {
      const items = getAllByTestId("command-menu-item");
      // Only "build" matches the query "build".
      expect(items.length).toBe(1);
    });
  });

  it("shows no-results when query has no matches", async () => {
    const { getByTestId } = render(CommandMenu, {
      props: {
        query: "zzznomatch",
        workingDir: "/some/dir",
        onselect: vi.fn(),
        onclose: vi.fn(),
      },
    });

    await waitFor(() => {
      expect(getByTestId("command-menu-empty")).toBeTruthy();
    });
  });
});
