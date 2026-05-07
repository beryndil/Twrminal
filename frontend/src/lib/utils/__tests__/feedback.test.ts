/**
 * Unit tests for ``src/lib/utils/feedback.ts`` (gap-cycle-01-008).
 *
 * Acceptance criteria covered:
 *
 * 1. URL composition — :func:`buildFeedbackUrl` returns a GitHub
 *    ``issues/new`` URL whose ``body`` query param contains the
 *    supplied version, the browser UA, platform, language, and the
 *    reproduction scaffold headers.
 * 2. Lazy version fetch on first click — :func:`fetchVersion` calls
 *    ``fetch`` exactly once on the first invocation.
 * 3. Cache reuse on second click — a second :func:`fetchVersion` call
 *    does NOT issue a second ``fetch`` request.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  _resetVersionCacheForTests,
  buildFeedbackUrl,
  fetchVersion,
} from "../feedback";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a minimal ``Response``-like object accepted by the fetch stub. */
function makeOkResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function makeErrorResponse(status: number): Response {
  return new Response(JSON.stringify({ detail: "error" }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

beforeEach(() => {
  // Reset module-level cache between tests so each test gets a clean slate.
  _resetVersionCacheForTests();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// AC1: URL composition
// ---------------------------------------------------------------------------

describe("buildFeedbackUrl", () => {
  it("starts with the Bearings GitHub issues/new URL", () => {
    const url = buildFeedbackUrl("1.2.3");
    expect(url).toMatch(/^https:\/\/github\.com\/Beryndil\/Bearings\/issues\/new/);
  });

  it("body param contains the supplied version", () => {
    const url = buildFeedbackUrl("0.99.1");
    const body = decodeURIComponent(new URL(url).searchParams.get("body") ?? "");
    expect(body).toContain("0.99.1");
  });

  it("body param contains the browser user-agent", () => {
    const url = buildFeedbackUrl("1.0.0");
    const body = decodeURIComponent(new URL(url).searchParams.get("body") ?? "");
    // jsdom sets navigator.userAgent to a non-empty string.
    expect(body).toContain(navigator.userAgent);
  });

  it("body param contains the platform", () => {
    const url = buildFeedbackUrl("1.0.0");
    const body = decodeURIComponent(new URL(url).searchParams.get("body") ?? "");
    expect(body).toContain(navigator.platform);
  });

  it("body param contains the language", () => {
    const url = buildFeedbackUrl("1.0.0");
    const body = decodeURIComponent(new URL(url).searchParams.get("body") ?? "");
    expect(body).toContain(navigator.language);
  });

  it("body param contains the reproduction scaffold headers", () => {
    const url = buildFeedbackUrl("1.0.0");
    const body = decodeURIComponent(new URL(url).searchParams.get("body") ?? "");
    expect(body).toContain("## Steps to reproduce");
    expect(body).toContain("## Expected behavior");
    expect(body).toContain("## Actual behavior");
  });

  it("includes the 'bug' label", () => {
    const url = buildFeedbackUrl("1.0.0");
    const parsed = new URL(url);
    expect(parsed.searchParams.get("labels")).toBe("bug");
  });
});

// ---------------------------------------------------------------------------
// AC2 + AC3: lazy fetch and cache reuse
// ---------------------------------------------------------------------------

describe("fetchVersion", () => {
  it("fetches from /api/diag/server on the first call", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(makeOkResponse({ version: "1.5.0", uptime: 0, pid: 1 }));

    const version = await fetchVersion();

    expect(version).toBe("1.5.0");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(String(fetchSpy.mock.calls[0][0])).toContain("/api/diag/server");
  });

  it("reuses the cached promise on the second call without re-fetching", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(makeOkResponse({ version: "2.0.0", uptime: 0, pid: 1 }));

    // First call — initiates fetch.
    const v1 = await fetchVersion();
    // Second call — must reuse the cached promise.
    const v2 = await fetchVersion();

    expect(v1).toBe("2.0.0");
    expect(v2).toBe("2.0.0");
    // Fetch must have been called exactly once across both invocations.
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("falls back to 'unknown' when the fetch fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(makeErrorResponse(503));

    const version = await fetchVersion();

    expect(version).toBe("unknown");
  });

  it("falls back to 'unknown' on a network error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("Network error"));

    const version = await fetchVersion();

    expect(version).toBe("unknown");
  });
});
