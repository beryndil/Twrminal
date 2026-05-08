/**
 * Unit tests for ``api/analytics.ts`` (Analytics Phases 5 + 6).
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
  createSessionFromDraft,
  draftNewSession,
  getAttribution,
  getBucketCurrent,
  getRedundancy,
  getSessionPlugSummary,
  promoteToOnOpen,
  promoteToTagMemory,
  suppressWarning,
  type BucketCurrentOut,
  type DraftNewSessionOut,
  type PromoteToOnOpenOut,
  type PromoteToTagMemoryOut,
  type RedundancyBlockOut,
  type SessionFromDraftOut,
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
  API_ANALYTICS_DRAFT_NEW_SESSION_ENDPOINT,
  API_ANALYTICS_PLUG_BLOCKS_BASE,
  API_ANALYTICS_SESSION_PLUG_SUMMARY_ENDPOINT,
  API_ANALYTICS_SESSIONS_FROM_DRAFT_ENDPOINT,
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

// ---------------------------------------------------------------------------
// promoteToTagMemory (Phase 6)
// ---------------------------------------------------------------------------

const _TEST_HASH = "a".repeat(64);

describe("promoteToTagMemory", () => {
  it("POSTs to the correct hash-parameterised endpoint", async () => {
    const payload: PromoteToTagMemoryOut = { memory_id: 1, tag: "infra" };
    mockFetch(payload);

    await promoteToTagMemory(_TEST_HASH, {
      tag: "infra",
      memory_content: "Remember this.",
    });

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_ANALYTICS_PLUG_BLOCKS_BASE}/${_TEST_HASH}/promote-to-tag-memory`);
    expect(init.method).toBe("POST");
    const sent = JSON.parse(init.body as string) as unknown;
    expect((sent as Record<string, unknown>)["tag"]).toBe("infra");
    expect((sent as Record<string, unknown>)["memory_content"]).toBe("Remember this.");
  });

  it("returns the decoded promote response", async () => {
    const payload: PromoteToTagMemoryOut = { memory_id: 42, tag: "infra" };
    mockFetch(payload);

    const result = await promoteToTagMemory(_TEST_HASH, {
      tag: "infra",
      memory_content: "x",
    });
    expect(result.memory_id).toBe(42);
    expect(result.tag).toBe("infra");
  });

  it("passes the AbortSignal when provided", async () => {
    mockFetch({ memory_id: 1, tag: "infra" });
    const ctrl = new AbortController();
    await promoteToTagMemory(
      _TEST_HASH,
      { tag: "infra", memory_content: "x" },
      { signal: ctrl.signal },
    );

    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(init.signal).toBe(ctrl.signal);
  });
});

// ---------------------------------------------------------------------------
// promoteToOnOpen (Phase 6)
// ---------------------------------------------------------------------------

describe("promoteToOnOpen", () => {
  it("POSTs to the correct hash-parameterised endpoint", async () => {
    const payload: PromoteToOnOpenOut = { on_open_sh_path: "/tmp/proj/.bearings/on_open.sh" };
    mockFetch(payload);

    await promoteToOnOpen(_TEST_HASH, {
      working_directory: "/tmp/proj",
      snippet: "echo hello",
    });

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_ANALYTICS_PLUG_BLOCKS_BASE}/${_TEST_HASH}/promote-to-on-open`);
    expect(init.method).toBe("POST");
    const sent = JSON.parse(init.body as string) as unknown;
    expect((sent as Record<string, unknown>)["working_directory"]).toBe("/tmp/proj");
    expect((sent as Record<string, unknown>)["snippet"]).toBe("echo hello");
  });

  it("returns the decoded promote response", async () => {
    const payload: PromoteToOnOpenOut = { on_open_sh_path: "/out/path" };
    mockFetch(payload);

    const result = await promoteToOnOpen(_TEST_HASH, {
      working_directory: "/tmp",
      snippet: "x",
    });
    expect(result.on_open_sh_path).toBe("/out/path");
  });
});

// ---------------------------------------------------------------------------
// draftNewSession (Phase 6)
// ---------------------------------------------------------------------------

describe("draftNewSession", () => {
  it("POSTs to the draft-new-session endpoint with the correct body", async () => {
    const payload: DraftNewSessionOut = {
      draft_plug: "# Continuing from Foo",
      estimated_tokens: 80,
      draft_cost_tokens: { input: 0, output: 0 },
    };
    mockFetch(payload);

    await draftNewSession({ source_session_id: "ses_abc", carry_tags: ["infra"] });

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toBe(API_ANALYTICS_DRAFT_NEW_SESSION_ENDPOINT);
    expect(init.method).toBe("POST");
    const sent = JSON.parse(init.body as string) as unknown;
    expect((sent as Record<string, unknown>)["source_session_id"]).toBe("ses_abc");
    expect((sent as Record<string, unknown>)["carry_tags"]).toEqual(["infra"]);
  });

  it("returns the decoded draft payload", async () => {
    const payload: DraftNewSessionOut = {
      draft_plug: "draft",
      estimated_tokens: 10,
      draft_cost_tokens: { input: 0, output: 0 },
    };
    mockFetch(payload);

    const result = await draftNewSession({ source_session_id: "ses_xyz" });
    expect(result.draft_plug).toBe("draft");
    expect(result.estimated_tokens).toBe(10);
  });
});

// ---------------------------------------------------------------------------
// createSessionFromDraft (Phase 6)
// ---------------------------------------------------------------------------

describe("createSessionFromDraft", () => {
  it("POSTs to the sessions/from-draft endpoint", async () => {
    const payload: SessionFromDraftOut = { session_id: "ses_new" };
    mockFetch(payload);

    await createSessionFromDraft({
      draft_plug: "# New session",
      tags: ["infra"],
      working_directory: "/tmp",
    });

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toBe(API_ANALYTICS_SESSIONS_FROM_DRAFT_ENDPOINT);
    expect(init.method).toBe("POST");
    const sent = JSON.parse(init.body as string) as unknown;
    expect((sent as Record<string, unknown>)["draft_plug"]).toBe("# New session");
    expect((sent as Record<string, unknown>)["tags"]).toEqual(["infra"]);
    expect((sent as Record<string, unknown>)["working_directory"]).toBe("/tmp");
  });

  it("returns the new session id", async () => {
    mockFetch({ session_id: "ses_xyz" });
    const result = await createSessionFromDraft({
      draft_plug: "x",
      working_directory: "/tmp",
    });
    expect(result.session_id).toBe("ses_xyz");
  });
});
