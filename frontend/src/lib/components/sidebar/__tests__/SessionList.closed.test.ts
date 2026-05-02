/**
 * Tests for the closed-sessions surface in ``SessionList``:
 *
 * 1. Closed rows are hidden by default — the open list renders without
 *    them.
 * 2. A "Closed (N)" expander appears at the bottom when any closed
 *    rows exist; the count matches the cohort size.
 * 3. Clicking the expander reveals closed rows AND attaches a Reopen
 *    button to each.
 * 4. Clicking a row's Reopen button calls the injected ``reopenSession``
 *    API client + triggers a refresh.
 *
 * Pinned to the Slice B4 surface in ``~/.claude/plans/unblocking-v1-dogfood.md``.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SessionList from "../SessionList.svelte";
import { _resetForTests as resetSessionsStore } from "../../../stores/sessions.svelte";
import { _resetForTests as resetTagsStore } from "../../../stores/tags.svelte";
import type { SessionOut } from "../../../api/sessions";

const session = (id: string, title: string, overrides: Partial<SessionOut> = {}): SessionOut => ({
  id,
  kind: "chat",
  title,
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
});

const fakeStores = (sessions: readonly SessionOut[]) => ({
  sessionsStore: {
    sessions: [...sessions],
    tagsBySessionId: {} as Record<string, never[]>,
    loading: false,
    error: null as Error | null,
  },
  tagsStore: {
    all: [] as never[],
    selectedIds: new Set<number>(),
    loading: false,
    error: null as Error | null,
  },
});

beforeEach(() => {
  resetSessionsStore();
  resetTagsStore();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SessionList — closed-section surface", () => {
  it("hides closed sessions from the default list and surfaces the expander", () => {
    const open = session("ses_open", "Open");
    const closed = session("ses_closed", "Closed One", {
      closed_at: "2026-01-02T00:00:00Z",
      closing_summary: "Done.",
    });
    const stores = fakeStores([open, closed]);
    const { queryByText, getByTestId } = render(SessionList, {
      props: {
        ...stores,
        refreshSessions: vi.fn().mockResolvedValue(undefined),
        refreshTags: vi.fn().mockResolvedValue(undefined),
        toggleTag: vi.fn(),
        clearTagFilter: vi.fn(),
        reopenSession: vi.fn().mockResolvedValue(undefined),
      },
    });
    // Open row visible, closed row not visible until the expander is clicked.
    expect(queryByText("Open")).not.toBeNull();
    expect(queryByText("Closed One")).toBeNull();
    const toggle = getByTestId("session-list-closed-toggle");
    expect(toggle).toHaveTextContent("Closed (1)");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("clicking the expander reveals closed rows and toggles aria-expanded", async () => {
    const closed = session("ses_closed", "Closed Row", {
      closed_at: "2026-01-02T00:00:00Z",
    });
    const stores = fakeStores([closed]);
    const { getByTestId, queryByText } = render(SessionList, {
      props: {
        ...stores,
        refreshSessions: vi.fn().mockResolvedValue(undefined),
        refreshTags: vi.fn().mockResolvedValue(undefined),
        toggleTag: vi.fn(),
        clearTagFilter: vi.fn(),
        reopenSession: vi.fn().mockResolvedValue(undefined),
      },
    });
    expect(queryByText("Closed Row")).toBeNull();
    const toggle = getByTestId("session-list-closed-toggle");
    await fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(queryByText("Closed Row")).not.toBeNull();
  });

  it("the closed expander does not render when there are no closed sessions", () => {
    const open = session("ses_open", "Just Open");
    const stores = fakeStores([open]);
    const { queryByTestId } = render(SessionList, {
      props: {
        ...stores,
        refreshSessions: vi.fn().mockResolvedValue(undefined),
        refreshTags: vi.fn().mockResolvedValue(undefined),
        toggleTag: vi.fn(),
        clearTagFilter: vi.fn(),
        reopenSession: vi.fn().mockResolvedValue(undefined),
      },
    });
    expect(queryByTestId("session-list-closed-toggle")).toBeNull();
  });

  it("clicking Reopen on a closed row calls reopenSession + refreshSessions", async () => {
    const closed = session("ses_x", "Was Closed", {
      closed_at: "2026-01-02T00:00:00Z",
    });
    const stores = fakeStores([closed]);
    const reopenSession = vi.fn().mockResolvedValue(undefined);
    const refreshSessions = vi.fn().mockResolvedValue(undefined);
    const { getByTestId } = render(SessionList, {
      props: {
        ...stores,
        refreshSessions,
        refreshTags: vi.fn().mockResolvedValue(undefined),
        toggleTag: vi.fn(),
        clearTagFilter: vi.fn(),
        reopenSession,
      },
    });
    await fireEvent.click(getByTestId("session-list-closed-toggle"));
    await fireEvent.click(getByTestId("session-reopen-button"));
    await waitFor(() => {
      expect(reopenSession).toHaveBeenCalledWith("ses_x");
    });
    // The post-reopen refresh fires once the API call resolves.
    await waitFor(() => {
      // refreshSessions runs once on mount via the $effect, then again
      // after a reopen — so the count crosses 1.
      expect(refreshSessions.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
  });
});
