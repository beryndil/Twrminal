/**
 * Route test for ``/sessions/[id]/+page.svelte`` — mounting the route
 * with a synthetic ``$app/state.page`` value calls
 * :func:`setActiveSession` with the URL parameter.
 *
 * The route file does not render any visible chrome of its own (the
 * layout owns the conversation/composer panes), so the test asserts
 * on the side-effect: the inspector store's ``activeSessionId``
 * matches the URL after mount.
 */
import { render } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { pageState } = vi.hoisted(() => ({
  pageState: { params: { id: "ses_route" }, route: { id: "/sessions/[id]" } },
}));

vi.mock("$app/state", () => ({
  page: pageState,
}));

import Page from "./+page.svelte";
import { _resetForTests, inspectorStore } from "$lib/stores/inspector.svelte";

beforeEach(() => {
  _resetForTests();
  pageState.params.id = "ses_route";
});
afterEach(() => {
  vi.clearAllMocks();
});

describe("/sessions/[id] route", () => {
  it("syncs the inspector store's activeSessionId from the URL parameter on mount", () => {
    expect(inspectorStore.activeSessionId).toBeNull();
    render(Page);
    expect(inspectorStore.activeSessionId).toBe("ses_route");
  });

  it("syncs to a different id when the route param changes", () => {
    pageState.params.id = "ses_first";
    render(Page);
    expect(inspectorStore.activeSessionId).toBe("ses_first");
  });
});
