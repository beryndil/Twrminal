/**
 * InspectorAnalytics tests — covers rendering states and API call
 * shape for all three sections (A: bucket, B: redundancy, C: plug)
 * plus promote actions (Phase 6).
 *
 * Uses the component's test seams so each test owns its fixture
 * data without touching the global ``fetch``.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import InspectorAnalytics from "../InspectorAnalytics.svelte";
import type {
  BucketCurrentOut,
  PromoteToOnOpenOut,
  PromoteToTagMemoryOut,
  RedundancyBlockOut,
  SessionPlugSummaryOut,
  TagAttributionOut,
} from "../../../api/analytics";
import type { TagOut } from "../../../api/tags";
import type { SessionOut } from "../../../api/sessions";
import { INSPECTOR_STRINGS } from "../../../config";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function fakeSession(overrides: Partial<SessionOut> = {}): SessionOut {
  return {
    id: "ses_a",
    kind: "chat",
    title: "Fixture",
    description: null,
    session_instructions: null,
    working_dir: "/wd",
    model: "sonnet",
    permission_mode: null,
    max_budget_usd: null,
    total_cost_usd: 0,
    message_count: 0,
    last_context_pct: null,
    last_context_tokens: null,
    last_context_max: null,
    pinned: false,
    error_pending: false,
    checklist_item_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    last_viewed_at: null,
    last_completed_at: null,
    closed_at: null,
    closing_summary: null,
    ...overrides,
  };
}

function fakeBucket(overrides: Partial<BucketCurrentOut> = {}): BucketCurrentOut {
  return {
    five_hour: { used: 50_000, limit: 200_000, percent: 25 },
    weekly: { used: 1_000_000, limit: 5_000_000, percent: 20 },
    as_of: 1_715_000_000_000,
    ...overrides,
  };
}

function fakeAttribution(tag = "infra"): TagAttributionOut {
  return {
    tag,
    tokens_by_model: { "claude-sonnet-4-6": 50_000 },
    share_total: 0.42,
    burn_rate_per_min: 120,
  };
}

function fakeRedundancyBlock(overrides: Partial<RedundancyBlockOut> = {}): RedundancyBlockOut {
  return {
    hash: "abc123",
    block_type: "claude_md",
    token_count: 850,
    token_count_model: "claude-opus-4-7",
    repeat_count: 5,
    total_cost_tokens: 4_250,
    source_path: "~/.claude/CLAUDE.md",
    sessions: [{ id: "ses_1", title: "Session 1", timestamp: 1_700_000_000_000, tags: ["infra"] }],
    ...overrides,
  };
}

function fakePlugSummary(overrides: Partial<SessionPlugSummaryOut> = {}): SessionPlugSummaryOut {
  return {
    total_tokens: 300,
    status: "green",
    blocks: [{ hash: "h1", block_type: "claude_md", tokens: 300 }],
    ...overrides,
  };
}

function fakeTag(id: number, name: string): TagOut {
  return {
    id,
    name,
    color: null,
    default_model: null,
    working_dir: null,
    pinned: false,
    class_: "general",
    sort_order: id,
    group: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    open_session_count: 0,
    session_count: 0,
  };
}

interface SeamData {
  bucket?: BucketCurrentOut;
  attribution?: TagAttributionOut[];
  redundancy?: RedundancyBlockOut[];
  plug?: SessionPlugSummaryOut;
  tags?: TagOut[];
  promoteTagMemory?: (_hash: string, _body: unknown) => Promise<PromoteToTagMemoryOut>;
  promoteOnOpen?: (_hash: string, _body: unknown) => Promise<PromoteToOnOpenOut>;
}

function seams(data: SeamData = {}) {
  return {
    fetchBucketCurrent: async () => data.bucket ?? fakeBucket(),
    fetchAttribution: async () => data.attribution ?? [],
    fetchRedundancy: async () => data.redundancy ?? [],
    fetchPlugSummary: async () => data.plug ?? fakePlugSummary(),
    fetchTags: async () => data.tags ?? [],
    doPromoteToTagMemory:
      data.promoteTagMemory ??
      (async () => ({ memory_id: 1, tag: "infra" }) as PromoteToTagMemoryOut),
    doPromoteToOnOpen:
      data.promoteOnOpen ??
      (async () => ({ on_open_sh_path: "/tmp/.bearings/on_open.sh" }) as PromoteToOnOpenOut),
  };
}

// Seam set where all fetches stay pending forever (loading-state tests).
function pendingSeams() {
  return {
    fetchBucketCurrent: (): Promise<never> => new Promise(() => {}),
    fetchAttribution: (): Promise<never> => new Promise(() => {}),
    fetchRedundancy: (): Promise<never> => new Promise(() => {}),
    fetchPlugSummary: (): Promise<never> => new Promise(() => {}),
    fetchTags: (): Promise<never> => new Promise(() => {}),
    doPromoteToTagMemory: async () => ({ memory_id: 1, tag: "infra" }) as PromoteToTagMemoryOut,
    doPromoteToOnOpen: async () =>
      ({ on_open_sh_path: "/tmp/.bearings/on_open.sh" }) as PromoteToOnOpenOut,
  };
}

// Seam set where all fetches reject immediately (error-state tests).
function errorSeams() {
  return {
    fetchBucketCurrent: () => Promise.reject(new Error("boom")),
    fetchAttribution: () => Promise.reject(new Error("boom")),
    fetchRedundancy: () => Promise.reject(new Error("boom")),
    fetchPlugSummary: () => Promise.reject(new Error("boom")),
    fetchTags: () => Promise.reject(new Error("boom")),
    doPromoteToTagMemory: async () => ({ memory_id: 1, tag: "infra" }) as PromoteToTagMemoryOut,
    doPromoteToOnOpen: async () =>
      ({ on_open_sh_path: "/tmp/.bearings/on_open.sh" }) as PromoteToOnOpenOut,
  };
}

// ---------------------------------------------------------------------------
// Loading + error states
// ---------------------------------------------------------------------------

describe("InspectorAnalytics — loading state", () => {
  it("renders loading copy before fetches resolve", () => {
    const { getByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...pendingSeams() },
    });
    expect(getByTestId("inspector-analytics-loading")).toHaveTextContent(
      INSPECTOR_STRINGS.analyticsLoading,
    );
  });
});

describe("InspectorAnalytics — error state", () => {
  it("renders error copy when bucket fetch rejects", async () => {
    const { findByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...errorSeams() },
    });
    const err = await findByTestId("inspector-analytics-error");
    expect(err).toHaveTextContent(INSPECTOR_STRINGS.analyticsError);
  });
});

// ---------------------------------------------------------------------------
// Section A — Bucket attribution
// ---------------------------------------------------------------------------

describe("InspectorAnalytics — Section A bucket bars", () => {
  it("renders the 5h and weekly bucket bars with correct percentages", async () => {
    const bucket = fakeBucket({
      five_hour: { used: 50_000, limit: 200_000, percent: 25 },
      weekly: { used: 1_000_000, limit: 5_000_000, percent: 20 },
    });
    const { findByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ bucket }) },
    });

    const bar5h = await findByTestId("inspector-analytics-bucket-bar-5h");
    expect(bar5h.getAttribute("data-percent")).toBe("25");

    const barWeekly = await findByTestId("inspector-analytics-bucket-bar-weekly");
    expect(barWeekly.getAttribute("data-percent")).toBe("20");
  });

  it("renders no-data copy when both bucket windows are null", async () => {
    const bucket: BucketCurrentOut = { five_hour: null, weekly: null, as_of: 0 };
    const { findByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ bucket }) },
    });
    const noData = await findByTestId("inspector-analytics-bucket-no-data");
    expect(noData).toHaveTextContent(INSPECTOR_STRINGS.analyticsBucketNoData);
  });

  it("renders the attribution table with one row per tag", async () => {
    const attribution = [fakeAttribution("infra"), fakeAttribution("data")];
    const { findAllByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ attribution }) },
    });
    const rows = await findAllByTestId("inspector-analytics-attribution-row");
    expect(rows).toHaveLength(2);
    const tags = rows.map((r) => r.getAttribute("data-tag"));
    expect(tags).toContain("infra");
    expect(tags).toContain("data");
  });

  it("shows empty-state copy when attribution is empty", async () => {
    const { findByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ attribution: [] }) },
    });
    const empty = await findByTestId("inspector-analytics-attribution-empty");
    expect(empty).toHaveTextContent(INSPECTOR_STRINGS.analyticsAttributionEmpty);
  });

  it("exposes the window toggle buttons", async () => {
    const { findByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams() },
    });
    await findByTestId("inspector-analytics-bucket-toggle-5h");
    await findByTestId("inspector-analytics-bucket-toggle-weekly");
  });
});

// ---------------------------------------------------------------------------
// Section B — Redundancy
// ---------------------------------------------------------------------------

describe("InspectorAnalytics — Section B redundancy", () => {
  it("renders redundancy-loading copy before fetch resolves", () => {
    const { getByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...pendingSeams() },
    });
    expect(getByTestId("inspector-analytics-redundancy-loading")).toHaveTextContent(
      INSPECTOR_STRINGS.analyticsLoading,
    );
  });

  it("renders empty-state copy when no redundant blocks found", async () => {
    const { findByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ redundancy: [] }) },
    });
    const empty = await findByTestId("inspector-analytics-redundancy-empty");
    expect(empty).toHaveTextContent(INSPECTOR_STRINGS.analyticsRedundancyEmpty);
  });

  it("renders one list item per redundant block with correct data attrs", async () => {
    const blocks = [
      fakeRedundancyBlock({ hash: "h1", repeat_count: 5, total_cost_tokens: 4_250 }),
      fakeRedundancyBlock({ hash: "h2", repeat_count: 3, total_cost_tokens: 2_550 }),
    ];
    const { findAllByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ redundancy: blocks }) },
    });
    const items = await findAllByTestId("inspector-analytics-redundancy-block");
    expect(items).toHaveLength(2);
    expect(items[0].getAttribute("data-hash")).toBe("h1");
    expect(items[0].getAttribute("data-repeat-count")).toBe("5");
    expect(items[1].getAttribute("data-hash")).toBe("h2");
  });

  it("exposes the tag-filter select and last-N slider", async () => {
    const { findByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams() },
    });
    await findByTestId("inspector-analytics-redundancy-tag-select");
    await findByTestId("inspector-analytics-redundancy-lastn-slider");
  });

  it("populates the tag dropdown from the tags list", async () => {
    const tags = [fakeTag(1, "infra"), fakeTag(2, "data")];
    const { findByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ tags }) },
    });
    const select = await findByTestId("inspector-analytics-redundancy-tag-select");
    expect(select.textContent).toContain("infra");
    expect(select.textContent).toContain("data");
  });

  it("renders the block type chip for each redundancy block", async () => {
    const blocks = [fakeRedundancyBlock({ block_type: "claude_md" })];
    const { findByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ redundancy: blocks }) },
    });
    const chip = await findByTestId("inspector-analytics-redundancy-block-type");
    expect(chip.textContent?.trim()).toBe("CLAUDE.md");
  });
});

// ---------------------------------------------------------------------------
// Section C — Active session plug
// ---------------------------------------------------------------------------

describe("InspectorAnalytics — Section C session plug", () => {
  it("renders no-session copy when session is null", () => {
    const { getByTestId } = render(InspectorAnalytics, {
      props: { session: null, ...seams() },
    });
    expect(getByTestId("inspector-analytics-plug-no-session")).toHaveTextContent(
      INSPECTOR_STRINGS.analyticsPlugNoSession,
    );
  });

  it("renders the plug summary with total tokens and status", async () => {
    const plug: SessionPlugSummaryOut = {
      total_tokens: 1820,
      status: "red",
      blocks: [{ hash: "h1", block_type: "claude_md", tokens: 1820 }],
    };
    const { findByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ plug }) },
    });
    const summary = await findByTestId("inspector-analytics-plug-summary");
    expect(summary.getAttribute("data-status")).toBe("red");
    expect(summary.getAttribute("data-total-tokens")).toBe("1820");
  });

  it("renders green status when total tokens is below the yellow threshold", async () => {
    const plug: SessionPlugSummaryOut = {
      total_tokens: 200,
      status: "green",
      blocks: [],
    };
    const { findByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ plug }) },
    });
    const status = await findByTestId("inspector-analytics-plug-status");
    expect(status.textContent?.trim()).toBe("green");
  });

  it("renders no-data copy when plug summary has no blocks and status is green", async () => {
    const plug: SessionPlugSummaryOut = { total_tokens: 0, status: "green", blocks: [] };
    const { findByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ plug }) },
    });
    // The summary section still renders, but the table is empty.
    await findByTestId("inspector-analytics-plug-summary");
    // No block rows rendered.
    const { queryAllByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ plug }) },
    });
    await new Promise((r) => setTimeout(r, 0));
    expect(queryAllByTestId("inspector-analytics-plug-block-row")).toHaveLength(0);
  });

  it("renders one block row per plug block with type and token count", async () => {
    const plug: SessionPlugSummaryOut = {
      total_tokens: 1_100,
      status: "yellow",
      blocks: [
        { hash: "h1", block_type: "claude_md", tokens: 850 },
        { hash: "h2", block_type: "tag_memory", tokens: 250 },
      ],
    };
    const { findAllByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ plug }) },
    });
    const rows = await findAllByTestId("inspector-analytics-plug-block-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].getAttribute("data-block-type")).toBe("claude_md");
    expect(rows[1].getAttribute("data-block-type")).toBe("tag_memory");
  });

  it("renders a promote button for each plug block row", async () => {
    const plug: SessionPlugSummaryOut = {
      total_tokens: 500,
      status: "yellow",
      blocks: [{ hash: "h1", block_type: "claude_md", tokens: 500 }],
    };
    const { findAllByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ plug }) },
    });
    const btns = await findAllByTestId("inspector-analytics-plug-block-promote");
    expect(btns).toHaveLength(1);
    expect(btns[0].textContent?.trim()).toBe(INSPECTOR_STRINGS.analyticsPromoteBtn);
  });
});

// ---------------------------------------------------------------------------
// Section B — Promote actions (Phase 6)
// ---------------------------------------------------------------------------

describe("InspectorAnalytics — Section B promote buttons", () => {
  it("shows promote buttons in the expanded detail of a redundancy block", async () => {
    const blocks = [fakeRedundancyBlock({ hash: "hx" })];
    const { findByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ redundancy: blocks }) },
    });
    // Expand the block first.
    const expandBtn = await findByTestId("inspector-analytics-redundancy-block-expand");
    fireEvent.click(expandBtn);
    // Promote buttons should now be visible.
    await findByTestId("inspector-analytics-redundancy-promote-actions");
    await findByTestId("inspector-analytics-redundancy-promote-tag-memory");
    await findByTestId("inspector-analytics-redundancy-promote-on-open");
  });

  it("opens the tag-memory modal when the promote-to-tag-memory button is clicked", async () => {
    const blocks = [fakeRedundancyBlock({ hash: "hx" })];
    const { findByTestId, queryByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ redundancy: blocks }) },
    });
    const expandBtn = await findByTestId("inspector-analytics-redundancy-block-expand");
    fireEvent.click(expandBtn);
    const promoteBtn = await findByTestId("inspector-analytics-redundancy-promote-tag-memory");
    fireEvent.click(promoteBtn);
    await findByTestId("inspector-analytics-promote-tag-memory-modal");
    expect(queryByTestId("inspector-analytics-promote-on-open-modal")).toBeNull();
  });

  it("opens the on_open modal when the promote-to-on-open button is clicked", async () => {
    const blocks = [fakeRedundancyBlock({ hash: "hx" })];
    const { findByTestId, queryByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ redundancy: blocks }) },
    });
    const expandBtn = await findByTestId("inspector-analytics-redundancy-block-expand");
    fireEvent.click(expandBtn);
    const promoteBtn = await findByTestId("inspector-analytics-redundancy-promote-on-open");
    fireEvent.click(promoteBtn);
    await findByTestId("inspector-analytics-promote-on-open-modal");
    expect(queryByTestId("inspector-analytics-promote-tag-memory-modal")).toBeNull();
  });

  it("calls the doPromoteToTagMemory seam on save and shows success message", async () => {
    const spy = vi.fn().mockResolvedValue({ memory_id: 7, tag: "infra" });
    const blocks = [fakeRedundancyBlock({ hash: "hx" })];
    const { findByTestId } = render(InspectorAnalytics, {
      props: {
        session: fakeSession(),
        ...seams({ redundancy: blocks, promoteTagMemory: spy }),
      },
    });
    fireEvent.click(await findByTestId("inspector-analytics-redundancy-block-expand"));
    fireEvent.click(await findByTestId("inspector-analytics-redundancy-promote-tag-memory"));

    const tagInput = await findByTestId("inspector-analytics-promote-tag-input");
    fireEvent.input(tagInput, { target: { value: "infra" } });

    const saveBtn = await findByTestId("inspector-analytics-promote-save");
    fireEvent.click(saveBtn);

    await waitFor(() => expect(spy).toHaveBeenCalledOnce());
    const status = await findByTestId("inspector-analytics-promote-status");
    expect(status.textContent).toContain(INSPECTOR_STRINGS.analyticsPromoteTagMemorySuccess);
  });

  it("calls the doPromoteToOnOpen seam on save and shows success message", async () => {
    const spy = vi.fn().mockResolvedValue({ on_open_sh_path: "/p/.bearings/on_open.sh" });
    const blocks = [fakeRedundancyBlock({ hash: "hx" })];
    const { findByTestId } = render(InspectorAnalytics, {
      props: {
        session: fakeSession(),
        ...seams({ redundancy: blocks, promoteOnOpen: spy }),
      },
    });
    fireEvent.click(await findByTestId("inspector-analytics-redundancy-block-expand"));
    fireEvent.click(await findByTestId("inspector-analytics-redundancy-promote-on-open"));

    const wdInput = await findByTestId("inspector-analytics-promote-workdir-input");
    fireEvent.input(wdInput, { target: { value: "/tmp/proj" } });

    const saveBtn = await findByTestId("inspector-analytics-promote-save");
    fireEvent.click(saveBtn);

    await waitFor(() => expect(spy).toHaveBeenCalledOnce());
    const status = await findByTestId("inspector-analytics-promote-status");
    expect(status.textContent).toContain(INSPECTOR_STRINGS.analyticsPromoteOnOpenSuccess);
  });

  it("closes the modal when cancel is clicked", async () => {
    const blocks = [fakeRedundancyBlock({ hash: "hx" })];
    const { findByTestId, queryByTestId } = render(InspectorAnalytics, {
      props: { session: fakeSession(), ...seams({ redundancy: blocks }) },
    });
    fireEvent.click(await findByTestId("inspector-analytics-redundancy-block-expand"));
    fireEvent.click(await findByTestId("inspector-analytics-redundancy-promote-tag-memory"));
    await findByTestId("inspector-analytics-promote-tag-memory-modal");

    const cancelBtn = await findByTestId("inspector-analytics-promote-cancel");
    fireEvent.click(cancelBtn);
    expect(queryByTestId("inspector-analytics-promote-tag-memory-modal")).toBeNull();
  });
});
