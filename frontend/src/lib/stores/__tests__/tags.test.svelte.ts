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
  group: "bearings",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

beforeEach(() => {
  _resetForTests();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("tagsStore filter mechanics", () => {
  it("toggleTag adds a tag id to selectedIds when absent", () => {
    expect(tagsStore.selectedIds.has(7)).toBe(false);
    toggleTag(7);
    expect(tagsStore.selectedIds.has(7)).toBe(true);
  });

  it("toggleTag removes the id when already present", () => {
    toggleTag(7);
    toggleTag(7);
    expect(tagsStore.selectedIds.has(7)).toBe(false);
    expect(tagsStore.selectedIds.size).toBe(0);
  });

  it("toggleTag replaces the set reference each call (Svelte reactivity)", () => {
    const before = tagsStore.selectedIds;
    toggleTag(7);
    expect(tagsStore.selectedIds).not.toBe(before);
  });

  it("supports OR semantics — multiple ids coexist in selectedIds", () => {
    toggleTag(1);
    toggleTag(2);
    toggleTag(3);
    expect(Array.from(tagsStore.selectedIds).sort((a, b) => a - b)).toEqual([1, 2, 3]);
  });

  it("clearTagFilter empties the set", () => {
    toggleTag(1);
    toggleTag(2);
    clearTagFilter();
    expect(tagsStore.selectedIds.size).toBe(0);
  });

  it("clearTagFilter is a no-op when already empty (no spurious mutation)", () => {
    const before = tagsStore.selectedIds;
    clearTagFilter();
    expect(tagsStore.selectedIds).toBe(before);
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
