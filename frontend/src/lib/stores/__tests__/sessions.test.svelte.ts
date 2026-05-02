/**
 * Unit tests for the sessions store — covers the OR-semantics wire
 * shape (multiple ``tag_ids`` query params), the no-filter shortcut,
 * and the per-session tag fan-out.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { _resetForTests, refreshSessions, sessionsStore } from "../sessions.svelte";
import type { SessionOut } from "../../api/sessions";
import type { TagOut } from "../../api/tags";

const fixtureSession: SessionOut = {
  id: "ses_a",
  kind: "chat",
  title: "Hello",
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
};

const fixtureTag: TagOut = {
  id: 1,
  name: "bearings/architect",
  color: null,
  default_model: null,
  working_dir: null,
  group: "bearings",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

beforeEach(() => {
  _resetForTests();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("sessionsStore.refreshSessions", () => {
  it("omits tag_ids from the query when the filter set is empty", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([fixtureSession])) // sessions list
      .mockResolvedValueOnce(jsonResponse([])); // per-session tags

    await refreshSessions(new Set<number>());

    const sessionsCallUrl = String(fetchMock.mock.calls[0][0]);
    expect(sessionsCallUrl).toBe("/api/sessions");
    expect(sessionsCallUrl).not.toContain("tag_ids");
  });

  it("emits ?tag_ids=1&tag_ids=2 for the OR filter shape", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([fixtureSession]))
      .mockResolvedValueOnce(jsonResponse([fixtureTag]));

    await refreshSessions(new Set<number>([1, 2]));

    const sessionsCallUrl = String(fetchMock.mock.calls[0][0]);
    // URLSearchParams may emit either ordering; assert both keys appear.
    expect(sessionsCallUrl).toContain("tag_ids=1");
    expect(sessionsCallUrl).toContain("tag_ids=2");
    expect(sessionsCallUrl).toMatch(/tag_ids=1.*tag_ids=2|tag_ids=2.*tag_ids=1/);
  });

  it("populates per-session tag map from /api/sessions/{id}/tags", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([fixtureSession]))
      .mockResolvedValueOnce(jsonResponse([fixtureTag]));

    await refreshSessions(new Set<number>());

    expect(sessionsStore.sessions).toEqual([fixtureSession]);
    expect(sessionsStore.tagsBySessionId[fixtureSession.id]).toEqual([fixtureTag]);
  });

  it("captures error when the sessions list fetch fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("server down", { status: 500 }),
    );
    await refreshSessions(new Set<number>());
    expect(sessionsStore.error).toBeInstanceOf(Error);
    expect(sessionsStore.loading).toBe(false);
  });

  it("falls back to empty tag list when per-session tag fetch fails (does not blank the row)", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([fixtureSession]))
      .mockResolvedValueOnce(new Response("nope", { status: 500 }));

    await refreshSessions(new Set<number>());

    expect(sessionsStore.sessions).toEqual([fixtureSession]);
    expect(sessionsStore.tagsBySessionId[fixtureSession.id]).toEqual([]);
    expect(sessionsStore.error).toBeNull();
  });
});
