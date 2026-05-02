/**
 * Inspector shell tests — tab strip rendering, default-tab landing,
 * tab switching, and the empty-session branch.
 *
 * The shell exposes a prop seam (``inspectorStore`` /
 * ``setInspectorTab``) for test isolation, but the ``$state`` proxy
 * the production singleton ships is the simplest way to exercise the
 * reactive subscription path. Each test resets the singleton in
 * ``beforeEach`` so cross-test state doesn't leak.
 */
import { fireEvent, render } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";

import Inspector from "../Inspector.svelte";
import {
  DEFAULT_INSPECTOR_TAB,
  INSPECTOR_STRINGS,
  INSPECTOR_TAB_AGENT,
  INSPECTOR_TAB_CONTEXT,
  INSPECTOR_TAB_INSTRUCTIONS,
  INSPECTOR_TAB_ROUTING,
  INSPECTOR_TAB_USAGE,
  KNOWN_INSPECTOR_TABS,
  type InspectorTabId,
} from "../../../config";
import type { SessionOut } from "../../../api/sessions";
import { _resetForTests, inspectorStore, setInspectorTab } from "../../../stores/inspector.svelte";

function fakeSession(overrides: Partial<SessionOut> = {}): SessionOut {
  return {
    id: "ses_a",
    kind: "chat",
    title: "Fixture session",
    description: null,
    session_instructions: null,
    working_dir: "/wd",
    model: "sonnet",
    permission_mode: null,
    max_budget_usd: null,
    total_cost_usd: 0,
    message_count: 0,
    last_context_pct: null,
    last_context_tokens: null,
    last_context_max: null,
    pinned: false,
    error_pending: false,
    checklist_item_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    last_viewed_at: null,
    last_completed_at: null,
    closed_at: null,
    closing_summary: null,
    ...overrides,
  };
}

beforeEach(() => {
  _resetForTests();
});

describe("Inspector shell — tab strip", () => {
  it("renders one tab button per documented tab id", () => {
    const { getAllByTestId } = render(Inspector, { props: { session: fakeSession() } });
    const tabs = getAllByTestId("inspector-tab");
    expect(tabs).toHaveLength(KNOWN_INSPECTOR_TABS.length);
    const ids = tabs.map((el) => el.dataset.tabId);
    expect(ids).toEqual([...KNOWN_INSPECTOR_TABS]);
  });

  it("labels each tab from INSPECTOR_STRINGS.tabLabels", () => {
    const { getAllByTestId } = render(Inspector, { props: { session: fakeSession() } });
    const tabs = getAllByTestId("inspector-tab");
    for (const tab of tabs) {
      const id = tab.dataset.tabId as InspectorTabId;
      expect(tab.textContent?.trim()).toBe(INSPECTOR_STRINGS.tabLabels[id]);
    }
  });

  it("marks the active tab with aria-selected=true and the active class", () => {
    setInspectorTab(INSPECTOR_TAB_CONTEXT);
    const { getAllByTestId } = render(Inspector, { props: { session: fakeSession() } });
    const tabs = getAllByTestId("inspector-tab");
    for (const tab of tabs) {
      const isActive = tab.dataset.tabId === INSPECTOR_TAB_CONTEXT;
      expect(tab.getAttribute("aria-selected")).toBe(String(isActive));
    }
  });
});

describe("Inspector shell — default-tab landing", () => {
  it("renders the Agent subsection when the store carries the default tab id", () => {
    const { getByTestId, queryByTestId } = render(Inspector, {
      props: { session: fakeSession() },
    });
    expect(inspectorStore.activeTabId).toBe(DEFAULT_INSPECTOR_TAB);
    expect(getByTestId("inspector-agent")).toBeInTheDocument();
    expect(queryByTestId("inspector-context")).toBeNull();
    expect(queryByTestId("inspector-instructions")).toBeNull();
    expect(queryByTestId("inspector-routing")).toBeNull();
    expect(queryByTestId("inspector-usage")).toBeNull();
  });
});

describe("Inspector shell — tab switching", () => {
  it("clicking a tab calls the supplied setInspectorTab with the tab id", async () => {
    let receivedId: InspectorTabId | null = null;
    const captureSetTab = (id: InspectorTabId): void => {
      receivedId = id;
    };
    const { getAllByTestId } = render(Inspector, {
      props: { session: fakeSession(), setInspectorTab: captureSetTab },
    });
    const contextTab = getAllByTestId("inspector-tab").find(
      (el) => el.dataset.tabId === INSPECTOR_TAB_CONTEXT,
    );
    expect(contextTab).toBeDefined();
    await fireEvent.click(contextTab!);
    expect(receivedId).toBe(INSPECTOR_TAB_CONTEXT);
  });

  it("re-renders the matching subsection when the store flips tab id", async () => {
    const { findByTestId, queryByTestId } = render(Inspector, {
      props: { session: fakeSession() },
    });
    expect(await findByTestId("inspector-agent")).toBeInTheDocument();

    setInspectorTab(INSPECTOR_TAB_INSTRUCTIONS);
    expect(await findByTestId("inspector-instructions")).toBeInTheDocument();
    expect(queryByTestId("inspector-agent")).toBeNull();
  });

  it("clicking through the production store rotates the rendered subsection", async () => {
    const { findByTestId, getAllByTestId } = render(Inspector, {
      props: { session: fakeSession() },
    });
    const tabs = getAllByTestId("inspector-tab");
    const contextTab = tabs.find((el) => el.dataset.tabId === INSPECTOR_TAB_CONTEXT)!;
    await fireEvent.click(contextTab);
    expect(await findByTestId("inspector-context")).toBeInTheDocument();

    const instructionsTab = tabs.find((el) => el.dataset.tabId === INSPECTOR_TAB_INSTRUCTIONS)!;
    await fireEvent.click(instructionsTab);
    expect(await findByTestId("inspector-instructions")).toBeInTheDocument();
  });
});

describe("Inspector shell — empty session", () => {
  it("renders the empty-state copy when session is null", () => {
    const { getByTestId, queryByTestId } = render(Inspector, { props: { session: null } });
    expect(getByTestId("inspector-empty")).toHaveTextContent(INSPECTOR_STRINGS.emptySession);
    // The subsections themselves do not render until a session is in scope.
    expect(queryByTestId("inspector-agent")).toBeNull();
    expect(queryByTestId("inspector-context")).toBeNull();
    expect(queryByTestId("inspector-instructions")).toBeNull();
  });

  it("renders the empty-state copy when session is omitted entirely", () => {
    const { getByTestId } = render(Inspector);
    expect(getByTestId("inspector-empty")).toBeInTheDocument();
  });

  it("still renders the tab strip so the user can pick a tab before a session loads", () => {
    const { getAllByTestId } = render(Inspector, { props: { session: null } });
    expect(getAllByTestId("inspector-tab")).toHaveLength(KNOWN_INSPECTOR_TABS.length);
  });

  it("agrees with the documented Agent / Context / Instructions / Routing / Usage tab ids", () => {
    // Keeps the shell honest against ``KNOWN_INSPECTOR_TABS`` — any
    // re-ordering or rename without touching this assertion is loud.
    // Item 2.6 appended Routing + Usage; the order is the on-screen
    // order of the tab strip and the spec §10 inspector enumeration.
    expect(KNOWN_INSPECTOR_TABS).toEqual([
      INSPECTOR_TAB_AGENT,
      INSPECTOR_TAB_CONTEXT,
      INSPECTOR_TAB_INSTRUCTIONS,
      INSPECTOR_TAB_ROUTING,
      INSPECTOR_TAB_USAGE,
    ]);
  });
});
