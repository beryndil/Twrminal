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
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Inspector from "../Inspector.svelte";
import {
  DEFAULT_INSPECTOR_TAB,
  INSPECTOR_STRINGS,
  INSPECTOR_TAB_AGENT,
  INSPECTOR_TAB_ANALYTICS,
  INSPECTOR_TAB_CHANGES,
  INSPECTOR_TAB_CONTEXT,
  INSPECTOR_TAB_FILES,
  INSPECTOR_TAB_INSTRUCTIONS,
  INSPECTOR_TAB_METRICS,
  INSPECTOR_TAB_ROUTING,
  INSPECTOR_TAB_USAGE,
  KNOWN_INSPECTOR_TABS,
  type InspectorTabId,
} from "../../../config";
import type { MessageOut, MessagePage } from "../../../api/messages";
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
  window.localStorage.clear();
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
      props: {
        session: fakeSession(),
        // Provide pending seams so Routing/Usage never resolve — keeps
        // the test from touching the real network.
        fetchMessages: () => new Promise(() => {}),
        fetchHistory: () => new Promise(() => {}),
        fetchByModel: () => new Promise(() => {}),
        fetchOverrideRates: () => new Promise(() => {}),
      },
    });
    expect(inspectorStore.activeTabId).toBe(DEFAULT_INSPECTOR_TAB);
    // Active tab wrapper is NOT hidden.
    const agentEl = getByTestId("inspector-agent");
    expect(agentEl).toBeInTheDocument();
    expect(agentEl.parentElement?.hasAttribute("hidden")).toBe(false);
    // All other subsections are mounted but wrapped in hidden divs so
    // they don't announce stale content to screen-readers.
    const ctxEl = queryByTestId("inspector-context");
    expect(ctxEl).not.toBeNull();
    expect(ctxEl!.parentElement?.hasAttribute("hidden")).toBe(true);
    const instrEl = queryByTestId("inspector-instructions");
    expect(instrEl).not.toBeNull();
    expect(instrEl!.parentElement?.hasAttribute("hidden")).toBe(true);
    const filesEl = queryByTestId("inspector-files");
    expect(filesEl).not.toBeNull();
    expect(filesEl!.parentElement?.hasAttribute("hidden")).toBe(true);
    const routingEl = queryByTestId("inspector-routing");
    expect(routingEl).not.toBeNull();
    expect(routingEl!.parentElement?.hasAttribute("hidden")).toBe(true);
    const usageEl = queryByTestId("inspector-usage");
    expect(usageEl).not.toBeNull();
    expect(usageEl!.parentElement?.hasAttribute("hidden")).toBe(true);
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

  it("shows the matching subsection when the store flips tab id; prior tab is hidden not removed", async () => {
    const { findByTestId, getByTestId } = render(Inspector, {
      props: {
        session: fakeSession(),
        fetchMessages: () => new Promise(() => {}),
        fetchHistory: () => new Promise(() => {}),
        fetchByModel: () => new Promise(() => {}),
        fetchOverrideRates: () => new Promise(() => {}),
      },
    });
    expect(await findByTestId("inspector-agent")).toBeInTheDocument();

    setInspectorTab(INSPECTOR_TAB_INSTRUCTIONS);
    const instrEl = await findByTestId("inspector-instructions");
    expect(instrEl.parentElement?.hasAttribute("hidden")).toBe(false);
    // Agent is still in the DOM, just hidden.
    const agentEl = getByTestId("inspector-agent");
    expect(agentEl.parentElement?.hasAttribute("hidden")).toBe(true);

    // Files tab works the same way.
    setInspectorTab(INSPECTOR_TAB_FILES);
    const filesEl = await findByTestId("inspector-files");
    expect(filesEl.parentElement?.hasAttribute("hidden")).toBe(false);
    expect(instrEl.parentElement?.hasAttribute("hidden")).toBe(true);
  });

  it("clicking through the production store rotates the rendered subsection", async () => {
    const { findByTestId, getAllByTestId } = render(Inspector, {
      props: {
        session: fakeSession(),
        fetchMessages: () => new Promise(() => {}),
        fetchHistory: () => new Promise(() => {}),
        fetchByModel: () => new Promise(() => {}),
        fetchOverrideRates: () => new Promise(() => {}),
      },
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

describe("Inspector shell — tab state persistence (gap-cycle-09-001)", () => {
  /**
   * Helper: build a routed assistant MessageOut that triggers the
   * timeline row + "Why this model?" toggle in InspectorRouting.
   */
  function routedMsg(overrides: Partial<MessageOut> = {}): MessageOut {
    return {
      id: "msg_r1",
      session_id: "ses_a",
      role: "assistant",
      content: "",
      created_at: "2026-01-01T00:00:00Z",
      executor_model: "sonnet",
      advisor_model: "opus",
      effort_level: "auto",
      routing_source: "tag_rule",
      routing_reason: "test rule fired",
      matched_rule_id: 1,
      executor_input_tokens: 10,
      executor_output_tokens: 5,
      advisor_input_tokens: 3,
      advisor_output_tokens: 2,
      advisor_calls_count: 1,
      cache_read_tokens: 0,
      input_tokens: null,
      output_tokens: null,
      seq: 1,
      pinned: false,
      hidden_from_context: false,
      evaluated_rules: [],
      stopped: false,
      ...overrides,
    };
  }

  it("inactive tab wrappers carry the hidden attribute; active wrapper does not", () => {
    // Default active tab is Agent.
    const { getByTestId, queryByTestId } = render(Inspector, {
      props: {
        session: fakeSession(),
        fetchMessages: () => new Promise(() => {}),
        fetchHistory: () => new Promise(() => {}),
        fetchByModel: () => new Promise(() => {}),
        fetchOverrideRates: () => new Promise(() => {}),
      },
    });
    expect(getByTestId("inspector-agent").parentElement?.hasAttribute("hidden")).toBe(false);
    expect(queryByTestId("inspector-context")!.parentElement?.hasAttribute("hidden")).toBe(true);
    expect(queryByTestId("inspector-instructions")!.parentElement?.hasAttribute("hidden")).toBe(
      true,
    );
    expect(queryByTestId("inspector-files")!.parentElement?.hasAttribute("hidden")).toBe(true);
    expect(queryByTestId("inspector-routing")!.parentElement?.hasAttribute("hidden")).toBe(true);
    expect(queryByTestId("inspector-usage")!.parentElement?.hasAttribute("hidden")).toBe(true);
  });

  it("DOM node for Routing tab persists (same reference) across a tab switch and back", async () => {
    setInspectorTab(INSPECTOR_TAB_ROUTING);
    const { getByTestId } = render(Inspector, {
      props: {
        session: fakeSession(),
        fetchMessages: () => new Promise(() => {}),
        fetchHistory: () => new Promise(() => {}),
        fetchByModel: () => new Promise(() => {}),
        fetchOverrideRates: () => new Promise(() => {}),
      },
    });
    const routingEl = getByTestId("inspector-routing");

    setInspectorTab(INSPECTOR_TAB_USAGE);
    // Routing is still in the document tree, just wrapped in a hidden div.
    await waitFor(() => {
      expect(document.body.contains(routingEl)).toBe(true);
    });

    setInspectorTab(INSPECTOR_TAB_ROUTING);
    // Same node identity after coming back — component was never unmounted.
    await waitFor(() => {
      expect(getByTestId("inspector-routing")).toBe(routingEl);
    });
  });

  it("expandedReasons in the Routing tab survive a round-trip to another tab and back", async () => {
    const page: MessagePage = { items: [routedMsg()], has_more: false };
    const fetchMessages = vi.fn(async () => page);

    setInspectorTab(INSPECTOR_TAB_ROUTING);
    const { findByTestId, getByTestId } = render(Inspector, {
      props: {
        session: fakeSession(),
        fetchMessages,
        fetchHistory: () => new Promise(() => {}),
        fetchByModel: () => new Promise(() => {}),
        fetchOverrideRates: () => new Promise(() => {}),
      },
    });

    // Wait for Routing to load and the why-toggle to appear.
    const toggle = await findByTestId("inspector-routing-why-toggle");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    await fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");

    // Switch away to Context tab.
    setInspectorTab(INSPECTOR_TAB_CONTEXT);
    await waitFor(() => {
      expect(getByTestId("inspector-context").parentElement?.hasAttribute("hidden")).toBe(false);
    });

    // Switch back to Routing.
    setInspectorTab(INSPECTOR_TAB_ROUTING);
    await waitFor(() => {
      expect(getByTestId("inspector-routing").parentElement?.hasAttribute("hidden")).toBe(false);
    });

    // expandedReasons survived: the same toggle is still marked expanded.
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });

  it("Usage fetches fire once on mount and are NOT re-triggered by tab switches", async () => {
    // Spy functions that resolve immediately and count calls.
    const fetchHistory = vi.fn(async () => []);
    const fetchByModel = vi.fn(async () => []);
    const fetchOverrideRates = vi.fn(async () => []);

    render(Inspector, {
      props: {
        session: fakeSession(),
        fetchMessages: () => new Promise(() => {}),
        fetchHistory,
        fetchByModel,
        fetchOverrideRates,
      },
    });

    // Wait for InspectorUsage's $effect to fire and all three fetches to
    // resolve (the empty-state node appears once loadState hits "ready").
    await waitFor(() => {
      expect(fetchHistory).toHaveBeenCalledTimes(1);
      expect(fetchByModel).toHaveBeenCalledTimes(1);
      expect(fetchOverrideRates).toHaveBeenCalledTimes(1);
    });

    // Switching tabs does not unmount InspectorUsage, so no re-fetch.
    setInspectorTab(INSPECTOR_TAB_ROUTING);
    setInspectorTab(INSPECTOR_TAB_AGENT);
    setInspectorTab(INSPECTOR_TAB_USAGE);

    // A brief settle — if counts rise above 1 this will catch it.
    await waitFor(() => {
      expect(fetchHistory).toHaveBeenCalledTimes(1);
      expect(fetchByModel).toHaveBeenCalledTimes(1);
      expect(fetchOverrideRates).toHaveBeenCalledTimes(1);
    });
  });
});

describe("Inspector shell — ARIA tab panel labelling (gap-cycle-12-003)", () => {
  it("tabpanel announces the active tab label for the default tab (Agent)", () => {
    const { getByRole } = render(Inspector, { props: { session: fakeSession() } });
    expect(getByRole("tabpanel")).toHaveAccessibleName(
      INSPECTOR_STRINGS.tabLabels[DEFAULT_INSPECTOR_TAB],
    );
  });

  it("each tab button carries id=inspector-tab-<tabId>", () => {
    const { getAllByTestId } = render(Inspector, { props: { session: fakeSession() } });
    for (const tab of getAllByTestId("inspector-tab")) {
      const tabId = tab.dataset.tabId as InspectorTabId;
      expect(tab.id).toBe(`inspector-tab-${tabId}`);
    }
  });

  it("each tab button aria-controls points to inspector-panel-<tabId>", () => {
    const { getAllByTestId } = render(Inspector, { props: { session: fakeSession() } });
    for (const tab of getAllByTestId("inspector-tab")) {
      const tabId = tab.dataset.tabId as InspectorTabId;
      expect(tab.getAttribute("aria-controls")).toBe(`inspector-panel-${tabId}`);
    }
  });

  it("tabpanel accessible name updates when the active tab changes", async () => {
    const { getByRole } = render(Inspector, {
      props: {
        session: fakeSession(),
        fetchMessages: () => new Promise(() => {}),
        fetchHistory: () => new Promise(() => {}),
        fetchByModel: () => new Promise(() => {}),
        fetchOverrideRates: () => new Promise(() => {}),
      },
    });
    expect(getByRole("tabpanel")).toHaveAccessibleName(
      INSPECTOR_STRINGS.tabLabels[DEFAULT_INSPECTOR_TAB],
    );
    setInspectorTab(INSPECTOR_TAB_CONTEXT);
    await waitFor(() => {
      expect(getByRole("tabpanel")).toHaveAccessibleName(
        INSPECTOR_STRINGS.tabLabels[INSPECTOR_TAB_CONTEXT],
      );
    });
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

  it("agrees with the documented Agent / Context / Instructions / Files / Changes / Metrics / Routing / Usage / Analytics tab ids", () => {
    // Keeps the shell honest against ``KNOWN_INSPECTOR_TABS`` — any
    // re-ordering or rename without touching this assertion is loud.
    // Item 2.6 appended Routing + Usage; gap-cycle-09-003 inserted
    // Files between Instructions and Routing; gap-cycle-09-004
    // inserted Changes between Files and Routing; gap-cycle-09-005
    // inserted Metrics between Changes and Routing. Analytics Phase 5
    // appended Analytics at the end.
    expect(KNOWN_INSPECTOR_TABS).toEqual([
      INSPECTOR_TAB_AGENT,
      INSPECTOR_TAB_CONTEXT,
      INSPECTOR_TAB_INSTRUCTIONS,
      INSPECTOR_TAB_FILES,
      INSPECTOR_TAB_CHANGES,
      INSPECTOR_TAB_METRICS,
      INSPECTOR_TAB_ROUTING,
      INSPECTOR_TAB_USAGE,
      INSPECTOR_TAB_ANALYTICS,
    ]);
  });
});
