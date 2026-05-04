/**
 * Unit tests for :mod:`stores/multiSelection.svelte.ts`.
 *
 * Verifies the toggle, setIds, clearSelection, and _resetForTests
 * helpers against the reactive state proxy.
 */
import { describe, expect, it, afterEach } from "vitest";
import {
  multiSelectionStore,
  toggleId,
  setIds,
  clearSelection,
  _resetForTests,
} from "../multiSelection.svelte";

afterEach(() => {
  _resetForTests();
});

describe("multiSelectionStore", () => {
  it("starts empty", () => {
    expect(multiSelectionStore.ids.size).toBe(0);
  });

  it("toggleId adds a new id", () => {
    toggleId("ses_a");
    expect(multiSelectionStore.ids.has("ses_a")).toBe(true);
    expect(multiSelectionStore.ids.size).toBe(1);
  });

  it("toggleId removes an existing id", () => {
    toggleId("ses_a");
    toggleId("ses_a");
    expect(multiSelectionStore.ids.size).toBe(0);
  });

  it("toggleId handles multiple distinct ids", () => {
    toggleId("ses_a");
    toggleId("ses_b");
    expect(multiSelectionStore.ids.has("ses_a")).toBe(true);
    expect(multiSelectionStore.ids.has("ses_b")).toBe(true);
    expect(multiSelectionStore.ids.size).toBe(2);
  });

  it("setIds replaces the entire selection", () => {
    toggleId("ses_a");
    setIds(["ses_b", "ses_c"]);
    expect(multiSelectionStore.ids.has("ses_a")).toBe(false);
    expect(multiSelectionStore.ids.has("ses_b")).toBe(true);
    expect(multiSelectionStore.ids.has("ses_c")).toBe(true);
  });

  it("clearSelection empties the set", () => {
    setIds(["ses_a", "ses_b"]);
    clearSelection();
    expect(multiSelectionStore.ids.size).toBe(0);
  });

  it("clearSelection is a no-op when already empty", () => {
    // Should not throw.
    clearSelection();
    expect(multiSelectionStore.ids.size).toBe(0);
  });

  it("_resetForTests empties the set", () => {
    setIds(["ses_x"]);
    _resetForTests();
    expect(multiSelectionStore.ids.size).toBe(0);
  });
});
