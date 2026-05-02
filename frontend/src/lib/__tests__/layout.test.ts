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
 */
import { render } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

vi.mock("$app/state", () => ({
  page: { params: {}, route: { id: "/" } },
}));
vi.mock("$app/navigation", () => ({
  goto: vi.fn(),
}));

import Layout from "../../routes/+layout.svelte";

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
