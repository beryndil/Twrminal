/**
 * Component tests for ``DataView`` — loading / error / empty / success
 * state dispatch, retry callback, and empty-slot override.
 *
 * Gap: gap-cycle-01-011.
 */
import { render } from "@testing-library/svelte";
import { fireEvent } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import DataView from "../DataView.svelte";
import DataViewLoadingHarness from "./harness/DataViewLoadingHarness.svelte";
import DataViewErrorHarness from "./harness/DataViewErrorHarness.svelte";
import DataViewEmptyHarness from "./harness/DataViewEmptyHarness.svelte";
import DataViewEmptySlotHarness from "./harness/DataViewEmptySlotHarness.svelte";
import DataViewSuccessHarness from "./harness/DataViewSuccessHarness.svelte";

// ---------------------------------------------------------------------------
// Loading state
// ---------------------------------------------------------------------------

describe("DataView — loading state", () => {
  it("renders the loading skeleton when loading=true", () => {
    const { getByTestId, queryByTestId } = render(DataViewLoadingHarness);

    expect(getByTestId("data-view-loading")).toBeInTheDocument();
    expect(queryByTestId("data-view-error")).toBeNull();
    expect(queryByTestId("data-view-empty")).toBeNull();
    expect(queryByTestId("data-view-success")).toBeNull();
  });

  it("loading region has role=status and aria-busy=true", () => {
    const { getByTestId } = render(DataViewLoadingHarness);

    const region = getByTestId("data-view-loading");
    expect(region).toHaveAttribute("role", "status");
    expect(region).toHaveAttribute("aria-busy", "true");
  });

  it("renders deterministic skeleton bars (three bars, no random content)", () => {
    const { getAllByTestId } = render(DataViewLoadingHarness);

    const bars = getAllByTestId("data-view-skeleton-bar");
    expect(bars).toHaveLength(3);
  });
});

// ---------------------------------------------------------------------------
// Error state
// ---------------------------------------------------------------------------

describe("DataView — error state", () => {
  it("renders the error region when error is a non-empty string", () => {
    const { getByTestId, queryByTestId } = render(DataViewErrorHarness);

    expect(getByTestId("data-view-error")).toBeInTheDocument();
    expect(queryByTestId("data-view-loading")).toBeNull();
    expect(queryByTestId("data-view-empty")).toBeNull();
    expect(queryByTestId("data-view-success")).toBeNull();
  });

  it("error region has role=alert", () => {
    const { getByTestId } = render(DataViewErrorHarness);

    expect(getByTestId("data-view-error")).toHaveAttribute("role", "alert");
  });

  it("displays the supplied error message", () => {
    const { getByTestId } = render(DataViewErrorHarness);

    expect(getByTestId("data-view-error-message")).toHaveTextContent(
      "Test error message",
    );
  });

  it("renders the retry button", () => {
    const { getByTestId } = render(DataViewErrorHarness);

    expect(getByTestId("data-view-retry")).toBeInTheDocument();
  });

  it("hides the retry button when onretry is not supplied", () => {
    const { queryByTestId } = render(DataView, {
      props: { error: "boom" },
    });

    expect(queryByTestId("data-view-retry")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Retry callback
// ---------------------------------------------------------------------------

describe("DataView — retry callback", () => {
  it("calls onretry when the retry button is clicked", async () => {
    const onretry = vi.fn();
    const { getByTestId } = render(DataView, {
      props: { error: "fetch failed", onretry },
    });

    await fireEvent.click(getByTestId("data-view-retry"));

    expect(onretry).toHaveBeenCalledOnce();
  });

  it("calls onretry on repeated clicks", async () => {
    const onretry = vi.fn();
    const { getByTestId } = render(DataView, {
      props: { error: "fetch failed", onretry },
    });

    await fireEvent.click(getByTestId("data-view-retry"));
    await fireEvent.click(getByTestId("data-view-retry"));

    expect(onretry).toHaveBeenCalledTimes(2);
  });
});

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

describe("DataView — empty state", () => {
  it("renders the empty region when isEmpty=true and not loading/errored", () => {
    const { getByTestId, queryByTestId } = render(DataViewEmptyHarness);

    expect(getByTestId("data-view-empty")).toBeInTheDocument();
    expect(queryByTestId("data-view-loading")).toBeNull();
    expect(queryByTestId("data-view-error")).toBeNull();
    expect(queryByTestId("data-view-success")).toBeNull();
  });

  it("renders the default empty-state copy when no empty snippet is supplied", () => {
    const { getByTestId } = render(DataView, {
      props: { isEmpty: true },
    });

    expect(getByTestId("data-view-empty-default")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Empty-slot override
// ---------------------------------------------------------------------------

describe("DataView — empty-slot override", () => {
  it("renders the custom empty snippet instead of the default copy", () => {
    const { getByTestId, queryByTestId } = render(DataViewEmptySlotHarness);

    expect(getByTestId("data-view-empty")).toBeInTheDocument();
    expect(getByTestId("custom-empty-content")).toBeInTheDocument();
    expect(queryByTestId("data-view-empty-default")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Success state
// ---------------------------------------------------------------------------

describe("DataView — success state", () => {
  it("renders the success slot when not loading, not errored, not empty", () => {
    const { getByTestId, queryByTestId } = render(DataViewSuccessHarness);

    expect(getByTestId("data-view-success")).toBeInTheDocument();
    expect(queryByTestId("data-view-loading")).toBeNull();
    expect(queryByTestId("data-view-error")).toBeNull();
    expect(queryByTestId("data-view-empty")).toBeNull();
  });

  it("renders the children content inside the success wrapper", () => {
    const { getByTestId } = render(DataViewSuccessHarness);

    expect(getByTestId("success-body-content")).toBeInTheDocument();
  });

  it("loading takes priority over error", () => {
    const { getByTestId, queryByTestId } = render(DataView, {
      props: { loading: true, error: "also errored" },
    });

    expect(getByTestId("data-view-loading")).toBeInTheDocument();
    expect(queryByTestId("data-view-error")).toBeNull();
  });

  it("error takes priority over empty", () => {
    const { getByTestId, queryByTestId } = render(DataView, {
      props: { error: "problem", isEmpty: true },
    });

    expect(getByTestId("data-view-error")).toBeInTheDocument();
    expect(queryByTestId("data-view-empty")).toBeNull();
  });
});
