/**
 * SidebarSearch.svelte — unit tests.
 *
 * Covers the acceptance criteria from gap-cycle-02-007:
 *
 * - Esc cascade closes the overlay regardless of which element inside
 *   the panel owns focus (input, close button, or body).
 * - The local onkeydown Esc handler on the input closes the overlay
 *   when the input has focus.
 * - Close button click closes the overlay.
 * - Backdrop click closes the overlay.
 *
 * Behavior anchor: ``docs/behavior/keyboard-shortcuts.md`` §"Focus",
 * priority 4 ("any other overlay").
 */
import { cleanup, fireEvent, render } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushSync } from "svelte";

import {
  ESC_PRIORITY_OVERLAY,
  _resetForTests as resetEscCascade,
  runEscCascade,
} from "../../../keyboard/escCascade";
import { _resetForTests as resetHandlers, getHandler } from "../../../keyboard/store.svelte";
import { KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH } from "../../../config";
import SidebarSearch from "../SidebarSearch.svelte";

// searchHistory is called after a debounce; mock it so tests don't need a
// real API server.
vi.mock("../../../api/history", () => ({
  searchHistory: vi.fn(async () => []),
}));

beforeEach(() => {
  resetEscCascade();
  resetHandlers();
  document.body.innerHTML = "";
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  resetEscCascade();
  resetHandlers();
});

describe("SidebarSearch", () => {
  it("renders nothing when closed", () => {
    const { queryByTestId } = render(SidebarSearch, { props: { onclose: vi.fn() } });
    expect(queryByTestId("sidebar-search-dialog")).toBeNull();
  });

  it("shows the dialog after the keybinding handler is called", () => {
    const { queryByTestId } = render(SidebarSearch, { props: { onclose: vi.fn() } });
    flushSync(() => {
      getHandler(KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH)?.();
    });
    expect(queryByTestId("sidebar-search-dialog")).toBeInTheDocument();
  });

  it("close button click closes the overlay", async () => {
    const onclose = vi.fn();
    const { queryByTestId, getByTestId } = render(SidebarSearch, { props: { onclose } });
    flushSync(() => {
      getHandler(KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH)?.();
    });
    await fireEvent.click(getByTestId("sidebar-search-close"));
    expect(queryByTestId("sidebar-search-dialog")).toBeNull();
    expect(onclose).toHaveBeenCalledOnce();
  });

  it("backdrop click closes the overlay", async () => {
    const onclose = vi.fn();
    const { queryByTestId, getByTestId } = render(SidebarSearch, { props: { onclose } });
    flushSync(() => {
      getHandler(KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH)?.();
    });
    await fireEvent.click(getByTestId("sidebar-search-backdrop"));
    expect(queryByTestId("sidebar-search-dialog")).toBeNull();
    expect(onclose).toHaveBeenCalledOnce();
  });

  it("local Esc on the input closes the overlay (defence-in-depth)", async () => {
    const onclose = vi.fn();
    const { queryByTestId, getByTestId } = render(SidebarSearch, { props: { onclose } });
    flushSync(() => {
      getHandler(KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH)?.();
    });
    const input = getByTestId("sidebar-search-input");
    await fireEvent.keyDown(input, { key: "Escape" });
    expect(queryByTestId("sidebar-search-dialog")).toBeNull();
    expect(onclose).toHaveBeenCalledOnce();
  });

  // ---- gap-cycle-02-007: Esc cascade integration -------------------------

  it("Esc cascade closes overlay regardless of focus owner (gap-cycle-02-007)", () => {
    // The overlay is open; focus is on document.body (not the search input).
    const onclose = vi.fn();
    render(SidebarSearch, { props: { onclose } });

    // Open the overlay via the keybinding handler registered in onMount.
    flushSync(() => {
      getHandler(KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH)?.();
    });

    // Move focus away from the search input to simulate e.g. the close button
    // or any non-input element inside the panel owning focus.
    document.body.focus();

    // Run the global Esc cascade — must close the overlay at priority 4.
    const result = runEscCascade();

    expect(result).toBe(ESC_PRIORITY_OVERLAY);
    expect(onclose).toHaveBeenCalledOnce();
  });
});
