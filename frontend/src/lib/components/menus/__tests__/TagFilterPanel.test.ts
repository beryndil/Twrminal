/**
 * Component tests for ``TagFilterPanel`` — three-section chip
 * rendering, click toggle, clear-button visibility, empty-state
 * copy. Each section's chip set tracks an independent OR-within
 * selection; the three compose AND-across at the query layer.
 */
import { fireEvent, render } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TagFilterPanel from "../TagFilterPanel.svelte";
import type { TagClass, TagOut } from "../../../api/tags";
import {
  tagsStore,
  _resetForTests,
  _hydrateTagPanelFromStorage,
} from "../../../stores/tags.svelte";
import { TAG_FILTER_PANEL_COLLAPSED_KEY } from "../../../config";

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
  open_session_count: 0,
  session_count: 0,
});

const emptySets = (): {
  selectedProjectIds: ReadonlySet<number>;
  selectedSeverityIds: ReadonlySet<number>;
  selectedOtherIds: ReadonlySet<number>;
  selectedSeverityNone: boolean;
} => ({
  selectedProjectIds: new Set<number>(),
  selectedSeverityIds: new Set<number>(),
  selectedOtherIds: new Set<number>(),
  selectedSeverityNone: false,
});

// ---------------------------------------------------------------------------
// Shared setup helpers
// ---------------------------------------------------------------------------

interface PanelProps {
  tags: TagOut[];
  selectedProjectIds: ReadonlySet<number>;
  selectedSeverityIds: ReadonlySet<number>;
  selectedOtherIds: ReadonlySet<number>;
  selectedSeverityNone: boolean;
  onToggle: ReturnType<typeof vi.fn>;
  onToggleSeverityNone: ReturnType<typeof vi.fn>;
  onClear: ReturnType<typeof vi.fn>;
}

function baseProps(overrides: Partial<PanelProps> = {}): PanelProps {
  return {
    tags: [tag(1, "bearings", "project")],
    ...emptySets(),
    onToggle: vi.fn(),
    onToggleSeverityNone: vi.fn(),
    onClear: vi.fn(),
    ...overrides,
  };
}

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
        onToggleSeverityNone: vi.fn(),
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
        onToggleSeverityNone: vi.fn(),
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
        onToggleSeverityNone: vi.fn(),
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
        onToggleSeverityNone: vi.fn(),
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
        onToggleSeverityNone: vi.fn(),
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
        onToggleSeverityNone: vi.fn(),
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
        onToggleSeverityNone: vi.fn(),
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
        onToggleSeverityNone: vi.fn(),
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
        onToggleSeverityNone: vi.fn(),
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
        onToggleSeverityNone: vi.fn(),
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
        onToggleSeverityNone: vi.fn(),
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
        onToggleSeverityNone: vi.fn(),
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
        onToggleSeverityNone: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(getByTestId("tag-filter-chip-pinned-indicator")).toHaveAttribute("aria-label", "Pinned");
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
        onToggleSeverityNone: vi.fn(),
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
        onToggleSeverityNone: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(queryAllByTestId("tag-filter-chip-pinned-indicator")).toHaveLength(1);
    expect(getAllByTestId("tag-filter-chip")).toHaveLength(2);
  });

  // ---------------------------------------------------------------------------
  // Session count pair display
  // ---------------------------------------------------------------------------

  it("renders a count pair element on every chip", () => {
    const { getAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [
          { ...tag(1, "bearings", "project"), open_session_count: 2, session_count: 3 },
          { ...tag(2, "urgent", "severity"), open_session_count: 0, session_count: 1 },
          { ...tag(3, "misc"), open_session_count: 0, session_count: 0 },
        ],
        ...emptySets(),
        onToggle: vi.fn(),
        onToggleSeverityNone: vi.fn(),
        onClear: vi.fn(),
      },
    });
    // One count pair per chip.
    expect(getAllByTestId("tag-filter-chip-counts")).toHaveLength(3);
  });

  it("open count span has emerald tint when open_session_count > 0", () => {
    const { getAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [{ ...tag(1, "bearings", "project"), open_session_count: 3, session_count: 5 }],
        ...emptySets(),
        onToggle: vi.fn(),
        onToggleSeverityNone: vi.fn(),
        onClear: vi.fn(),
      },
    });
    const countPair = getAllByTestId("tag-filter-chip-counts")[0];
    const openSpan = countPair.querySelector(".session-count--open");
    expect(openSpan).not.toBeNull();
    expect(openSpan!.classList.contains("text-emerald-500")).toBe(true);
    expect(openSpan!.classList.contains("text-fg-muted")).toBe(false);
    expect(openSpan!.textContent).toBe("3");
  });

  it("open count span is muted when open_session_count is 0", () => {
    const { getAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [{ ...tag(1, "bearings", "project"), open_session_count: 0, session_count: 2 }],
        ...emptySets(),
        onToggle: vi.fn(),
        onToggleSeverityNone: vi.fn(),
        onClear: vi.fn(),
      },
    });
    const countPair = getAllByTestId("tag-filter-chip-counts")[0];
    const openSpan = countPair.querySelector(".session-count--open");
    expect(openSpan).not.toBeNull();
    expect(openSpan!.classList.contains("text-fg-muted")).toBe(true);
    expect(openSpan!.classList.contains("text-emerald-500")).toBe(false);
    expect(openSpan!.textContent).toBe("0");
  });

  it("total count span shows the session_count value", () => {
    const { getAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [{ ...tag(1, "bearings", "project"), open_session_count: 1, session_count: 7 }],
        ...emptySets(),
        onToggle: vi.fn(),
        onToggleSeverityNone: vi.fn(),
        onClear: vi.fn(),
      },
    });
    const countPair = getAllByTestId("tag-filter-chip-counts")[0];
    // Total count span: the second .session-count (not .session-count--open)
    const allCountSpans = countPair.querySelectorAll(".session-count");
    const totalSpan = Array.from(allCountSpans).find(
      (s) => !s.classList.contains("session-count--open"),
    );
    expect(totalSpan).not.toBeNull();
    expect(totalSpan!.textContent).toBe("/7");
  });

  it("both counts visible for empty tag (0, 0)", () => {
    const { getAllByTestId } = render(TagFilterPanel, {
      props: {
        tags: [{ ...tag(1, "bearings", "project"), open_session_count: 0, session_count: 0 }],
        ...emptySets(),
        onToggle: vi.fn(),
        onToggleSeverityNone: vi.fn(),
        onClear: vi.fn(),
      },
    });
    const countPair = getAllByTestId("tag-filter-chip-counts")[0];
    expect(countPair.textContent).toContain("0");
    expect(countPair.textContent).toContain("/0");
  });

  // ---------------------------------------------------------------------------
  // "No severity" synthetic chip — gap-cycle-18-003
  // ---------------------------------------------------------------------------

  it("renders the No severity chip when the severity section is non-empty", () => {
    const { getByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "urgent", "severity")],
        ...emptySets(),
        onToggle: vi.fn(),
        onToggleSeverityNone: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(getByTestId("tag-filter-chip-severity-none")).toBeInTheDocument();
  });

  it("does NOT render the No severity chip when the severity section is empty", () => {
    const { queryByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "bearings", "project")],
        ...emptySets(),
        onToggle: vi.fn(),
        onToggleSeverityNone: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(queryByTestId("tag-filter-chip-severity-none")).toBeNull();
  });

  it("clicking the No severity chip fires onToggleSeverityNone", async () => {
    const onToggleSeverityNone = vi.fn();
    const { getByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "urgent", "severity")],
        ...emptySets(),
        onToggle: vi.fn(),
        onToggleSeverityNone,
        onClear: vi.fn(),
      },
    });
    await fireEvent.click(getByTestId("tag-filter-chip-severity-none"));
    expect(onToggleSeverityNone).toHaveBeenCalled();
  });

  it("No severity chip shows aria-pressed=true when selectedSeverityNone is true", () => {
    const { getByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "urgent", "severity")],
        ...emptySets(),
        selectedSeverityNone: true,
        onToggle: vi.fn(),
        onToggleSeverityNone: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(getByTestId("tag-filter-chip-severity-none")).toHaveAttribute("aria-pressed", "true");
  });

  it("No severity chip shows aria-pressed=false when selectedSeverityNone is false", () => {
    const { getByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "urgent", "severity")],
        ...emptySets(),
        onToggle: vi.fn(),
        onToggleSeverityNone: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(getByTestId("tag-filter-chip-severity-none")).toHaveAttribute("aria-pressed", "false");
  });

  it("selectedSeverityNone=true makes the clear button visible", () => {
    const { getByTestId } = render(TagFilterPanel, {
      props: {
        tags: [tag(1, "urgent", "severity")],
        ...emptySets(),
        selectedSeverityNone: true,
        onToggle: vi.fn(),
        onToggleSeverityNone: vi.fn(),
        onClear: vi.fn(),
      },
    });
    expect(getByTestId("tag-filter-clear")).toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // Collapse toggle — gap-cycle-18-004
  // ---------------------------------------------------------------------------

  describe("collapse toggle", () => {
    beforeEach(() => {
      _resetForTests();
      localStorage.clear();
    });

    afterEach(() => {
      _resetForTests();
      localStorage.clear();
    });

    it("renders the toggle button when tags exist", () => {
      const { getByTestId } = render(TagFilterPanel, { props: baseProps() });
      expect(getByTestId("tag-filter-collapse-toggle")).toBeInTheDocument();
    });

    it("does NOT render the toggle when tags list is empty", () => {
      const { queryByTestId } = render(TagFilterPanel, {
        props: baseProps({ tags: [] }),
      });
      expect(queryByTestId("tag-filter-collapse-toggle")).toBeNull();
    });

    it("chip body is visible by default (panel expanded)", () => {
      const { getByTestId } = render(TagFilterPanel, { props: baseProps() });
      // When expanded, at least one chip section is present.
      expect(getByTestId("tag-filter-section-project")).toBeInTheDocument();
    });

    it("clicking the toggle hides the chip body", async () => {
      const { getByTestId, queryByTestId } = render(TagFilterPanel, { props: baseProps() });
      await fireEvent.click(getByTestId("tag-filter-collapse-toggle"));
      expect(queryByTestId("tag-filter-section-project")).toBeNull();
    });

    it("clicking the toggle twice restores the chip body", async () => {
      const { getByTestId } = render(TagFilterPanel, { props: baseProps() });
      await fireEvent.click(getByTestId("tag-filter-collapse-toggle"));
      await fireEvent.click(getByTestId("tag-filter-collapse-toggle"));
      expect(getByTestId("tag-filter-section-project")).toBeInTheDocument();
    });

    it("toggle button shows 'Hide tags' when expanded", () => {
      const { getByTestId } = render(TagFilterPanel, { props: baseProps() });
      expect(getByTestId("tag-filter-collapse-toggle")).toHaveTextContent("Hide tags");
    });

    it("toggle button shows 'Show tags' when collapsed", async () => {
      const { getByTestId } = render(TagFilterPanel, { props: baseProps() });
      await fireEvent.click(getByTestId("tag-filter-collapse-toggle"));
      expect(getByTestId("tag-filter-collapse-toggle")).toHaveTextContent("Show tags");
    });

    it("aria-expanded is true when panel is expanded", () => {
      const { getByTestId } = render(TagFilterPanel, { props: baseProps() });
      expect(getByTestId("tag-filter-collapse-toggle")).toHaveAttribute("aria-expanded", "true");
    });

    it("aria-expanded is false when panel is collapsed", async () => {
      const { getByTestId } = render(TagFilterPanel, { props: baseProps() });
      await fireEvent.click(getByTestId("tag-filter-collapse-toggle"));
      expect(getByTestId("tag-filter-collapse-toggle")).toHaveAttribute("aria-expanded", "false");
    });

    it("aria-controls points at tag-filter-chip-body", () => {
      const { getByTestId } = render(TagFilterPanel, { props: baseProps() });
      expect(getByTestId("tag-filter-collapse-toggle")).toHaveAttribute(
        "aria-controls",
        "tag-filter-chip-body",
      );
    });

    it("toggle persists collapsed=true to localStorage", async () => {
      const { getByTestId } = render(TagFilterPanel, { props: baseProps() });
      await fireEvent.click(getByTestId("tag-filter-collapse-toggle"));
      expect(localStorage.getItem(TAG_FILTER_PANEL_COLLAPSED_KEY)).toBe("true");
    });

    it("toggle persists collapsed=false to localStorage on second click", async () => {
      const { getByTestId } = render(TagFilterPanel, { props: baseProps() });
      await fireEvent.click(getByTestId("tag-filter-collapse-toggle"));
      await fireEvent.click(getByTestId("tag-filter-collapse-toggle"));
      expect(localStorage.getItem(TAG_FILTER_PANEL_COLLAPSED_KEY)).toBe("false");
    });

    it("re-hydration from localStorage starts panel collapsed", () => {
      localStorage.setItem(TAG_FILTER_PANEL_COLLAPSED_KEY, "true");
      _hydrateTagPanelFromStorage();
      // tagsStore.panelCollapsed should now be true.
      expect(tagsStore.panelCollapsed).toBe(true);
      // A freshly-rendered component should reflect the hydrated state.
      const { queryByTestId } = render(TagFilterPanel, { props: baseProps() });
      expect(queryByTestId("tag-filter-section-project")).toBeNull();
    });

    it("re-hydration from missing key leaves panel expanded", () => {
      // localStorage is already clear from beforeEach.
      _hydrateTagPanelFromStorage();
      expect(tagsStore.panelCollapsed).toBe(false);
      const { getByTestId } = render(TagFilterPanel, { props: baseProps() });
      expect(getByTestId("tag-filter-section-project")).toBeInTheDocument();
    });

    it("active-filter breadcrumb hidden when expanded even with selection", () => {
      const { queryByTestId } = render(TagFilterPanel, {
        props: baseProps({ selectedProjectIds: new Set([1]) }),
      });
      expect(queryByTestId("tag-filter-collapsed-active-count")).toBeNull();
    });

    it("active-filter breadcrumb hidden when collapsed but no selection", async () => {
      const { getByTestId, queryByTestId } = render(TagFilterPanel, { props: baseProps() });
      await fireEvent.click(getByTestId("tag-filter-collapse-toggle"));
      expect(queryByTestId("tag-filter-collapsed-active-count")).toBeNull();
    });

    it("active-filter breadcrumb visible when collapsed AND a project tag is selected", async () => {
      const { getByTestId } = render(TagFilterPanel, {
        props: baseProps({ selectedProjectIds: new Set([1]) }),
      });
      await fireEvent.click(getByTestId("tag-filter-collapse-toggle"));
      expect(getByTestId("tag-filter-collapsed-active-count")).toBeInTheDocument();
      expect(getByTestId("tag-filter-collapsed-active-count")).toHaveTextContent("1 on");
    });

    it("active-filter breadcrumb shows correct count for multiple selections", async () => {
      const { getByTestId } = render(TagFilterPanel, {
        props: baseProps({
          tags: [
            tag(1, "bearings", "project"),
            tag(2, "urgent", "severity"),
            tag(3, "misc", "general"),
          ],
          selectedProjectIds: new Set([1]),
          selectedSeverityIds: new Set([2]),
          selectedOtherIds: new Set([3]),
        }),
      });
      await fireEvent.click(getByTestId("tag-filter-collapse-toggle"));
      expect(getByTestId("tag-filter-collapsed-active-count")).toHaveTextContent("3 on");
    });

    it("active-filter breadcrumb counts severityNone as a selection", async () => {
      const { getByTestId } = render(TagFilterPanel, {
        props: baseProps({
          tags: [tag(1, "urgent", "severity")],
          selectedSeverityNone: true,
        }),
      });
      await fireEvent.click(getByTestId("tag-filter-collapse-toggle"));
      expect(getByTestId("tag-filter-collapsed-active-count")).toHaveTextContent("1 on");
    });
  });
});
