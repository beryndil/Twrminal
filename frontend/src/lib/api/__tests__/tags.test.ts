/**
 * Wire-shape tests for the tag-class API client. Pins the URL +
 * payload shape that the backend route layer (in
 * ``src/bearings/web/routes/tags.py``) accepts; if the wire shape
 * drifts the assertion fires before any UI consumer sees the
 * mismatch.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { TAG_CLASS_PROJECT, TAG_CLASS_SEVERITY, updateTagSortOrder } from "../tags";

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonResponse(status = 204): Response {
  return new Response(null, { status });
}

describe("updateTagSortOrder", () => {
  it("PUTs to /api/tags/sort-order with class_ + ordered_ids", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse());
    await updateTagSortOrder(TAG_CLASS_PROJECT, [3, 1, 2]);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/tags/sort-order");
    expect((init as RequestInit | undefined)?.method).toBe("PUT");
    const body = JSON.parse(String((init as RequestInit | undefined)?.body));
    expect(body).toEqual({ class_: "project", ordered_ids: [3, 1, 2] });
  });

  it("accepts severity class on the wire", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse());
    await updateTagSortOrder(TAG_CLASS_SEVERITY, []);
    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(String((init as RequestInit | undefined)?.body));
    expect(body.class_).toBe("severity");
    expect(body.ordered_ids).toEqual([]);
  });

  it("throws on non-2xx", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "bad ids" }), { status: 422 }),
    );
    await expect(updateTagSortOrder(TAG_CLASS_PROJECT, [99])).rejects.toThrow();
  });
});
