/**
 * Tests for the ``/api/sessions`` typed-client surface — focused on
 * the new ``reopenSession`` helper. The list-sessions wire shape is
 * already exercised through the SessionList integration test; the
 * reopen helper has its own unit coverage so a wire-shape regression
 * surfaces here rather than via a Slice B4 UX failure.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { reopenSession, type SessionOut } from "../sessions";

afterEach(() => {
  vi.restoreAllMocks();
});

const baseRow: SessionOut = {
  id: "ses_a",
  kind: "chat",
  title: "Reopened",
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
  // Closing summary survives reopen per behavior doc — the operator
  // can still see what the agent thought it had finished.
  closing_summary: "Done.",
};

describe("reopenSession", () => {
  it("POSTs to /api/sessions/<id>/reopen and returns the refreshed row", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(baseRow), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const result = await reopenSession("ses_a");
    expect(result.id).toBe("ses_a");
    expect(result.closed_at).toBeNull();
    expect(result.closing_summary).toBe("Done.");
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/sessions/ses_a/reopen");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
  });

  it("URL-encodes the session id so unusual characters round-trip safely", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(baseRow), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    await reopenSession("ses with spaces/and slashes");
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "/api/sessions/ses%20with%20spaces%2Fand%20slashes/reopen",
    );
  });
});
