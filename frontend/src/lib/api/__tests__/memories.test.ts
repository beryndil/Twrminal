/**
 * Tests for ``api/memories.ts`` — verifies URL shape + body
 * projection + the full CRUD surface (memories ARE editable, unlike
 * the read-only vault).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createMemory,
  deleteMemory,
  getMemory,
  listAllMemories,
  listTagMemories,
  updateMemory,
  type AllMemoriesRow,
  type TagMemoryIn,
} from "../memories";

afterEach(() => {
  vi.restoreAllMocks();
});

const fakeMemory = {
  id: 42,
  tag_id: 7,
  title: "T",
  body: "B",
  enabled: true,
  created_at: "2026-04-29T00:00:00Z",
  updated_at: "2026-04-29T00:00:00Z",
};

const fakeAllMemoriesRow: AllMemoriesRow = {
  tag_id: 7,
  tag_name: "bearings/architect",
  tag_color: null,
  memory_id: 42,
  memory_title: "T",
  memory_body_preview: "B",
  enabled: true,
  updated_at: "2026-04-29T00:00:00Z",
};

describe("listAllMemories", () => {
  it("GETs /api/memories and returns the flat list", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify([fakeAllMemoriesRow]), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const out = await listAllMemories();
    expect(out).toHaveLength(1);
    expect(out[0].memory_id).toBe(42);
    expect(out[0].tag_name).toBe("bearings/architect");
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/memories");
  });

  it("returns [] when the response is an empty array", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const out = await listAllMemories();
    expect(out).toEqual([]);
  });
});

describe("listTagMemories", () => {
  it("GETs /api/tags/{tag_id}/memories", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify([fakeMemory]), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const out = await listTagMemories(7);
    expect(out).toHaveLength(1);
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/tags/7/memories");
  });
});

describe("getMemory", () => {
  it("GETs /api/memories/{id}", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(fakeMemory), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const out = await getMemory(42);
    expect(out.id).toBe(42);
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/memories/42");
  });
});

describe("createMemory", () => {
  it("POSTs to /api/tags/{tag_id}/memories with the wire body", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(fakeMemory), {
        status: 201,
        headers: { "content-type": "application/json" },
      }),
    );
    const body: TagMemoryIn = { title: "T", body: "B", enabled: true };
    await createMemory(7, body);
    const init = fetchMock.mock.calls[0][1];
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual(body);
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/tags/7/memories");
  });
});

describe("updateMemory", () => {
  it("PATCHes /api/memories/{id} with the wire body", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ ...fakeMemory, enabled: false }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const body: TagMemoryIn = { title: "T", body: "B", enabled: false };
    const out = await updateMemory(42, body);
    expect(out.enabled).toBe(false);
    expect(fetchMock.mock.calls[0][1]?.method).toBe("PATCH");
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/memories/42");
  });
});

describe("deleteMemory", () => {
  it("DELETEs /api/memories/{id} and tolerates 204", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    await deleteMemory(42);
    expect(fetchMock.mock.calls[0][1]?.method).toBe("DELETE");
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/memories/42");
  });
});
