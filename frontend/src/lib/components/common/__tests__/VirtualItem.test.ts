/**
 * Unit tests for ``VirtualItem`` and ``VirtualItemHarness``
 * (gap-cycle-01-012).
 *
 * Coverage:
 * - Starts mounted — initial render shows slot content, no placeholder.
 * - Mount on intersection — content re-appears when isIntersecting=true.
 * - Unmount on leave — placeholder replaces content when isIntersecting=false.
 * - Placeholder height correctness — wrapper carries the measured height
 *   as an explicit style, keeping scroll geometry stable.
 * - Fixed height cleared on re-mount — content drives its own height
 *   after becoming visible again.
 * - rootMargin forwarded — the prop value reaches IntersectionObserver.
 * - Observer disconnects on component destroy.
 * - VirtualItemHarness renders its container.
 *
 * IntersectionObserver is not implemented in jsdom; the global no-op
 * stub from ``vitest.setup.ts`` keeps other components with
 * ``VirtualItem`` working. These tests install a *controllable* mock
 * via ``vi.stubGlobal`` in ``beforeEach`` to drive intersection events,
 * then restore the original (no-op) stub in ``afterEach``.
 */
import { render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import VirtualItem from "../VirtualItem.svelte";
import VirtualItemHarness from "../VirtualItemHarness.svelte";
import VirtualItemContentHarness from "./harness/VirtualItemContentHarness.svelte";

// ---------------------------------------------------------------------------
// Controllable IntersectionObserver mock
// ---------------------------------------------------------------------------

type IOCallback = (entries: IntersectionObserverEntry[]) => void;

/**
 * State captured when the mock constructor runs.  Reset in
 * ``beforeEach`` so each test starts with a clean slate.
 */
let activeCallback: IOCallback | null = null;
let activeObservedEl: Element | null = null;
let mockDisconnect: ReturnType<typeof vi.fn> | null = null;

function buildMockIO(): typeof IntersectionObserver {
  // vitest@4: mockImplementation must be a regular function (not arrow) so
  // `new IntersectionObserver(...)` in component code works as a constructor.
  return vi.fn().mockImplementation(function (cb: IOCallback, _options: object) {
    activeCallback = cb;
    mockDisconnect = vi.fn();
    const instance = {
      observe: vi.fn((el: Element) => {
        activeObservedEl = el;
      }),
      unobserve: vi.fn(),
      disconnect: mockDisconnect,
    };
    return instance;
  }) as unknown as typeof IntersectionObserver;
}

/**
 * Fire a synthetic intersection callback for the currently observed
 * element.  ``measuredHeight`` is stubbed on the element's
 * ``getBoundingClientRect`` so the component can capture it.
 */
function triggerIntersection(isIntersecting: boolean, measuredHeight = 0): void {
  if (activeCallback === null || activeObservedEl === null) {
    throw new Error("No IntersectionObserver installed — did the component mount?");
  }
  vi.spyOn(activeObservedEl as HTMLElement, "getBoundingClientRect").mockReturnValue({
    height: measuredHeight,
    width: 100,
    top: 0,
    left: 0,
    right: 100,
    bottom: measuredHeight,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  });
  activeCallback([
    {
      isIntersecting,
      target: activeObservedEl,
      intersectionRatio: isIntersecting ? 1 : 0,
      boundingClientRect: (activeObservedEl as HTMLElement).getBoundingClientRect(),
      intersectionRect: {} as DOMRectReadOnly,
      rootBounds: null,
      time: performance.now(),
    } as IntersectionObserverEntry,
  ]);
}

beforeEach(() => {
  activeCallback = null;
  activeObservedEl = null;
  mockDisconnect = null;
  vi.stubGlobal("IntersectionObserver", buildMockIO());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Initial render
// ---------------------------------------------------------------------------

describe("VirtualItem — initial render", () => {
  it("starts mounted: slot content is visible, no placeholder", () => {
    const { getByTestId, queryByTestId } = render(VirtualItemContentHarness);

    expect(getByTestId("virtual-item")).toBeInTheDocument();
    expect(getByTestId("virtual-item-test-content")).toBeInTheDocument();
    expect(queryByTestId("virtual-item-placeholder")).toBeNull();
  });

  it("wrapper has no explicit height style on initial mount", () => {
    const { getByTestId } = render(VirtualItemContentHarness);

    // No fixed height — content drives natural height.
    const wrapper = getByTestId("virtual-item");
    expect(wrapper).not.toHaveAttribute("style");
  });
});

// ---------------------------------------------------------------------------
// Unmount on leave
// ---------------------------------------------------------------------------

describe("VirtualItem — unmount on leave", () => {
  it("replaces slot content with a placeholder when isIntersecting=false", async () => {
    const { getByTestId, queryByTestId } = render(VirtualItemContentHarness);

    triggerIntersection(false, 48);

    await waitFor(() => {
      expect(getByTestId("virtual-item-placeholder")).toBeInTheDocument();
      expect(queryByTestId("virtual-item-test-content")).toBeNull();
    });
  });

  it("placeholder carries aria-hidden=true", async () => {
    const { getByTestId } = render(VirtualItemContentHarness);

    triggerIntersection(false, 48);

    await waitFor(() => {
      expect(getByTestId("virtual-item-placeholder")).toHaveAttribute("aria-hidden", "true");
    });
  });
});

// ---------------------------------------------------------------------------
// Mount on intersection
// ---------------------------------------------------------------------------

describe("VirtualItem — mount on intersection", () => {
  it("re-mounts slot content when isIntersecting=true after a leave", async () => {
    const { getByTestId, queryByTestId } = render(VirtualItemContentHarness);

    // First leave the viewport.
    triggerIntersection(false, 48);
    await waitFor(() => expect(getByTestId("virtual-item-placeholder")).toBeInTheDocument());

    // Then re-enter.
    triggerIntersection(true);
    await waitFor(() => {
      expect(getByTestId("virtual-item-test-content")).toBeInTheDocument();
      expect(queryByTestId("virtual-item-placeholder")).toBeNull();
    });
  });
});

// ---------------------------------------------------------------------------
// Placeholder height correctness
// ---------------------------------------------------------------------------

describe("VirtualItem — placeholder height", () => {
  it("applies the measured height to the wrapper when content is unmounted", async () => {
    const { getByTestId } = render(VirtualItemContentHarness);

    triggerIntersection(false, 64);

    await waitFor(() => {
      expect(getByTestId("virtual-item")).toHaveStyle("height: 64px");
    });
  });

  it("preserves the height from the most recent getBoundingClientRect call", async () => {
    const { getByTestId } = render(VirtualItemContentHarness);

    // Leave at height 32, re-enter, leave again at height 80.
    triggerIntersection(false, 32);
    await waitFor(() => expect(getByTestId("virtual-item")).toHaveStyle("height: 32px"));

    triggerIntersection(true);
    await waitFor(() => expect(getByTestId("virtual-item-test-content")).toBeInTheDocument());

    triggerIntersection(false, 80);
    await waitFor(() => {
      expect(getByTestId("virtual-item")).toHaveStyle("height: 80px");
    });
  });

  it("clears the fixed height when content re-mounts", async () => {
    const { getByTestId } = render(VirtualItemContentHarness);

    triggerIntersection(false, 64);
    await waitFor(() => expect(getByTestId("virtual-item-placeholder")).toBeInTheDocument());

    triggerIntersection(true);
    await waitFor(() => {
      // When visible, the explicit height style must be absent so
      // content can determine its own natural height.
      expect(getByTestId("virtual-item")).not.toHaveStyle("height: 64px");
    });
  });
});

// ---------------------------------------------------------------------------
// rootMargin prop
// ---------------------------------------------------------------------------

describe("VirtualItem — rootMargin", () => {
  it("passes the default rootMargin (200px 0px) to IntersectionObserver", () => {
    render(VirtualItemContentHarness);

    expect(IntersectionObserver).toHaveBeenCalledWith(
      expect.any(Function),
      expect.objectContaining({ rootMargin: "200px 0px" }),
    );
  });

  it("passes a custom rootMargin to IntersectionObserver", () => {
    render(VirtualItem, { props: { rootMargin: "50px 0px" } });

    expect(IntersectionObserver).toHaveBeenCalledWith(
      expect.any(Function),
      expect.objectContaining({ rootMargin: "50px 0px" }),
    );
  });
});

// ---------------------------------------------------------------------------
// Observer lifecycle
// ---------------------------------------------------------------------------

describe("VirtualItem — observer lifecycle", () => {
  it("disconnects the observer when the component is destroyed", async () => {
    const { unmount } = render(VirtualItemContentHarness);

    unmount();

    await waitFor(() => {
      expect(mockDisconnect).toHaveBeenCalledOnce();
    });
  });
});

// ---------------------------------------------------------------------------
// VirtualItemHarness
// ---------------------------------------------------------------------------

describe("VirtualItemHarness — story harness", () => {
  it("renders the harness container and scroll viewport", () => {
    const { getByTestId } = render(VirtualItemHarness);

    expect(getByTestId("virtual-item-harness")).toBeInTheDocument();
    expect(getByTestId("virtual-item-harness-scroll")).toBeInTheDocument();
  });

  it("mounts a synthetic 1000-row list (all rows start visible)", () => {
    const { getAllByTestId } = render(VirtualItemHarness);

    // With the no-op IntersectionObserver override, all 1000 rows
    // remain mounted; VirtualItem-specific tests use the controllable
    // mock to exercise unmount/remount paths separately.
    const rows = getAllByTestId("virtual-item-harness-row");
    expect(rows).toHaveLength(1000);
  });
});
