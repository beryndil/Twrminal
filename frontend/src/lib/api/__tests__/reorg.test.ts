/**
 * Tests for the reorg API client — ``mergeSession`` (gap-cycle-03-008).
 *
 * Acceptance criteria:
 *
 * - ``mergeSession`` fires ``POST /api/sessions/{src}/reorg/merge?target={dst}``.
 * - Returns the :class:`ReorgAuditOut` envelope on 200.
 * - Throws :class:`ApiError` on 409 (self-merge) and 404 (missing session).
 * - URL-encodes both session ids.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../client";
import { mergeSession, type ReorgAuditOut } from "../reorg";

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
