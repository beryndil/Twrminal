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

describe("sidebar templates button (gap-cycle-08-007)", () => {
  it("renders the templates button inside the sidebar", () => {
    const { getByTestId } = render(Layout);

    const sidebar = getByTestId("app-shell-sidebar");
    const btn = sidebar.querySelector('[data-testid="sidebar-templates-button"]');
    expect(btn).toBeInTheDocument();
  });

  it("templates button carries the correct aria-label", () => {
    const { getByTestId } = render(Layout);

    const btn = getByTestId("sidebar-templates-button");
    // Updated: WCAG 2.5.3 requires aria-label to contain visible text "Templates…".
    expect(btn.getAttribute("aria-label")).toBe("Templates… — open picker");
  });

  it("clicking the templates button opens the TemplatePicker dialog", async () => {
    const { getByTestId, queryByTestId } = render(Layout);

    // Picker is closed initially.
    expect(queryByTestId("template-picker")).not.toBeInTheDocument();

    await fireEvent.click(getByTestId("sidebar-templates-button"));

    // After click the backdrop / dialog should be visible.
    expect(queryByTestId("template-picker")).toBeInTheDocument();
  });
});

describe("sidebar row hydration layout (F1-RT-06 regression)", () => {
  /**
   * The session-list outer div must use ``flex-1`` (flex child sizing)
   * rather than ``h-full`` (percentage-height sizing).  A flex item
   * inside an ``overflow: hidden`` flex container has a definite height
   * from the flex algorithm; ``height: 100%`` (h-full) may not resolve
   * against that definite height in some Chromium builds, leaving the
   * nav inside with ``clientHeight: 0`` and causing every VirtualItem
   * to be classified as off-screen by IntersectionObserver.
   *
   * This test pins the class shape so a future refactor cannot silently
   * regress back to ``h-full``.
   */
  it("session-list outer div has flex-1 class (not h-full)", () => {
    const { getByTestId } = render(Layout);

    const sessionList = getByTestId("session-list");
    expect(sessionList).toHaveClass("flex-1");
    expect(sessionList).not.toHaveClass("h-full");
  });

  it("session-list outer div has min-h-0 class to allow flex shrinking", () => {
    const { getByTestId } = render(Layout);

    const sessionList = getByTestId("session-list");
    expect(sessionList).toHaveClass("min-h-0");
  });

  it("session-list-body nav exists inside the sidebar body", () => {
    const { getByTestId } = render(Layout);

    const nav = getByTestId("session-list-body");
    expect(nav).toBeInTheDocument();
    expect(nav.tagName.toLowerCase()).toBe("nav");
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
