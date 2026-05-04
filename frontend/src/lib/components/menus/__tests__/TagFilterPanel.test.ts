/**
 * Component tests for ``TagFilterPanel`` — chip rendering, click
 * toggle, clear-button visibility, empty-state copy.
 */
import { fireEvent, render } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import TagFilterPanel from "../TagFilterPanel.svelte";
import type { TagOut } from "../../../api/tags";

const tag = (id: number, name: string): TagOut => ({
  id,
  name,
  color: null,
  default_model: null,
  working_dir: null,
  pinned: false,
  group: name.includes("/") ? name.split("/")[0] : null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
});

describe("TagFilterPanel", () => {
  it("renders one chip per tag", () => {
    const { getAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "a"), tag(2, "b"), tag(3, "c")],
        selectedIds: new Set<number>(),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(getAllByTestId("tag-filter-chip")).toHaveLength(3);
  });

  it("shows the empty-state when no tags exist", () => {
    const { getByTestId } = render(TagFilterPanel, {
      props: {
        tags: [],
        selectedIds: new Set<number>(),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(getByTestId("tag-filter-empty")).toBeInTheDocument();
  });

  it("clicking a chip fires onToggle with the tag id", async () => {
    const onToggle = vi.fn();
    const { getAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(7, "bearings/architect")],
        selectedIds: new Set<number>(),
        onToggle,
        onClear: vi.fn(),
      },
    });
    await fireEvent.click(getAllByTestId("tag-filter-chip")[0]);
    expect(onToggle).toHaveBeenCalledWith(7);
  });

  it("hides the clear button when nothing is selected", () => {
    const { queryByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "a")],
        selectedIds: new Set<number>(),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(queryByTestId("tag-filter-clear")).toBeNull();
  });

  it("shows the clear button when at least one tag is selected", () => {
    const { getByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "a")],
        selectedIds: new Set([1]),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(getByTestId("tag-filter-clear")).toBeInTheDocument();
  });

  it("clear button fires onClear", async () => {
    const onClear = vi.fn();
    const { getByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "a")],
        selectedIds: new Set([1]),
        onToggle: vi.fn(),
        onClear,
      },
    });
    await fireEvent.click(getByTestId("tag-filter-clear"));
    expect(onClear).toHaveBeenCalled();
  });

  it("marks selected chips with aria-pressed=true", () => {
    const { getAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "a"), tag(2, "b")],
        selectedIds: new Set([1]),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    const [first, second] = getAllByTestId("tag-filter-chip");
    expect(first).toHaveAttribute("aria-pressed", "true");
    expect(second).toHaveAttribute("aria-pressed", "false");
  });
});
