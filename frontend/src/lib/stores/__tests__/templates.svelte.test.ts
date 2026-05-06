/**
 * Unit tests for the templates store — covers refresh (sort order,
 * error handling), instantiate (happy path + 422 inline error), and
 * removeTemplate (delete + refresh cycle).
 *
 * All network calls are intercepted via ``vi.spyOn(globalThis, "fetch")``.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  _resetForTests,
  instantiate,
  refreshTemplates,
  removeTemplate,
  templatesStore,
} from "../templates.svelte";
import type { TemplateOut } from "../../api/templates";
import type { SessionOut } from "../../api/sessions";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const makeTemplate = (overrides: Partial<TemplateOut> = {}): TemplateOut => ({
  id: 1,
  name: "Default",
  description: null,
  model: "sonnet",
  advisor_model: null,
  advisor_max_uses: 0,
  effort_level: "normal",
  permission_profile: "default",
  system_prompt_baseline: null,
  working_dir_default: "/home/user/project",
  tag_names: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ...overrides,
});

const makeSession = (overrides: Partial<SessionOut> = {}): SessionOut => ({
  id: "ses_abc",
  kind: "chat",
  title: "Default",
  description: null,
  session_instructions: null,
  working_dir: "/home/user/project",
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

function jsonResp(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function noContentResp(): Response {
  return new Response(null, { status: 204 });
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  _resetForTests();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// refreshTemplates
// ---------------------------------------------------------------------------

describe("refreshTemplates", () => {
  it("populates templatesStore.templates with the API response", async () => {
    const tmpl = makeTemplate();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResp([tmpl]));

    await refreshTemplates();

    expect(templatesStore.templates).toHaveLength(1);
    expect(templatesStore.templates[0]?.name).toBe("Default");
    expect(templatesStore.loading).toBe(false);
    expect(templatesStore.error).toBeNull();
  });

  it("sorts templates newest-first by created_at", async () => {
    const old = makeTemplate({ id: 1, name: "Old", created_at: "2026-01-01T00:00:00Z" });
    const newer = makeTemplate({ id: 2, name: "New", created_at: "2026-06-01T00:00:00Z" });
    // API returns alphabetically (old first).
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResp([old, newer]));

    await refreshTemplates();

    expect(templatesStore.templates[0]?.name).toBe("New");
    expect(templatesStore.templates[1]?.name).toBe("Old");
  });

  it("sets error on fetch failure and clears loading", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("net fail"));

    await refreshTemplates();

    expect(templatesStore.error).toBeInstanceOf(Error);
    expect(templatesStore.loading).toBe(false);
  });

  it("handles an empty list", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResp([]));

    await refreshTemplates();

    expect(templatesStore.templates).toHaveLength(0);
    expect(templatesStore.error).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// instantiate
// ---------------------------------------------------------------------------

describe("instantiate — happy path", () => {
  it("calls POST /api/sessions with template fields and returns the new session id", async () => {
    const tmpl = makeTemplate({ id: 7, name: "My Template", model: "opus" });
    // Prime the store cache.
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResp([tmpl]));
    await refreshTemplates();

    const session = makeSession({ id: "ses_new", model: "opus" });
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResp(session, 201));

    const id = await instantiate(7);

    expect(id).toBe("ses_new");
    // Verify the POST body contains the right model.
    const [, init] = fetchSpy.mock.calls[0]!;
    const body = JSON.parse((init as RequestInit).body as string) as Record<string, unknown>;
    expect(body["model"]).toBe("opus");
    expect(body["kind"]).toBe("chat");
  });
});

describe("instantiate — error surfaces inline", () => {
  it("throws when the template id is not in the cache", async () => {
    await expect(instantiate(999)).rejects.toThrow("Template 999 not found in cache");
  });

  it("throws ApiError when the backend returns a non-2xx (e.g. 422)", async () => {
    const tmpl = makeTemplate({ id: 3, working_dir_default: null });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResp([tmpl]));
    await refreshTemplates();

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResp({ detail: "no working_dir" }, 422),
    );

    await expect(instantiate(3)).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// removeTemplate
// ---------------------------------------------------------------------------

describe("removeTemplate", () => {
  it("calls DELETE then refreshes the list", async () => {
    const tmpl = makeTemplate({ id: 5 });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResp([tmpl])) // initial refresh
      .mockResolvedValueOnce(noContentResp()) // DELETE 204
      .mockResolvedValueOnce(jsonResp([])); // refresh after delete

    await refreshTemplates();
    expect(templatesStore.templates).toHaveLength(1);

    await removeTemplate(5);

    expect(templatesStore.templates).toHaveLength(0);
    // Verify DELETE was the second call.
    const [deleteUrl] = fetchMock.mock.calls[1]!;
    expect(String(deleteUrl)).toContain("/api/templates/5");
  });
});
