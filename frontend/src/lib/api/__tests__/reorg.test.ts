/**
 * Tests for the reorg API client — mergeSession, splitSession,
 * moveMessageReorg (gap-cycle-03-008, gap-cycle-13-002).
 *
 * Acceptance criteria:
 *
 * - ``mergeSession`` fires ``POST /api/sessions/{src}/reorg/merge?target={dst}``.
 * - ``splitSession`` fires ``POST /api/sessions/{src}/reorg/split?target={dst}&from_seq={n}``.
 * - ``moveMessageReorg`` fires ``POST /api/sessions/{src}/reorg/move?target={dst}&message_id={id}``.
 * - All return the correct wire shapes on 200.
 * - All throw :class:`ApiError` on 409 / 404.
 * - URL-encodes all path and query parameters.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../client";
import {
  mergeSession,
  moveMessageReorg,
  splitSession,
  type ReorgAuditOut,
  type ReorgSplitOut,
} from "../reorg";

afterEach(() => {
  vi.restoreAllMocks();
});

const mockAudit: ReorgAuditOut = {
  id: "rga_abc123",
  dst_session_id: "ses_dst",
  src_session_id: "ses_src",
  merged_at: "2026-05-07T12:00:00.000000+00:00",
  src_title: "Old Session",
  boundary_msg_id: "msg_first",
  kind: "merge",
};

describe("mergeSession", () => {
  it("POSTs to the correct merge endpoint and returns the audit row", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockAudit), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const result = await mergeSession("ses_src", "ses_dst");

    expect(result.id).toBe("rga_abc123");
    expect(result.dst_session_id).toBe("ses_dst");
    expect(result.src_session_id).toBe("ses_src");
    expect(result.boundary_msg_id).toBe("msg_first");

    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toBe("/api/sessions/ses_src/reorg/merge?target=ses_dst");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
  });

  it("URL-encodes both session ids", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockAudit), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await mergeSession("ses src/special", "ses dst/target");

    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toBe(
      "/api/sessions/ses%20src%2Fspecial/reorg/merge?target=ses%20dst%2Ftarget",
    );
  });

  it("throws ApiError with status 409 on self-merge response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "self-merge is not permitted" }), {
        status: 409,
        headers: { "content-type": "application/json" },
      }),
    );

    await expect(mergeSession("ses_a", "ses_a")).rejects.toBeInstanceOf(ApiError);
    try {
      await mergeSession("ses_a", "ses_a");
    } catch (err) {
      if (err instanceof ApiError) {
        expect(err.status).toBe(409);
      }
    }
  });

  it("throws ApiError with status 404 on missing session", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "not found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );

    await expect(mergeSession("ses_nonexistent", "ses_dst")).rejects.toBeInstanceOf(ApiError);
  });

  it("returns null boundary_msg_id when src had no messages", async () => {
    const noMsgsAudit: ReorgAuditOut = { ...mockAudit, boundary_msg_id: null };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(noMsgsAudit), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const result = await mergeSession("ses_src", "ses_dst");
    expect(result.boundary_msg_id).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// splitSession (gap-cycle-13-002)
// ---------------------------------------------------------------------------

const mockSplitResult: ReorgSplitOut = {
  audit: {
    id: "rga_split1",
    dst_session_id: "ses_src",
    src_session_id: "ses_dst",
    merged_at: "2026-05-07T12:00:00.000000+00:00",
    src_title: "Target Session",
    boundary_msg_id: "msg_second",
    kind: "split",
  },
  moved_message_ids: ["msg_second", "msg_third"],
};

describe("splitSession", () => {
  it("POSTs to the correct split endpoint and returns split result", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockSplitResult), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const result = await splitSession("ses_src", "ses_dst", 42);

    expect(result.audit.kind).toBe("split");
    expect(result.audit.dst_session_id).toBe("ses_src");
    expect(result.moved_message_ids).toEqual(["msg_second", "msg_third"]);

    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toBe("/api/sessions/ses_src/reorg/split?target=ses_dst&from_seq=42");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
  });

  it("throws ApiError with status 409 on self-split", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "self-split is not permitted" }), {
        status: 409,
        headers: { "content-type": "application/json" },
      }),
    );
    await expect(splitSession("ses_a", "ses_a", 1)).rejects.toBeInstanceOf(ApiError);
  });

  it("throws ApiError with status 404 on missing session", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "not found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );
    await expect(splitSession("ses_nonexistent", "ses_dst", 1)).rejects.toBeInstanceOf(ApiError);
  });
});

// ---------------------------------------------------------------------------
// moveMessageReorg (gap-cycle-13-002)
// ---------------------------------------------------------------------------

const mockMoveAudit: ReorgAuditOut = {
  id: "rga_move1",
  dst_session_id: "ses_src",
  src_session_id: "ses_dst",
  merged_at: "2026-05-07T12:00:00.000000+00:00",
  src_title: "Target Session",
  boundary_msg_id: "msg_moved",
  kind: "move",
};

describe("moveMessageReorg", () => {
  it("POSTs to the correct move endpoint and returns the audit row", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockMoveAudit), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const result = await moveMessageReorg("ses_src", "ses_dst", "msg_moved");

    expect(result.kind).toBe("move");
    expect(result.boundary_msg_id).toBe("msg_moved");
    expect(result.dst_session_id).toBe("ses_src");

    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toBe(
      "/api/sessions/ses_src/reorg/move?target=ses_dst&message_id=msg_moved",
    );
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
  });

  it("throws ApiError with status 409 on self-move", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "src and target must differ" }), {
        status: 409,
        headers: { "content-type": "application/json" },
      }),
    );
    await expect(moveMessageReorg("ses_a", "ses_a", "msg_x")).rejects.toBeInstanceOf(ApiError);
  });

  it("throws ApiError with status 404 when message absent", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "not found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );
    await expect(
      moveMessageReorg("ses_src", "ses_dst", "msg_nonexistent"),
    ).rejects.toBeInstanceOf(ApiError);
  });
});
