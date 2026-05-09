/**
 * Tests for the ``/api/quota/current`` typed client (item 2.4) —
 * verifies the GET happens at the correct URL, the response decodes
 * to :interface:`QuotaSnapshot`, and the error contract surfaces
 * 404 / 502 / 503 to the dialog's fallback path.
 *
 * Also covers :func:`getCurrentQuotaSafe` (console-replay-001-FE):
 * documented empty-state responses (404 / 503 / 502) must resolve
 * ``null`` without logging to ``console.error``.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../client";
import { getCurrentQuota, getCurrentQuotaSafe, type QuotaSnapshot } from "../quota";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("getCurrentQuota", () => {
  it("GETs /api/quota/current and decodes the snapshot", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          captured_at: 1_700_000_000,
          overall_used_pct: 0.31,
          sonnet_used_pct: 0.14,
          overall_resets_at: 1_700_500_000,
          sonnet_resets_at: 1_700_500_000,
          raw_payload: '{"foo":"bar"}',
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );
    const snapshot = await getCurrentQuota();
    expect(snapshot.overall_used_pct).toBe(0.31);
    expect(snapshot.sonnet_used_pct).toBe(0.14);
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/quota/current");
  });

  it("throws ApiError on 404 (no snapshot recorded yet)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "no snapshot" }), {
        status: 404,
        statusText: "Not Found",
        headers: { "content-type": "application/json" },
      }),
    );
    let captured: unknown = null;
    try {
      await getCurrentQuota();
    } catch (error) {
      captured = error;
    }
    expect(captured).toBeInstanceOf(ApiError);
    expect((captured as ApiError).status).toBe(404);
  });
});

// ---- getCurrentQuotaSafe (console-replay-001-FE) ----------------------------

/** Minimal valid snapshot body. */
function makeSnapshotBody(): QuotaSnapshot {
  return {
    captured_at: 1_700_000_000,
    overall_used_pct: 0.5,
    sonnet_used_pct: 0.2,
    overall_resets_at: 1_700_500_000,
    sonnet_resets_at: 1_700_500_000,
    raw_payload: "{}",
  };
}

describe("getCurrentQuotaSafe", () => {
  it("resolves null on 404 without logging to console.error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "no snapshot" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );
    const consoleSpy = vi.spyOn(console, "error");
    const result = await getCurrentQuotaSafe();
    expect(result).toBeNull();
    expect(consoleSpy).not.toHaveBeenCalled();
  });

  it("resolves null on 503 (poller not configured) without console.error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "quota poller not configured" }), {
        status: 503,
        headers: { "content-type": "application/json" },
      }),
    );
    const consoleSpy = vi.spyOn(console, "error");
    const result = await getCurrentQuotaSafe();
    expect(result).toBeNull();
    expect(consoleSpy).not.toHaveBeenCalled();
  });

  it("resolves null on 502 (upstream poll blip) without console.error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "upstream blip" }), {
        status: 502,
        headers: { "content-type": "application/json" },
      }),
    );
    const consoleSpy = vi.spyOn(console, "error");
    const result = await getCurrentQuotaSafe();
    expect(result).toBeNull();
    expect(consoleSpy).not.toHaveBeenCalled();
  });

  it("resolves the snapshot on 200", async () => {
    const body = makeSnapshotBody();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const result = await getCurrentQuotaSafe();
    expect(result).not.toBeNull();
    expect(result?.overall_used_pct).toBe(0.5);
    expect(result?.sonnet_used_pct).toBe(0.2);
  });

  it("re-throws unexpected ApiError statuses (e.g. 500)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "internal error" }), {
        status: 500,
        headers: { "content-type": "application/json" },
      }),
    );
    let caught: unknown = null;
    try {
      await getCurrentQuotaSafe();
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(500);
  });
});
