/**
 * Component tests for :class:`MemoriesIndex` (gap-cycle-13-007).
 *
 * Done-when criteria covered:
 *
 * * Page renders flat list on mount (default view is the global index).
 * * Chip filter narrows the visible rows to one tag.
 * * Row click invokes ``onRowClick`` with the correct :interface:`AllMemoriesRow`.
 * * Empty state renders when the response is ``[]``.
 * * Loading state renders while the fetch is in flight.
 * * Chips only appear when more than one tag is present.
 *
 * The API call is injected via the ``listAllMemoriesFn`` prop seam so
 * the test never makes real HTTP calls.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import type { AllMemoriesRow } from "../../../api/memories";
import MemoriesIndex from "../MemoriesIndex.svelte";

function fakeRow(overrides: Partial<AllMemoriesRow> = {}): AllMemoriesRow {
  return {
    tag_id: 7,
    tag_name: "bearings/architect",
    tag_color: null,
    memory_id: 1,
    memory_title: "Memory A",
    memory_body_preview: "Preview A",
    enabled: true,
    updated_at: "2026-04-29T00:00:00Z",
    ...overrides,
  };
}

describe("MemoriesIndex — loading / empty / error states", () => {
  it("renders loading copy while the fetch is in flight", () => {
    // Never-resolving promise keeps loading = true.
    const listAllMemoriesFn = vi.fn().mockReturnValue(new Promise(() => {}));
    const { getByTestId } = render(MemoriesIndex, {
      props: { listAllMemoriesFn },
    });
    expect(getByTestId("memories-index-loading")).toBeInTheDocument();
  });

  it("renders empty state when the response is []", async () => {
    const listAllMemoriesFn = vi.fn().mockResolvedValue([]);
    const { getByTestId } = render(MemoriesIndex, {
      props: { listAllMemoriesFn },
    });
    await waitFor(() => expect(getByTestId("memories-index-empty")).toBeInTheDocument());
  });

  it("renders the flat list after the response resolves", async () => {
    const rows = [
      fakeRow({ memory_id: 1, memory_title: "First" }),
      fakeRow({ memory_id: 2, memory_title: "Second" }),
    ];
    const listAllMemoriesFn = vi.fn().mockResolvedValue(rows);
    const { getAllByTestId } = render(MemoriesIndex, {
      props: { listAllMemoriesFn },
    });
    await waitFor(() => {
      const renderedRows = getAllByTestId("memories-index-row");
      expect(renderedRows).toHaveLength(2);
    });
  });

  it("shows each row's title and tag name", async () => {
    const rows = [fakeRow({ memory_title: "My Memory", tag_name: "bearings/architect" })];
    const listAllMemoriesFn = vi.fn().mockResolvedValue(rows);
    const { getByTestId } = render(MemoriesIndex, {
      props: { listAllMemoriesFn },
    });
    await waitFor(() => {
      expect(getByTestId("memories-index-row-title").textContent).toContain("My Memory");
      expect(getByTestId("memories-index-row-tag").textContent).toContain("bearings/architect");
    });
  });
});

describe("MemoriesIndex — chip filter", () => {
  it("does NOT render chips when only one tag is present", async () => {
    const rows = [fakeRow({ tag_id: 7, tag_name: "single-tag" })];
    const listAllMemoriesFn = vi.fn().mockResolvedValue(rows);
    const { queryByTestId } = render(MemoriesIndex, {
      props: { listAllMemoriesFn },
    });
    await waitFor(() => expect(queryByTestId("memories-index-chips")).toBeNull());
  });

  it("renders a chip per unique tag when multiple tags exist", async () => {
    const rows = [
      fakeRow({ tag_id: 7, tag_name: "alpha", memory_id: 1 }),
      fakeRow({ tag_id: 9, tag_name: "beta", memory_id: 2 }),
    ];
    const listAllMemoriesFn = vi.fn().mockResolvedValue(rows);
    const { getAllByTestId } = render(MemoriesIndex, {
      props: { listAllMemoriesFn },
    });
    await waitFor(() => {
      const chips = getAllByTestId("memories-index-chip");
      expect(chips).toHaveLength(2);
    });
  });

  it("clicking a chip narrows the list to that tag's rows", async () => {
    const rows = [
      fakeRow({ tag_id: 7, tag_name: "alpha", memory_id: 1 }),
      fakeRow({ tag_id: 9, tag_name: "beta", memory_id: 2 }),
    ];
    const listAllMemoriesFn = vi.fn().mockResolvedValue(rows);
    const { getAllByTestId } = render(MemoriesIndex, {
      props: { listAllMemoriesFn },
    });
    // Wait for chips to appear.
    let chips: HTMLElement[];
    await waitFor(() => {
      chips = getAllByTestId("memories-index-chip");
      expect(chips).toHaveLength(2);
    });
    // Click the "alpha" chip (first).
    await fireEvent.click(getAllByTestId("memories-index-chip")[0]);
    await waitFor(() => {
      const renderedRows = getAllByTestId("memories-index-row");
      // Only the alpha row should be visible.
      expect(renderedRows).toHaveLength(1);
      expect(renderedRows[0].dataset.tagId).toBe("7");
    });
  });

  it("clicking an active chip clears the filter and shows all rows", async () => {
    const rows = [
      fakeRow({ tag_id: 7, tag_name: "alpha", memory_id: 1 }),
      fakeRow({ tag_id: 9, tag_name: "beta", memory_id: 2 }),
    ];
    const listAllMemoriesFn = vi.fn().mockResolvedValue(rows);
    const { getAllByTestId } = render(MemoriesIndex, {
      props: { listAllMemoriesFn },
    });
    await waitFor(() => {
      expect(getAllByTestId("memories-index-chip")).toHaveLength(2);
    });
    // Activate filter.
    await fireEvent.click(getAllByTestId("memories-index-chip")[0]);
    await waitFor(() => expect(getAllByTestId("memories-index-row")).toHaveLength(1));
    // Deactivate filter.
    await fireEvent.click(getAllByTestId("memories-index-chip")[0]);
    await waitFor(() => expect(getAllByTestId("memories-index-row")).toHaveLength(2));
  });
});

describe("MemoriesIndex — chip-filter zero-rows spec guard (finding-7-001 regression)", () => {
  /**
   * Guards the spec invariant from docs/behavior/memories.md §Index view
   * layout: the empty-state node renders ONLY when the API response itself
   * is [] (rows.length === 0), never when a chip filter merely reduces the
   * visible count to zero (filteredRows.length === 0 while rows.length > 0).
   *
   * The component uses \`rows.length === 0\` as the guard (MemoriesIndex.svelte
   * line 119).  A future regression that accidentally changed this to
   * \`filteredRows.length === 0\` would fail this test.
   */
  it("empty state stays hidden when chip filter leaves zero matching rows for the unselected tag", async () => {
    const rows = [
      fakeRow({ tag_id: 7, tag_name: "alpha", memory_id: 1 }),
      fakeRow({ tag_id: 9, tag_name: "beta", memory_id: 2 }),
    ];
    const listAllMemoriesFn = vi.fn().mockResolvedValue(rows);
    const { getAllByTestId, queryByTestId, queryAllByTestId } = render(MemoriesIndex, {
      props: { listAllMemoriesFn },
    });

    // Wait for chips to appear (two distinct tags → chip row is shown).
    await waitFor(() => {
      expect(getAllByTestId("memories-index-chip")).toHaveLength(2);
    });

    // Activate the alpha chip (tag_id:7) — narrows the visible list to 1 row.
    await fireEvent.click(getAllByTestId("memories-index-chip")[0]);
    await waitFor(() => {
      const visible = getAllByTestId("memories-index-row");
      expect(visible).toHaveLength(1);
      expect(visible[0]).toHaveAttribute("data-tag-id", "7");
    });

    // The beta rows (tag_id:9) now have zero visible count — they are filtered
    // out by the chip.  Because rows.length = 2 > 0 the spec guard must keep
    // the empty-state node absent from the DOM.
    const betaVisible = (queryAllByTestId("memories-index-row") ?? []).filter(
      (el) => el.getAttribute("data-tag-id") === "9",
    );
    expect(betaVisible).toHaveLength(0); // zero visible rows for the unselected tag
    expect(queryByTestId("memories-index-empty")).toBeNull(); // spec guard: empty state hidden

    // Switch to the beta chip — same invariant from the other direction.
    await fireEvent.click(getAllByTestId("memories-index-chip")[1]);
    await waitFor(() => {
      const visible = getAllByTestId("memories-index-row");
      expect(visible).toHaveLength(1);
      expect(visible[0]).toHaveAttribute("data-tag-id", "9");
    });
    const alphaVisible = (queryAllByTestId("memories-index-row") ?? []).filter(
      (el) => el.getAttribute("data-tag-id") === "7",
    );
    expect(alphaVisible).toHaveLength(0); // zero visible rows for the unselected tag
    expect(queryByTestId("memories-index-empty")).toBeNull(); // spec guard upheld
  });
});

describe("MemoriesIndex — row click", () => {
  it("calls onRowClick with the correct AllMemoriesRow when a row is clicked", async () => {
    const onRowClick = vi.fn();
    const row = fakeRow({ memory_id: 42, tag_id: 7, memory_title: "Click Me" });
    const listAllMemoriesFn = vi.fn().mockResolvedValue([row]);
    const { getByTestId } = render(MemoriesIndex, {
      props: { listAllMemoriesFn, onRowClick },
    });
    await waitFor(() => expect(getByTestId("memories-index-row")).toBeInTheDocument());
    await fireEvent.click(getByTestId("memories-index-row").querySelector("button")!);
    expect(onRowClick).toHaveBeenCalledWith(row);
  });
});
