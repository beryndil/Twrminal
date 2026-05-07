/**
 * Component tests for ``CollapsibleBody`` — fold threshold, expand /
 * collapse toggle, and ResizeObserver re-measurement.
 *
 * ResizeObserver is unavailable in jsdom; we install a minimal stub
 * that lets tests drive the callback manually.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CollapsibleBody from "../CollapsibleBody.svelte";

// ---------------------------------------------------------------------------
// ResizeObserver stub
// ---------------------------------------------------------------------------

/** Inline type matching the ResizeObserver callback signature. */
type ResizeCallback = (entries: ResizeObserverEntry[], observer: ResizeObserver) => void;

/** Last callback registered by a ``new ResizeObserver(cb)`` call. */
let capturedCallback: ResizeCallback | null = null;

function makeObserverStub(): typeof ResizeObserver {
  return class MockResizeObserver {
    constructor(cb: ResizeCallback) {
      capturedCallback = cb;
    }
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
  } as unknown as typeof ResizeObserver;
}

/**
 * Fire the captured ResizeObserver callback with the given content
 * height, simulating the browser measuring the inner content element.
 */
function triggerResize(height: number): void {
  if (capturedCallback === null) {
    throw new Error("No ResizeObserver callback captured — was the component mounted?");
  }
  capturedCallback(
    [{ contentRect: { height } } as ResizeObserverEntry],
    {} as ResizeObserver,
  );
}

beforeEach(() => {
  capturedCallback = null;
  vi.stubGlobal("ResizeObserver", makeObserverStub());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("CollapsibleBody — under threshold", () => {
  it("renders children with no fold UI when content height is below the threshold", async () => {
    const { queryByTestId } = render(CollapsibleBody, {
      props: { thresholdPx: 320 },
    });

    triggerResize(100);

    await waitFor(() => {
      expect(queryByTestId("collapsible-body-show")).toBeNull();
      expect(queryByTestId("collapsible-body-collapse")).toBeNull();
    });

    // data-over-threshold should be false
    const inner = queryByTestId("collapsible-body-inner");
    expect(inner).toHaveAttribute("data-over-threshold", "false");
  });

  it("data-expanded is false when under threshold", async () => {
    const { queryByTestId } = render(CollapsibleBody, {
      props: { thresholdPx: 320 },
    });

    triggerResize(50);

    await waitFor(() => {
      expect(queryByTestId("collapsible-body-inner")).toHaveAttribute("data-expanded", "false");
    });
  });
});

describe("CollapsibleBody — over threshold", () => {
  it("shows the 'Show full' button when content height exceeds the threshold", async () => {
    const { getByTestId } = render(CollapsibleBody, {
      props: { thresholdPx: 320 },
    });

    triggerResize(500);

    await waitFor(() => {
      expect(getByTestId("collapsible-body-show")).toBeInTheDocument();
    });

    expect(getByTestId("collapsible-body-show")).toHaveTextContent("Show full");
  });

  it("sets data-over-threshold to true when over the threshold", async () => {
    const { getByTestId } = render(CollapsibleBody, {
      props: { thresholdPx: 320 },
    });

    triggerResize(400);

    await waitFor(() => {
      expect(getByTestId("collapsible-body-inner")).toHaveAttribute("data-over-threshold", "true");
    });
  });

  it("applies max-height and mask-image inline style when folded and over threshold", async () => {
    const { getByTestId } = render(CollapsibleBody, {
      props: { thresholdPx: 320 },
    });

    triggerResize(500);

    await waitFor(() => {
      const inner = getByTestId("collapsible-body-inner");
      expect(inner.style.maxHeight).toBe("320px");
      expect(inner.style.overflow).toBe("hidden");
      // mask-image is set (either prefixed or unprefixed variant is present)
      const hasMask =
        inner.style.maskImage !== "" ||
        inner.style.getPropertyValue("-webkit-mask-image") !== "";
      expect(hasMask).toBe(true);
    });
  });
});

describe("CollapsibleBody — expand toggle", () => {
  it("clicking 'Show full' expands the wrapper and replaces the button with 'Collapse'", async () => {
    const { getByTestId, queryByTestId } = render(CollapsibleBody, {
      props: { thresholdPx: 320 },
    });

    triggerResize(500);

    await waitFor(() => {
      expect(getByTestId("collapsible-body-show")).toBeInTheDocument();
    });

    await fireEvent.click(getByTestId("collapsible-body-show"));

    await waitFor(() => {
      expect(queryByTestId("collapsible-body-show")).toBeNull();
      expect(getByTestId("collapsible-body-collapse")).toBeInTheDocument();
    });

    expect(getByTestId("collapsible-body-collapse")).toHaveTextContent("Collapse");
  });

  it("data-expanded flips to true after clicking 'Show full'", async () => {
    const { getByTestId } = render(CollapsibleBody, {
      props: { thresholdPx: 320 },
    });

    triggerResize(500);
    await waitFor(() => getByTestId("collapsible-body-show"));

    await fireEvent.click(getByTestId("collapsible-body-show"));

    await waitFor(() => {
      expect(getByTestId("collapsible-body-inner")).toHaveAttribute("data-expanded", "true");
    });
  });

  it("clamp style is removed after expanding", async () => {
    const { getByTestId } = render(CollapsibleBody, {
      props: { thresholdPx: 320 },
    });

    triggerResize(500);
    await waitFor(() => getByTestId("collapsible-body-show"));

    await fireEvent.click(getByTestId("collapsible-body-show"));

    await waitFor(() => {
      const inner = getByTestId("collapsible-body-inner");
      expect(inner.style.maxHeight).toBe("");
    });
  });

  it("clicking 'Collapse' re-folds the wrapper and shows 'Show full' again", async () => {
    const { getByTestId, queryByTestId } = render(CollapsibleBody, {
      props: { thresholdPx: 320 },
    });

    triggerResize(500);
    await waitFor(() => getByTestId("collapsible-body-show"));

    await fireEvent.click(getByTestId("collapsible-body-show"));
    await waitFor(() => getByTestId("collapsible-body-collapse"));

    await fireEvent.click(getByTestId("collapsible-body-collapse"));

    await waitFor(() => {
      expect(queryByTestId("collapsible-body-collapse")).toBeNull();
      expect(getByTestId("collapsible-body-show")).toBeInTheDocument();
    });
  });
});

describe("CollapsibleBody — observer re-triggers on content change", () => {
  it("transitions from under to over threshold when the observer fires again with a larger height", async () => {
    const { getByTestId, queryByTestId } = render(CollapsibleBody, {
      props: { thresholdPx: 320 },
    });

    // Initial: content is short — no fold UI.
    triggerResize(100);
    await waitFor(() => {
      expect(queryByTestId("collapsible-body-show")).toBeNull();
    });

    // Streaming content grows past the threshold.
    triggerResize(500);
    await waitFor(() => {
      expect(getByTestId("collapsible-body-show")).toBeInTheDocument();
    });
  });

  it("uses the custom thresholdPx prop as the comparison boundary", async () => {
    const { getByTestId, queryByTestId } = render(CollapsibleBody, {
      props: { thresholdPx: 200 },
    });

    triggerResize(199);
    await waitFor(() => {
      expect(queryByTestId("collapsible-body-show")).toBeNull();
    });

    triggerResize(201);
    await waitFor(() => {
      expect(getByTestId("collapsible-body-show")).toBeInTheDocument();
    });
  });
});
