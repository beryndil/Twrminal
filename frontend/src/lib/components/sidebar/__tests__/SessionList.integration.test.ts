/**
 * Integration test for ``SessionList`` — the load-bearing assertion
 * for master item #537's done-when ("Finder-click filter + OR
 * semantics across tags").
 *
 * What this test exercises:
 *
 * 1. SessionList mounts, fetches /api/tags + /api/sessions + per-row
 *    /api/sessions/{id}/tags via the real stores against a mocked
 *    ``fetch``.
 * 2. Clicking a tag chip in a session row toggles that tag in the
 *    filter set AND triggers a re-fetch with ``?tag_ids=N``.
 * 3. Adding a SECOND tag to the filter — the OR-semantics assertion —
 *    keeps the first tag's session in the result. Specifically: with
 *    a disjoint setup (session_a→tag1, session_b→tag2) and filter
 *    ``{tag1, tag2}``, the backend would return BOTH (OR); under AND
 *    semantics it would return NEITHER. The frontend's job is to
 *    surface BOTH session ids in the wire query so the backend's OR
 *    plan applies.
 *
 * The assertion is on the wire shape (the URL the frontend asks for)
 * because the OR plan itself lives on the backend (the DB layer's
 * unit tests in ``test_sessions_db.py`` already pin the SQL). This
 * test pins that the FRONTEND emits the OR-shaped query rather than
 * collapsing the set under some implicit AND assumption.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SessionList from "../SessionList.svelte";
import { _resetForTests as resetSessionsStore } from "../../../stores/sessions.svelte";
import { _resetForTests as resetTagsStore } from "../../../stores/tags.svelte";
import type { SessionOut } from "../../../api/sessions";
import type { TagOut } from "../../../api/tags";

const session = (id: string, title: string): SessionOut => ({
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
});

const tag = (id: number, name: string): TagOut => ({
  id,
  name,
  color: null,
  default_model: null,
  working_dir: null,
  group: name.includes("/") ? name.split("/")[0] : null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
});

const TAG_1 = tag(1, "bearings/architect");
const TAG_2 = tag(2, "bearings/exec");
const SESSION_A = session("ses_a", "A — architect-only");
const SESSION_B = session("ses_b", "B — exec-only");

beforeEach(() => {
  resetSessionsStore();
  resetTagsStore();
});

afterEach(() => {
  vi.restoreAllMocks();
});

interface FakeServer {
  /** All URLs the frontend has fetched, in order. */
  urls: string[];
}

/**
 * Wire a stateful fake fetch:
 *
 * - ``/api/tags`` always returns [tag1, tag2];
 * - ``/api/sessions`` returns the union/OR of sessions matching the
 *   ``tag_ids`` query (or both sessions when the filter is absent);
 * - ``/api/sessions/{id}/tags`` returns the per-session tag list.
 */
function installFakeServer(): FakeServer {
  const recorder: FakeServer = { urls: [] };
  vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    recorder.urls.push(url);
    if (url.startsWith("/api/tags")) {
      return Promise.resolve(jsonResponse([TAG_1, TAG_2]));
    }
    if (url.startsWith("/api/sessions/ses_a/tags")) {
      return Promise.resolve(jsonResponse([TAG_1]));
    }
    if (url.startsWith("/api/sessions/ses_b/tags")) {
      return Promise.resolve(jsonResponse([TAG_2]));
    }
    if (url.startsWith("/api/sessions")) {
      const tagIds = extractTagIds(url);
      let rows: SessionOut[];
      if (tagIds.length === 0) {
        rows = [SESSION_A, SESSION_B];
      } else {
        // OR semantics: a session matches when ANY listed tag is on it.
        rows = [];
        if (tagIds.includes(1)) rows.push(SESSION_A);
        if (tagIds.includes(2)) rows.push(SESSION_B);
      }
      return Promise.resolve(jsonResponse(rows));
    }
    return Promise.resolve(new Response("not mocked: " + url, { status: 404 }));
  });
  return recorder;
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function extractTagIds(url: string): number[] {
  const queryStart = url.indexOf("?");
  if (queryStart < 0) return [];
  const params = new URLSearchParams(url.slice(queryStart + 1));
  return params.getAll("tag_ids").map((v) => Number.parseInt(v, 10));
}

describe("SessionList integration — finder-click + OR semantics", () => {
  it("renders both sessions on first load with no filter applied", async () => {
    installFakeServer();
    const { findByText } = render(SessionList);
    expect(await findByText(SESSION_A.title)).toBeInTheDocument();
    expect(await findByText(SESSION_B.title)).toBeInTheDocument();
  });

  it("clicking a session-row tag chip narrows the list AND re-fetches with tag_ids", async () => {
    const server = installFakeServer();
    const { container, queryByText, findByText } = render(SessionList);

    // Wait for the SessionRow's tag chip to render — the title appears
    // before the per-session tag-fetch completes, so we must explicitly
    // wait for the chip itself.
    const chipOnA = await waitFor(() => {
      const chip = container.querySelector<HTMLElement>(
        '[data-testid="session-row"][data-session-id="ses_a"] [data-testid="session-tag-chip"]',
      );
      if (chip === null) {
        throw new Error("session-row tag chip not yet rendered");
      }
      return chip;
    });
    expect(chipOnA.dataset.tagId).toBe("1");

    await fireEvent.click(chipOnA);

    // The store re-fetches with ?tag_ids=1; session B should disappear.
    await waitFor(() => {
      expect(queryByText(SESSION_B.title)).toBeNull();
    });
    expect(await findByText(SESSION_A.title)).toBeInTheDocument();

    // Confirm the wire call carried the filter.
    const lastSessionsCall = server.urls
      .filter((u) => u.startsWith("/api/sessions?") || u === "/api/sessions")
      .at(-1)!;
    expect(lastSessionsCall).toContain("tag_ids=1");
  });

  it("OR semantics — adding a second tag widens the result rather than narrowing", async () => {
    const server = installFakeServer();
    const { container, findAllByTestId, findByText, queryByText } = render(SessionList);

    // Wait for both rows' chips to render (per-session tag fetches).
    const chipOnA = await waitFor(() => {
      const chip = container.querySelector<HTMLElement>(
        '[data-testid="session-row"][data-session-id="ses_a"] [data-testid="session-tag-chip"]',
      );
      if (chip === null) {
        throw new Error("session-row chip on A not yet rendered");
      }
      return chip;
    });

    // Click the chip on row A → filter = {1}. B disappears.
    await fireEvent.click(chipOnA);
    await waitFor(() => {
      expect(queryByText(SESSION_B.title)).toBeNull();
    });

    // Click the OTHER tag in the top-of-sidebar filter panel.
    const filterChips = await findAllByTestId("tag-filter-chip");
    const tag2Chip = filterChips.find((el) => el.dataset.tagId === "2");
    expect(tag2Chip).toBeDefined();
    await fireEvent.click(tag2Chip!);

    // OR-semantics check: BOTH sessions visible (filter {1,2} returns
    // session_a OR session_b). AND semantics would yield neither.
    await findByText(SESSION_A.title);
    await findByText(SESSION_B.title);

    // Confirm the wire shape carries both ids.
    await waitFor(() => {
      const lastSessionsCall = server.urls
        .filter((u) => u.startsWith("/api/sessions?") || u === "/api/sessions")
        .at(-1)!;
      expect(lastSessionsCall).toContain("tag_ids=1");
      expect(lastSessionsCall).toContain("tag_ids=2");
    });
  });

  it("clear-filter button empties the filter set and refetches without tag_ids", async () => {
    const server = installFakeServer();
    const { findAllByTestId, findByTestId, findByText } = render(SessionList);

    await findByText(SESSION_A.title);

    // Apply a filter so the clear button appears.
    const filterChips = await findAllByTestId("tag-filter-chip");
    const firstFilterChip = filterChips.find((el) => el.dataset.tagId === "1");
    expect(firstFilterChip).toBeDefined();
    await fireEvent.click(firstFilterChip!);

    const clearButton = await findByTestId("tag-filter-clear");
    await fireEvent.click(clearButton);

    await waitFor(() => {
      const lastSessionsCall = server.urls
        .filter((u) => u.startsWith("/api/sessions?") || u === "/api/sessions")
        .at(-1)!;
      expect(lastSessionsCall).not.toContain("tag_ids");
    });
  });
});
