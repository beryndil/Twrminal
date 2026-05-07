/**
 * Tests for the ``/api/sessions`` typed-client surface — focused on
 * the new ``reopenSession`` and ``exportSessionJson`` helpers. The
 * list-sessions wire shape is already exercised through the SessionList
 * integration test; these helpers have their own unit coverage so a
 * wire-shape regression surfaces here rather than via a Slice B4 UX
 * failure.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { exportSessionJson, regenerateFromMessage, reopenSession, type SessionOut } from "../sessions";

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

describe("exportSessionJson", () => {
  const exportSession: SessionOut = {
    ...baseRow,
    id: "ses_export",
    title: "My Export Session",
    closed_at: null,
    closing_summary: null,
  };

  // jsdom does not implement URL.createObjectURL/revokeObjectURL — install
  // no-op stubs so vi.spyOn can intercept them in each test.
  beforeEach(() => {
    if (!URL.createObjectURL) {
      URL.createObjectURL = () => "blob:stub";
    }
    if (!URL.revokeObjectURL) {
      URL.revokeObjectURL = () => {};
    }
  });

  /** Build a stub anchor and wire up the DOM mocks, return the anchor. */
  function stubAnchor(): HTMLAnchorElement {
    const anchor = { href: "", download: "", click: vi.fn() } as unknown as HTMLAnchorElement;
    vi.spyOn(document, "createElement").mockReturnValueOnce(anchor);
    vi.spyOn(document.body, "appendChild").mockReturnValueOnce(anchor);
    vi.spyOn(document.body, "removeChild").mockReturnValueOnce(anchor);
    return anchor;
  }

  it("GETs /api/sessions/<id>/export and triggers URL.createObjectURL", async () => {
    const blob = new Blob(['{"session":{}}'], { type: "application/json" });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(blob, { status: 200, headers: { "content-type": "application/json" } }),
    );
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValueOnce("blob:fake");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementationOnce(() => {});
    const anchor = stubAnchor();

    await exportSessionJson(exportSession);

    // Correct endpoint called
    expect(String((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0])).toBe(
      "/api/sessions/ses_export/export",
    );
    // createObjectURL called with the response blob
    expect(createObjectURL).toHaveBeenCalledOnce();
    // revokeObjectURL called to free memory
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake");
    // anchor download attribute set to slugified title
    expect(anchor.download).toBe("my-export-session.json");
  });

  it("slugifies the title for the download filename", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(new Blob(["{}"], { type: "application/json" }), { status: 200 }),
    );
    vi.spyOn(URL, "createObjectURL").mockReturnValueOnce("blob:x");
    vi.spyOn(URL, "revokeObjectURL").mockImplementationOnce(() => {});
    const anchor = stubAnchor();

    await exportSessionJson({ ...exportSession, title: "Hello World! (v2)" });
    expect(anchor.download).toBe("hello-world-v2.json");
  });

  it("falls back to session.json when slug is empty", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(new Blob(["{}"], { type: "application/json" }), { status: 200 }),
    );
    vi.spyOn(URL, "createObjectURL").mockReturnValueOnce("blob:x");
    vi.spyOn(URL, "revokeObjectURL").mockImplementationOnce(() => {});
    const anchor = stubAnchor();

    await exportSessionJson({ ...exportSession, title: "---!!!" });
    expect(anchor.download).toBe("session.json");
  });

  it("works for closed sessions (no 409 expectation on client)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(new Blob(["{}"], { type: "application/json" }), { status: 200 }),
    );
    vi.spyOn(URL, "createObjectURL").mockReturnValueOnce("blob:x");
    vi.spyOn(URL, "revokeObjectURL").mockImplementationOnce(() => {});
    const anchor = stubAnchor();

    // Closed session — endpoint returns 200
    await exportSessionJson({ ...exportSession, closed_at: "2026-01-01T12:00:00Z" });
    expect(anchor.click).toHaveBeenCalledOnce();
  });
});

describe("regenerateFromMessage", () => {
  it("POSTs to /api/sessions/<sid>/regenerate_from/<mid> and resolves on 202", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ queued: true, session_id: "ses_a" }), {
        status: 202,
        headers: { "content-type": "application/json" },
      }),
    );
    await regenerateFromMessage("ses_a", "msg_1");
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "/api/sessions/ses_a/regenerate_from/msg_1",
    );
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
  });

  it("URL-encodes both session id and message id", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("{}", { status: 202 }),
    );
    await regenerateFromMessage("ses a/b", "msg x/y");
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "/api/sessions/ses%20a%2Fb/regenerate_from/msg%20x%2Fy",
    );
  });

  it("throws ApiError on non-2xx response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "not found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );
    const { ApiError } = await import("../client");
    await expect(regenerateFromMessage("ses_a", "msg_x")).rejects.toBeInstanceOf(ApiError);
  });
});
