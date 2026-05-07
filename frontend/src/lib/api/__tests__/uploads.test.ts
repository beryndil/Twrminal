/**
 * Tests for :func:`uploadFile` — locks the wire contract (multipart
 * POST, error shape, abort signal propagation) without touching the
 * real HTTP layer.
 *
 * Behavior anchor: ``docs/behavior/chat.md``
 * §"Composer — attachment ingestion".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../client";
import { uploadFile } from "../uploads";

const fetchMock = vi.fn();

function uploadResponse(id: number, filename: string): Response {
  return {
    status: 201,
    statusText: "Created",
    json: async () => ({
      id,
      sha256: "abc123",
      filename,
      mime_type: "text/plain",
      size: 4,
      created_at: 1_000_000,
    }),
    text: async () => JSON.stringify({ id }),
  } as unknown as Response;
}

function errorResponse(status: number, detail: string): Response {
  return {
    status,
    statusText: "Error",
    json: async () => ({ detail }),
    text: async () => JSON.stringify({ detail }),
  } as unknown as Response;
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("uploadFile", () => {
  it("POSTs to /api/uploads with multipart/form-data and returns the server row", async () => {
    fetchMock.mockResolvedValueOnce(uploadResponse(42, "test.txt"));
    const file = new File(["data"], "test.txt", { type: "text/plain" });
    const result = await uploadFile(file);
    expect(result.id).toBe(42);
    expect(result.filename).toBe("test.txt");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/uploads");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    const form = init.body as FormData;
    expect(form.get("file")).toBeInstanceOf(File);
  });

  it("throws ApiError on a non-2xx response, carrying the detail body", async () => {
    fetchMock.mockResolvedValueOnce(errorResponse(413, "upload body is too large"));
    const file = new File(["big"], "huge.bin", { type: "application/octet-stream" });
    await expect(uploadFile(file)).rejects.toBeInstanceOf(ApiError);
    let err: ApiError | null = null;
    try {
      await uploadFile(file);
    } catch (e) {
      err = e as ApiError;
    }
    // fetchMock was called once above and once now — just check status on the second throw.
    // Reset and re-run cleanly:
    fetchMock.mockResolvedValueOnce(errorResponse(413, "upload body is too large"));
    try {
      await uploadFile(file);
    } catch (e) {
      err = e as ApiError;
    }
    expect(err).not.toBeNull();
    expect(err!.status).toBe(413);
    expect((err!.body as { detail: string }).detail).toBe("upload body is too large");
  });

  it("forwards the AbortSignal to fetch so the request is cancellable", async () => {
    fetchMock.mockResolvedValueOnce(uploadResponse(7, "cancel.txt"));
    const file = new File(["x"], "cancel.txt", { type: "text/plain" });
    const ctrl = new AbortController();
    await uploadFile(file, ctrl.signal);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.signal).toBe(ctrl.signal);
  });

  it("propagates AbortError when the signal fires before the response arrives", async () => {
    const ctrl = new AbortController();
    fetchMock.mockRejectedValueOnce(Object.assign(new Error("The user aborted a request."), { name: "AbortError" }));
    const file = new File(["x"], "cancel.txt", { type: "text/plain" });
    ctrl.abort();
    let thrown: unknown = null;
    try {
      await uploadFile(file, ctrl.signal);
    } catch (e) {
      thrown = e;
    }
    expect(thrown).toBeInstanceOf(Error);
    expect((thrown as Error).name).toBe("AbortError");
  });
});
