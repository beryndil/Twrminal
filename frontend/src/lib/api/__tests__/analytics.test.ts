/**
 * Unit tests for ``api/analytics.ts`` (Analytics Phase 5).
 *
 * Covers: correct endpoint construction, query-param mapping,
 * and POST body shape for every public function.
 *
 * Uses ``vi.spyOn(globalThis, "fetch")`` (the same pattern used by
 * the other API client tests in this directory) so no real network
 * calls are made.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getAttribution,
  getBucketCurrent,
  getRedundancy,
  getSessionPlugSummary,
  suppressWarning,
  type BucketCurrentOut,
  type RedundancyBlockOut,
  type SessionPlugSummaryOut,
  type TagAttributionOut,
} from "../analytics";
import {
  ANALYTICS_ATTRIBUTION_WINDOW_5H,
  ANALYTICS_ATTRIBUTION_WINDOW_WEEKLY,
  ANALYTICS_REDUNDANCY_DEFAULT_LAST_N,
  ANALYTICS_REDUNDANCY_DEFAULT_MIN_REPEATS,
  API_ANALYTICS_ATTRIBUTION_ENDPOINT,
  API_ANALYTICS_BUCKET_CURRENT_ENDPOINT,
  API_ANALYTICS_SESSION_PLUG_SUMMARY_ENDPOINT,
  API_ANALYTICS_WARNINGS_SUPPRESS_ENDPOINT,
} from "../../config";

function mockFetch(body: unknown, status = 200): void {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// getBucketCurrent
// ---------------------------------------------------------------------------

describe("getBucketCurrent", () => {
  it("GETs the bucket/current endpoint with no query params", async () => {
    const payload: BucketCurrentOut = {
      five_hour: { used: 100, limit: 200_000, percent: 0.05 },
      weekly: { used: 500_000, limit: 5_000_000, percent: 10 },
      as_of: 1_715_000_000_000,
    };
    mockFetch(payload);

    const result = await getBucketCurrent();

    expect(fetch).toHaveBeenCalledOnce();
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toBe(API_ANALYTICS_BUCKET_CURRENT_ENDPOINT);
    expect(result).toEqual(payload);
  });

  it("passes the AbortSignal when provided", async () => {
    mockFetch({ five_hour: null, weekly: null, as_of: 0 });
    const ctrl = new AbortController();
    await getBucketCurrent({ signal: ctrl.signal });

    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(init.signal).toBe(ctrl.signal);
  });
});

// ---------------------------------------------------------------------------
// getAttribution
// ---------------------------------------------------------------------------

describe("getAttribution", () => {
  it("defaults to the weekly window and group_by=tag", async () => {
    const payload: TagAttributionOut[] = [];
    mockFetch(payload);

    await getAttribution();

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toContain(API_ANALYTICS_ATTRIBUTION_ENDPOINT);
    expect(url).toContain(`window=${ANALYTICS_ATTRIBUTION_WINDOW_WEEKLY}`);
    expect(url).toContain("group_by=tag");
  });

  it("uses the provided window parameter", async () => {
    mockFetch([]);
    await getAttribution({ window: ANALYTICS_ATTRIBUTION_WINDOW_5H });

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toContain(`window=${ANALYTICS_ATTRIBUTION_WINDOW_5H}`);
  });

  it("returns the decoded payload", async () => {
    const row: TagAttributionOut = {
      tag: "infra",
      tokens_by_model: { "claude-opus-4-7": 78_000 },
      share_total: 0.42,
      burn_rate_per_min: 380,
    };
    mockFetch([row]);

    const result = await getAttribution();
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual(row);
  });
});

// ---------------------------------------------------------------------------
// getRedundancy
// ---------------------------------------------------------------------------

describe("getRedundancy", () => {
  it("sends default last_n and min_repeats when no options given", async () => {
    mockFetch([]);
    await getRedundancy();

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toContain(`last_n=${ANALYTICS_REDUNDANCY_DEFAULT_LAST_N}`);
    expect(url).toContain(`min_repeats=${ANALYTICS_REDUNDANCY_DEFAULT_MIN_REPEATS}`);
    expect(url).not.toContain("tag=");
    expect(url).not.toContain("block_types=");
  });

  it("includes the tag param when provided", async () => {
    mockFetch([]);
    await getRedundancy({ tag: "infra" });

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toContain("tag=infra");
  });

  it("omits tag param when tag is null", async () => {
    mockFetch([]);
    await getRedundancy({ tag: null });

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).not.toContain("tag=");
  });

  it("includes block_types when provided", async () => {
    mockFetch([]);
    await getRedundancy({ blockTypes: "claude_md,tag_memory" });

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toContain("block_types=");
  });

  it("returns decoded redundancy blocks", async () => {
    const block: RedundancyBlockOut = {
      hash: "abc123",
      block_type: "claude_md",
      token_count: 850,
      token_count_model: "claude-opus-4-7",
      repeat_count: 14,
      total_cost_tokens: 11_900,
      source_path: "~/.claude/CLAUDE.md",
      sessions: [
        { id: "ses_1", title: "Session 1", timestamp: 1_700_000_000_000, tags: ["infra"] },
      ],
    };
    mockFetch([block]);

    const result = await getRedundancy();
    expect(result).toHaveLength(1);
    expect(result[0].hash).toBe("abc123");
    expect(result[0].sessions).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// getSessionPlugSummary
// ---------------------------------------------------------------------------

describe("getSessionPlugSummary", () => {
  it("constructs the correct URL with the session id", async () => {
    const payload: SessionPlugSummaryOut = {
      total_tokens: 1820,
      status: "red",
      blocks: [{ hash: "abc", block_type: "claude_md", tokens: 850 }],
    };
    mockFetch(payload);

    await getSessionPlugSummary("ses_abc");

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toBe(`${API_ANALYTICS_SESSION_PLUG_SUMMARY_ENDPOINT}/ses_abc/plug-summary`);
  });

  it("returns the decoded summary", async () => {
    const payload: SessionPlugSummaryOut = {
      total_tokens: 300,
      status: "green",
      blocks: [],
    };
    mockFetch(payload);

    const result = await getSessionPlugSummary("ses_xyz");
    expect(result.total_tokens).toBe(300);
    expect(result.status).toBe("green");
  });
});

// ---------------------------------------------------------------------------
// suppressWarning
// ---------------------------------------------------------------------------

describe("suppressWarning", () => {
  it("POSTs to the suppress endpoint with the correct JSON body", async () => {
    mockFetch({ status: "ok" });

    await suppressWarning({ block_hash: "abc123", warning_type: "yellow_length" });

    expect(fetch).toHaveBeenCalledOnce();
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toBe(API_ANALYTICS_WARNINGS_SUPPRESS_ENDPOINT);
    expect(init.method).toBe("POST");
    const sent = JSON.parse(init.body as string) as unknown;
    expect(sent).toEqual({ block_hash: "abc123", warning_type: "yellow_length" });
  });

  it("returns the decoded status payload", async () => {
    mockFetch({ status: "ok" });
    const result = await suppressWarning({ block_hash: "x", warning_type: "red_length" });
    expect(result).toEqual({ status: "ok" });
  });
});
