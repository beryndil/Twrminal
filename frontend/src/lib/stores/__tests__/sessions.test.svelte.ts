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
  pinned: false,
  class_: "general" as const,
  sort_order: 0,
  group: "bearings",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  open_session_count: 0,
  session_count: 0,
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

const emptyFilter = (): {
  project: ReadonlySet<number>;
  severity: ReadonlySet<number>;
  other: ReadonlySet<number>;
} => ({
  project: new Set<number>(),
  severity: new Set<number>(),
  other: new Set<number>(),
});

describe("sessionsStore.refreshSessions", () => {
  it("omits every tag_ids_<class> param from the query when no section has a selection", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([fixtureSession])) // sessions list
      .mockResolvedValueOnce(jsonResponse([])); // per-session tags

    await refreshSessions(emptyFilter());

    const sessionsCallUrl = String(fetchMock.mock.calls[0][0]);
    expect(sessionsCallUrl).toBe("/api/sessions");
    expect(sessionsCallUrl).not.toContain("tag_ids");
  });

  it("emits ?tag_ids_project=1&tag_ids_project=2 for the project section", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([fixtureSession]))
      .mockResolvedValueOnce(jsonResponse([fixtureTag]));

    await refreshSessions({ ...emptyFilter(), project: new Set([1, 2]) });

    const sessionsCallUrl = String(fetchMock.mock.calls[0][0]);
    expect(sessionsCallUrl).toContain("tag_ids_project=1");
    expect(sessionsCallUrl).toContain("tag_ids_project=2");
    expect(sessionsCallUrl).not.toContain("tag_ids_severity");
    expect(sessionsCallUrl).not.toContain("tag_ids_other");
  });

  it("emits all three section params when each has a selection", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([fixtureSession]))
      .mockResolvedValueOnce(jsonResponse([fixtureTag]));

    await refreshSessions({
      project: new Set([1]),
      severity: new Set([2]),
      other: new Set([3]),
    });

    const sessionsCallUrl = String(fetchMock.mock.calls[0][0]);
    expect(sessionsCallUrl).toContain("tag_ids_project=1");
    expect(sessionsCallUrl).toContain("tag_ids_severity=2");
    expect(sessionsCallUrl).toContain("tag_ids_other=3");
  });

  it("populates per-session tag map from /api/sessions/{id}/tags", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([fixtureSession]))
      .mockResolvedValueOnce(jsonResponse([fixtureTag]));

    await refreshSessions(emptyFilter());

    expect(sessionsStore.sessions).toEqual([fixtureSession]);
    expect(sessionsStore.tagsBySessionId[fixtureSession.id]).toEqual([fixtureTag]);
  });

  it("captures error when the sessions list fetch fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("server down", { status: 500 }),
    );
    await refreshSessions(emptyFilter());
    expect(sessionsStore.error).toBeInstanceOf(Error);
    expect(sessionsStore.loading).toBe(false);
  });

  it("falls back to empty tag list when per-session tag fetch fails (does not blank the row)", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([fixtureSession]))
      .mockResolvedValueOnce(new Response("nope", { status: 500 }));

    await refreshSessions(emptyFilter());

    expect(sessionsStore.sessions).toEqual([fixtureSession]);
    expect(sessionsStore.tagsBySessionId[fixtureSession.id]).toEqual([]);
    expect(sessionsStore.error).toBeNull();
  });
});
