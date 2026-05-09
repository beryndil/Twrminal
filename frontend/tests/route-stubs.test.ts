/**
 * Route-resolution smoke tests for BUG-NET-24-FE.
 *
 * Five routes were missing from the SvelteKit dist, causing in-app 404s
 * on direct navigation. This suite verifies that each route component
 * mounts without throwing and exposes its expected ``data-testid`` root
 * element, confirming the SvelteKit router now has a handler for each path.
 *
 * ``/preferences`` is tested separately because it is a redirect stub —
 * it calls ``goto("/settings", { replaceState: true })`` on mount rather
 * than rendering visible chrome.
 */
import { render } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---- SvelteKit shims (declared before any module import that pulls them) ----

vi.mock("$app/navigation", () => ({
  goto: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("$app/state", () => ({
  page: {
    url: { pathname: "", searchParams: { get: () => null } },
    route: { id: "" },
    params: {},
  },
}));

// ---- Imports ----------------------------------------------------------------

import { goto } from "$app/navigation";
import DashboardPage from "../src/routes/dashboard/+page.svelte";
import ChatPage from "../src/routes/chat/+page.svelte";
import HistoryPage from "../src/routes/history/+page.svelte";
import PreferencesPage from "../src/routes/preferences/+page.svelte";
import PairedPage from "../src/routes/paired/+page.svelte";

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.clearAllMocks();
});

// ---- Route smoke tests (BUG-NET-24-FE) -------------------------------------

describe("BUG-NET-24-FE — stub route resolution", () => {
  it("/dashboard renders its root element without throwing", () => {
    const { getByTestId } = render(DashboardPage);
    expect(getByTestId("dashboard-page")).toBeInTheDocument();
  });

  it("/chat renders its root element without throwing", () => {
    const { getByTestId } = render(ChatPage);
    expect(getByTestId("chat-page")).toBeInTheDocument();
  });

  it("/history renders its root element without throwing", () => {
    const { getByTestId } = render(HistoryPage);
    expect(getByTestId("history-page")).toBeInTheDocument();
  });

  it("/preferences mounts without throwing and calls goto('/settings')", async () => {
    render(PreferencesPage);
    // onMount fires asynchronously — flush the microtask queue.
    await vi.waitFor(() => {
      expect(goto).toHaveBeenCalledWith("/settings", { replaceState: true });
    });
  });

  it("/paired renders its root element without throwing", () => {
    const { getByTestId } = render(PairedPage);
    expect(getByTestId("paired-page")).toBeInTheDocument();
  });
});
