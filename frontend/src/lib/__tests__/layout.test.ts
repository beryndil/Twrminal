/**
 * Layout-shape regression test for the app shell.
 *
 * Asserts the three-column grid that `docs/behavior/chat.md`
 * §"opens an existing chat" describes — sidebar / main / inspector —
 * so a refactor cannot silently collapse one of the columns.
 *
 * SvelteKit's ``$app/state`` and ``$app/navigation`` are stubbed
 * because the layout reads ``page.params.id`` to sync the inspector
 * store from the URL and dispatches client-nav via ``goto`` on
 * synthetic ``onSelect`` activations. The stubs let the layout mount
 * without a SvelteKit harness — vitest renders components against
 * the bare component runtime, not a SvelteKit page server.
 *
 * The preferences store is stubbed so ``refreshPreferences`` does not
 * issue a real HTTP request on mount (gap-cycle-08-002).
 */
import { fireEvent, render } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$app/state", () => ({
  page: { params: {}, route: { id: "/" }, url: { pathname: "/" } },
}));
vi.mock("$app/navigation", () => ({
  goto: vi.fn(),
}));

// Stub the preferences store so no HTTP request is made on mount
// (gap-cycle-08-002).  The identity block renders with the fallback
// name / silhouette, which is all these tests need to assert.
vi.mock("$lib/stores/preferences.svelte", () => ({
  preferencesStore: { displayName: null, avatarUrl: null, cacheBust: "" },
  refreshPreferences: vi.fn(),
  applyPreferences: vi.fn(),
}));

import { goto } from "$app/navigation";
import Layout from "../../routes/+layout.svelte";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("app shell layout", () => {
  it("renders sidebar, main and inspector regions", () => {
    const { getByTestId } = render(Layout);

    expect(getByTestId("app-shell")).toBeInTheDocument();
    expect(getByTestId("app-shell-sidebar")).toBeInTheDocument();
    expect(getByTestId("app-shell-main")).toBeInTheDocument();
    expect(getByTestId("app-shell-inspector")).toBeInTheDocument();
  });

  it("center column has header, body and composer slots", () => {
    const { getByTestId } = render(Layout);

    expect(getByTestId("app-shell-main-header")).toBeInTheDocument();
    expect(getByTestId("app-shell-main-body")).toBeInTheDocument();
    expect(getByTestId("app-shell-main-composer")).toBeInTheDocument();
  });

  it("labels each region with an ARIA landmark for screen readers", () => {
    const { getByLabelText } = render(Layout);

    expect(getByLabelText("Sessions sidebar")).toBeInTheDocument();
    expect(getByLabelText("Conversation pane")).toBeInTheDocument();
    expect(getByLabelText("Inspector")).toBeInTheDocument();
  });
});

describe("sidebar nav vault link (gap-cycle-08-003)", () => {
  it("renders the vault nav link inside the sidebar nav", () => {
    const { getByTestId } = render(Layout);

    const nav = getByTestId("sidebar-nav");
    const link = nav.querySelector('[data-testid="sidebar-nav-vault"]');
    expect(link).toBeInTheDocument();
  });

  it("vault nav link points to /vault", () => {
    const { getByTestId } = render(Layout);

    const link = getByTestId("sidebar-nav-vault") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/vault");
  });

  it("vault nav link carries the Open vault aria-label", () => {
    const { getByTestId } = render(Layout);

    const link = getByTestId("sidebar-nav-vault");
    expect(link.getAttribute("aria-label")).toBe("Open vault (plans + TODOs)");
  });
});

describe("sidebar identity block (gap-cycle-08-002)", () => {
  it("renders user-identity-block inside the sidebar", () => {
    const { getByTestId } = render(Layout);

    const sidebar = getByTestId("app-shell-sidebar");
    const block = sidebar.querySelector('[data-testid="user-identity-block"]');
    expect(block).toBeInTheDocument();
  });

  it("clicking the identity block navigates to /settings", async () => {
    const { getByTestId } = render(Layout);

    await fireEvent.click(getByTestId("sidebar-identity-btn"));

    expect(goto).toHaveBeenCalledWith("/settings");
  });
});
