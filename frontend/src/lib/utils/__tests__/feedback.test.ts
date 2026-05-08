/**
 * Unit tests for ``src/lib/utils/feedback.ts``
 * (gap-cycle-01-008 + gap-cycle-07-004).
 *
 * Acceptance criteria covered:
 *
 * 1. URL composition — :func:`buildFeedbackUrl` returns a GitHub
 *    ``issues/new`` URL whose ``body`` query param contains the
 *    supplied version, the browser UA, platform, language, and the
 *    kind-appropriate reproduction scaffold headers.
 * 2. Kind discriminator — ``"bug"`` emits ``labels=bug`` and the
 *    bug scaffold; ``"feature"`` emits ``labels=feature`` and the
 *    feature scaffold; the two URLs are distinct.
 * 3. Lazy version fetch on first click — :func:`fetchVersion` calls
 *    ``fetch`` exactly once on the first invocation.
 * 4. Cache reuse on second click — a second :func:`fetchVersion` call
 *    does NOT issue a second ``fetch`` request.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { _resetVersionCacheForTests, buildFeedbackUrl, fetchVersion } from "../feedback";

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
// AC1: URL composition — common fields present in both kinds
// ---------------------------------------------------------------------------

describe("buildFeedbackUrl — common fields", () => {
  it("starts with the Bearings GitHub issues/new URL (bug)", () => {
    const url = buildFeedbackUrl("bug", "1.2.3");
    expect(url).toMatch(/^https:\/\/github\.com\/Beryndil\/Bearings\/issues\/new/);
  });

  it("starts with the Bearings GitHub issues/new URL (feature)", () => {
    const url = buildFeedbackUrl("feature", "1.2.3");
    expect(url).toMatch(/^https:\/\/github\.com\/Beryndil\/Bearings\/issues\/new/);
  });

  it("body param contains the supplied version", () => {
    const url = buildFeedbackUrl("bug", "0.99.1");
    const body = decodeURIComponent(new URL(url).searchParams.get("body") ?? "");
    expect(body).toContain("0.99.1");
  });

  it("body param contains the browser user-agent", () => {
    const url = buildFeedbackUrl("bug", "1.0.0");
    const body = decodeURIComponent(new URL(url).searchParams.get("body") ?? "");
    // jsdom sets navigator.userAgent to a non-empty string.
    expect(body).toContain(navigator.userAgent);
  });

  it("body param contains the platform", () => {
    const url = buildFeedbackUrl("bug", "1.0.0");
    const body = decodeURIComponent(new URL(url).searchParams.get("body") ?? "");
    expect(body).toContain(navigator.platform);
  });

  it("body param contains the language", () => {
    const url = buildFeedbackUrl("bug", "1.0.0");
    const body = decodeURIComponent(new URL(url).searchParams.get("body") ?? "");
    expect(body).toContain(navigator.language);
  });
});

// ---------------------------------------------------------------------------
// AC2: Kind discriminator — bug vs. feature produce distinct URLs / labels
// ---------------------------------------------------------------------------

describe("buildFeedbackUrl — FeedbackKind discriminator", () => {
  it("bug kind: body contains the bug scaffold headers", () => {
    const url = buildFeedbackUrl("bug", "1.0.0");
    const body = decodeURIComponent(new URL(url).searchParams.get("body") ?? "");
    expect(body).toContain("## Steps to reproduce");
    expect(body).toContain("## Expected behavior");
    expect(body).toContain("## Actual behavior");
  });

  it("bug kind: labels param is 'bug'", () => {
    const url = buildFeedbackUrl("bug", "1.0.0");
    expect(new URL(url).searchParams.get("labels")).toBe("bug");
  });

  it("feature kind: body contains the feature scaffold headers", () => {
    const url = buildFeedbackUrl("feature", "1.0.0");
    const body = decodeURIComponent(new URL(url).searchParams.get("body") ?? "");
    expect(body).toContain("## Use case");
    expect(body).toContain("## Proposed behavior");
    expect(body).toContain("## Alternatives considered");
  });

  it("feature kind: labels param is 'feature'", () => {
    const url = buildFeedbackUrl("feature", "1.0.0");
    expect(new URL(url).searchParams.get("labels")).toBe("feature");
  });

  it("bug and feature produce distinct URLs", () => {
    const bugUrl = buildFeedbackUrl("bug", "1.0.0");
    const featureUrl = buildFeedbackUrl("feature", "1.0.0");
    expect(bugUrl).not.toBe(featureUrl);
  });

  it("feature kind does NOT contain bug scaffold headers", () => {
    const url = buildFeedbackUrl("feature", "1.0.0");
    const body = decodeURIComponent(new URL(url).searchParams.get("body") ?? "");
    expect(body).not.toContain("## Steps to reproduce");
  });

  it("bug kind does NOT contain feature scaffold headers", () => {
    const url = buildFeedbackUrl("bug", "1.0.0");
    const body = decodeURIComponent(new URL(url).searchParams.get("body") ?? "");
    expect(body).not.toContain("## Use case");
  });
});

// ---------------------------------------------------------------------------
// AC3 + AC4: lazy fetch and cache reuse
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
