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
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../client";
import { dismissPendingOp, resolvePendingOp } from "../pendingOps";

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
