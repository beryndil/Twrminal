/**
 * Tests for the pending-ops API client (gap-cycle-03-010).
 *
 * Acceptance criteria covered:
 *
 * - ``resolvePendingOp`` fires POST /api/pending/{name}/resolve?directory=...
 * - ``dismissPendingOp`` fires DELETE /api/pending/{name}?directory=...
 * - Both return void on 204.
 * - Both throw ApiError on non-2xx (404, 500).
 * - Names and directories are URL-encoded in the request URL.
 *
 * Also covers ``fetchPendingOps`` soft-empty wraps (console-replay-012-FE):
 * - 404 → empty array (file does not exist).
 * - 403 → empty array (allow-roots empty; documented empty-state).
 * - Neither path logs to ``console.error``.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../client";
import { dismissPendingOp, fetchPendingOps, resolvePendingOp } from "../pendingOps";

afterEach(() => {
  vi.restoreAllMocks();
});

// ---- resolvePendingOp -------------------------------------------------------

describe("resolvePendingOp", () => {
  it("POSTs to the correct resolve endpoint and returns on 204", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await resolvePendingOp("my-op", "/home/user/project");

    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toBe("/api/pending/my-op/resolve?directory=%2Fhome%2Fuser%2Fproject");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
  });

  it("URL-encodes op name with special characters", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await resolvePendingOp("op with spaces/slashes", "/dir");

    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toContain("op%20with%20spaces%2Fslashes");
  });

  it("throws ApiError with status 404 on unknown name", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "no pending op named 'missing'" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );

    await expect(resolvePendingOp("missing", "/dir")).rejects.toBeInstanceOf(ApiError);
  });

  it("throws ApiError on 500", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "could not update pending.toml" }), {
        status: 500,
        headers: { "content-type": "application/json" },
      }),
    );

    let caught: ApiError | null = null;
    try {
      await resolvePendingOp("op", "/dir");
    } catch (err) {
      if (err instanceof ApiError) caught = err;
    }
    expect(caught).not.toBeNull();
    expect(caught?.status).toBe(500);
  });
});

// ---- dismissPendingOp -------------------------------------------------------

describe("dismissPendingOp", () => {
  it("DELETEs to the correct dismiss endpoint and returns on 204", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await dismissPendingOp("review", "/home/user/project");

    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toBe("/api/pending/review?directory=%2Fhome%2Fuser%2Fproject");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("DELETE");
  });

  it("URL-encodes directory path", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await dismissPendingOp("op", "/path with spaces");

    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toContain("directory=%2Fpath%20with%20spaces");
  });

  it("throws ApiError with status 404 on unknown name", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "no pending op named 'missing'" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );

    await expect(dismissPendingOp("missing", "/dir")).rejects.toBeInstanceOf(ApiError);
  });

  it("throws ApiError on 500 with non-JSON body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("Internal Server Error", { status: 500 }),
    );

    let caught: ApiError | null = null;
    try {
      await dismissPendingOp("op", "/dir");
    } catch (err) {
      if (err instanceof ApiError) caught = err;
    }
    expect(caught).not.toBeNull();
    expect(caught?.status).toBe(500);
  });
});

// ---- fetchPendingOps (console-replay-012-FE) --------------------------------

const FS_READ_RESPONSE_OK = JSON.stringify({
  path: "/proj/.bearings/pending.toml",
  content: '[ops.deploy]\ndescription = "Deploy"\nstarted_at = "2024-01-01T00:00:00Z"\n',
  size: 80,
  truncated: false,
});

describe("fetchPendingOps", () => {
  it("returns parsed ops on 200", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(FS_READ_RESPONSE_OK, {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const ops = await fetchPendingOps("/proj");
    expect(ops).toHaveLength(1);
    expect(ops[0].name).toBe("deploy");
  });

  it("returns [] on 404 (file does not exist) without console.error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "not found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );
    const consoleSpy = vi.spyOn(console, "error");
    const ops = await fetchPendingOps("/proj");
    expect(ops).toEqual([]);
    expect(consoleSpy).not.toHaveBeenCalled();
  });

  it("returns [] on 403 (allow-roots empty) without console.error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "path not under any allow-root" }), {
        status: 403,
        headers: { "content-type": "application/json" },
      }),
    );
    const consoleSpy = vi.spyOn(console, "error");
    const ops = await fetchPendingOps("/proj");
    expect(ops).toEqual([]);
    expect(consoleSpy).not.toHaveBeenCalled();
  });

  it("re-throws ApiError on unexpected statuses (e.g. 500)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "internal error" }), {
        status: 500,
        headers: { "content-type": "application/json" },
      }),
    );
    let caught: unknown = null;
    try {
      await fetchPendingOps("/proj");
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(500);
  });

  it("builds the correct fs/read URL for the working dir", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(FS_READ_RESPONSE_OK, {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    await fetchPendingOps("/home/user/my project");
    const calledUrl = String(fetchSpy.mock.calls[0][0]);
    expect(calledUrl).toContain("/api/fs/read");
    expect(calledUrl).toContain(encodeURIComponent("/home/user/my project/.bearings/pending.toml"));
  });
});
