/**
 * Unit tests for the tag store — covers the OR-filter mechanics
 * (toggleTag adds/removes, clearTagFilter empties, filter set is a
 * fresh reference on each change so consumers re-render).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { _resetForTests, clearTagFilter, refreshTags, tagsStore, toggleTag } from "../tags.svelte";
import type { TagOut } from "../../api/tags";

const fixtureTag: TagOut = {
  id: 7,
  name: "bearings/architect",
  color: null,
  default_model: null,
  working_dir: null,
  pinned: false,
  class_: "general" as const,
  sort_order: 0,
  group: "bearings",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  open_session_count: 0,
  session_count: 0,
};

beforeEach(() => {
  _resetForTests();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("tagsStore filter mechanics", () => {
  it("toggleTag adds a tag id to its class section's set when absent", () => {
    expect(tagsStore.selectedProjectIds.has(7)).toBe(false);
    toggleTag(7, "project");
    expect(tagsStore.selectedProjectIds.has(7)).toBe(true);
    // Other sections stay empty.
    expect(tagsStore.selectedSeverityIds.size).toBe(0);
    expect(tagsStore.selectedOtherIds.size).toBe(0);
  });

  it("toggleTag removes the id when already present in its section", () => {
    toggleTag(7, "severity");
    toggleTag(7, "severity");
    expect(tagsStore.selectedSeverityIds.has(7)).toBe(false);
    expect(tagsStore.selectedSeverityIds.size).toBe(0);
  });

  it("toggleTag replaces the section's set reference each call (Svelte reactivity)", () => {
    const before = tagsStore.selectedOtherIds;
    toggleTag(7, "general");
    expect(tagsStore.selectedOtherIds).not.toBe(before);
  });

  it("supports OR-within within a class — multiple ids coexist in one section", () => {
    toggleTag(1, "project");
    toggleTag(2, "project");
    toggleTag(3, "project");
    expect(Array.from(tagsStore.selectedProjectIds).sort((a, b) => a - b)).toEqual([1, 2, 3]);
    expect(tagsStore.selectedSeverityIds.size).toBe(0);
  });

  it("ids land in the correct section per class", () => {
    toggleTag(10, "project");
    toggleTag(20, "severity");
    toggleTag(30, "general");
    expect(tagsStore.selectedProjectIds.has(10)).toBe(true);
    expect(tagsStore.selectedSeverityIds.has(20)).toBe(true);
    expect(tagsStore.selectedOtherIds.has(30)).toBe(true);
  });

  it("clearTagFilter empties every section's set", () => {
    toggleTag(1, "project");
    toggleTag(2, "severity");
    toggleTag(3, "general");
    clearTagFilter();
    expect(tagsStore.selectedProjectIds.size).toBe(0);
    expect(tagsStore.selectedSeverityIds.size).toBe(0);
    expect(tagsStore.selectedOtherIds.size).toBe(0);
  });

  it("clearTagFilter is a no-op when every section is already empty", () => {
    const before = {
      project: tagsStore.selectedProjectIds,
      severity: tagsStore.selectedSeverityIds,
      other: tagsStore.selectedOtherIds,
    };
    clearTagFilter();
    expect(tagsStore.selectedProjectIds).toBe(before.project);
    expect(tagsStore.selectedSeverityIds).toBe(before.severity);
    expect(tagsStore.selectedOtherIds).toBe(before.other);
  });
});

describe("tagsStore.refreshTags", () => {
  it("populates state.all on a successful fetch", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify([fixtureTag]), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    await refreshTags();
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(tagsStore.all).toEqual([fixtureTag]);
    expect(tagsStore.loading).toBe(false);
    expect(tagsStore.error).toBeNull();
  });

  it("captures errors on a non-2xx response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response("nope", { status: 500 }));
    await refreshTags();
    expect(tagsStore.error).toBeInstanceOf(Error);
    expect(tagsStore.loading).toBe(false);
  });
});
