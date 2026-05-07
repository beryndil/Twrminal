/**
 * Component tests for ``TagFilterPanel`` — three-section chip
 * rendering, click toggle, clear-button visibility, empty-state
 * copy. Each section's chip set tracks an independent OR-within
 * selection; the three compose AND-across at the query layer.
 */
import { fireEvent, render } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import TagFilterPanel from "../TagFilterPanel.svelte";
import type { TagClass, TagOut } from "../../../api/tags";

const tag = (id: number, name: string, klass: TagClass = "general"): TagOut => ({
  id,
  name,
  color: null,
  default_model: null,
  working_dir: null,
  pinned: false,
  class_: klass,
  sort_order: 0,
  group: name.includes("/") ? name.split("/")[0] : null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
});

const emptySets = (): {
  selectedProjectIds: ReadonlySet<number>;
  selectedSeverityIds: ReadonlySet<number>;
  selectedOtherIds: ReadonlySet<number>;
} => ({
  selectedProjectIds: new Set<number>(),
  selectedSeverityIds: new Set<number>(),
  selectedOtherIds: new Set<number>(),
});

describe("TagFilterPanel", () => {
  it("renders one chip per tag, bucketed by class", () => {
    const { getAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [
          tag(1, "bearings", "project"),
          tag(2, "high", "severity"),
          tag(3, "freeform", "general"),
        ],
        ...emptySets(),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(getAllByTestId("tag-filter-chip")).toHaveLength(3);
  });

  it("renders the three section headers (Project / Severity / Other)", () => {
    const { getByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "bearings", "project")],
        ...emptySets(),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(getByTestId("tag-filter-section-project")).toBeInTheDocument();
    expect(getByTestId("tag-filter-section-severity")).toBeInTheDocument();
    expect(getByTestId("tag-filter-section-other")).toBeInTheDocument();
  });

  it("shows the global empty-state when no tags exist anywhere", () => {
    const { getByTestId } = render(TagFilterPanel, {
      props: {
        tags: [],
        ...emptySets(),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(getByTestId("tag-filter-empty")).toBeInTheDocument();
  });

  it("shows per-section empty-state copy when one section has no tags", () => {
    const { getByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "bearings", "project")],
        ...emptySets(),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    // Only project has tags; severity + other are empty within their sections.
    expect(getByTestId("tag-filter-section-severity-empty")).toBeInTheDocument();
    expect(getByTestId("tag-filter-section-other-empty")).toBeInTheDocument();
  });

  it("clicking a project chip fires onToggle with id + 'project'", async () => {
    const onToggle = vi.fn();
    const { getAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(7, "bearings", "project")],
        ...emptySets(),
        onToggle,
        onClear: vi.fn(),
      },
    });
    await fireEvent.click(getAllByTestId("tag-filter-chip")[0]);
    expect(onToggle).toHaveBeenCalledWith(7, "project");
  });

  it("clicking a severity chip fires onToggle with id + 'severity'", async () => {
    const onToggle = vi.fn();
    const { getAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(9, "urgent", "severity")],
        ...emptySets(),
        onToggle,
        onClear: vi.fn(),
      },
    });
    await fireEvent.click(getAllByTestId("tag-filter-chip")[0]);
    expect(onToggle).toHaveBeenCalledWith(9, "severity");
  });

  it("hides the clear button when no section has a selection", () => {
    const { queryByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "freeform")],
        ...emptySets(),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(queryByTestId("tag-filter-clear")).toBeNull();
  });

  it("shows the clear button when any section has at least one selection", () => {
    const { getByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "freeform")],
        ...emptySets(),
        selectedOtherIds: new Set([1]),
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
        tags: [tag(1, "freeform")],
        ...emptySets(),
        selectedOtherIds: new Set([1]),
        onToggle: vi.fn(),
        onClear,
      },
    });
    await fireEvent.click(getByTestId("tag-filter-clear"));
    expect(onClear).toHaveBeenCalled();
  });

  it("marks selected chips with aria-pressed=true within their class section", () => {
    const { getAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "bearings", "project"), tag(2, "archon", "project")],
        ...emptySets(),
        selectedProjectIds: new Set([1]),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    const chips = getAllByTestId("tag-filter-chip");
    const pressedById = new Map(
      chips.map((c) => [c.getAttribute("data-tag-id"), c.getAttribute("aria-pressed")]),
    );
    expect(pressedById.get("1")).toBe("true");
    expect(pressedById.get("2")).toBe("false");
  });

  it("renders no pin indicator on a chip when pinned is false", () => {
    const { queryAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "bearings", "project")],
        ...emptySets(),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(queryAllByTestId("tag-filter-chip-pinned-indicator")).toHaveLength(0);
  });

  it("renders a pin indicator on a chip when pinned is true", () => {
    const { getAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [{ ...tag(1, "bearings", "project"), pinned: true }],
        ...emptySets(),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    const indicators = getAllByTestId("tag-filter-chip-pinned-indicator");
    expect(indicators).toHaveLength(1);
    expect(indicators[0]).toHaveTextContent("★");
  });

  it("pin indicator has an accessible aria-label", () => {
    const { getByTestId } = render(TagFilterPanel, {
      props: {
        tags: [{ ...tag(1, "bearings", "project"), pinned: true }],
        ...emptySets(),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(getByTestId("tag-filter-chip-pinned-indicator")).toHaveAttribute(
      "aria-label",
      "Pinned",
    );
  });

  it("renders pin indicators across all three class sections", () => {
    const { getAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [
          { ...tag(1, "bearings", "project"), pinned: true },
          { ...tag(2, "urgent", "severity"), pinned: true },
          { ...tag(3, "freeform", "general"), pinned: true },
        ],
        ...emptySets(),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(getAllByTestId("tag-filter-chip-pinned-indicator")).toHaveLength(3);
  });

  it("renders indicator only on pinned chips in a mixed bucket", () => {
    const { getAllByTestId, queryAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [
          { ...tag(1, "pinned-proj", "project"), pinned: true },
          tag(2, "unpinned-proj", "project"),
        ],
        ...emptySets(),
        onToggle: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(queryAllByTestId("tag-filter-chip-pinned-indicator")).toHaveLength(1);
    expect(getAllByTestId("tag-filter-chip")).toHaveLength(2);
  });
});
