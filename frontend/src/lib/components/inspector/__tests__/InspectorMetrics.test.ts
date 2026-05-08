/**
 * InspectorMetrics tests — verifies the two cards (token totals and
 * tool-call counters), formatting, colour-class flips, elapsed sum,
 * and empty states.
 *
 * Uses the component's test-seam props so each test owns its fixture
 * data without touching the module-singleton conversation store.
 */
import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import InspectorMetrics from "../InspectorMetrics.svelte";
import { INSPECTOR_STRINGS } from "../../../config";
import type { MessageTurnView, ToolCallView } from "../../../stores/conversation.svelte";
import type { SessionOut } from "../../../api/sessions";

// ---------------------------------------------------------------------------
// Helpers
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

function fakeTurn(overrides: Partial<MessageTurnView> = {}): MessageTurnView {
  return {
    id: "t1",
    role: "assistant",
    body: "",
    thinking: "",
    complete: true,
    toolCalls: [],
    routing: null,
    error: null,
    createdAt: "2026-01-01T12:00:00Z",
    resumed: false,
    seq: 1,
    attachments: [],
    ...overrides,
  };
}

function fakeToolCall(overrides: Partial<ToolCallView> = {}): ToolCallView {
  return {
    id: "tc1",
    name: "Read",
    inputJson: "{}",
    output: "",
    rawLength: 0,
    done: true,
    ok: true,
    durationMs: 100,
    errorMessage: null,
    liveElapsedMs: 0,
    startedAt: 0,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Token totals — cell values
// ---------------------------------------------------------------------------

describe("InspectorMetrics — token totals cells", () => {
  it("renders the four token-total cells with the correct values", () => {
    const { getByTestId } = render(InspectorMetrics, {
      props: {
        session: fakeSession(),
        turns: [],
        inputTokens: 1_234,
        outputTokens: 567,
        cacheReadTokens: 890,
        cacheWriteTokens: 200,
      },
    });

    // Input: 1234 → "1.2k"
    expect(getByTestId("inspector-metrics-token-input")).toHaveTextContent("1.2k");
    // Output: 567 → "567"
    expect(getByTestId("inspector-metrics-token-output")).toHaveTextContent("567");
    // Cache read: 890 → "890"
    expect(getByTestId("inspector-metrics-token-cache-read")).toHaveTextContent("890");
    // Cache write: 200 → "200"
    expect(getByTestId("inspector-metrics-token-cache-write")).toHaveTextContent("200");
  });

  it("formats large token counts with M suffix", () => {
    const { getByTestId } = render(InspectorMetrics, {
      props: {
        session: fakeSession(),
        turns: [],
        inputTokens: 3_400_000,
        outputTokens: 0,
        cacheReadTokens: 0,
        cacheWriteTokens: 0,
      },
    });
    expect(getByTestId("inspector-metrics-token-input")).toHaveTextContent("3.4M");
  });

  it("renders — for cache-write when cacheWriteTokens is null", () => {
    const { getByTestId } = render(InspectorMetrics, {
      props: {
        session: fakeSession(),
        turns: [],
        inputTokens: 0,
        outputTokens: 0,
        cacheReadTokens: 0,
        cacheWriteTokens: null,
      },
    });
    expect(getByTestId("inspector-metrics-token-cache-write")).toHaveTextContent(
      INSPECTOR_STRINGS.metricsTokenCacheWriteUnavailable,
    );
  });

  it("renders — for cache-write when cacheWriteTokens is undefined (production default)", () => {
    const { getByTestId } = render(InspectorMetrics, {
      props: {
        session: fakeSession(),
        turns: [],
        inputTokens: 0,
        outputTokens: 0,
        cacheReadTokens: 0,
        // cacheWriteTokens not passed → undefined
      },
    });
    expect(getByTestId("inspector-metrics-token-cache-write")).toHaveTextContent(
      INSPECTOR_STRINGS.metricsTokenCacheWriteUnavailable,
    );
  });
});

// ---------------------------------------------------------------------------
// Token totals — colour classes
// ---------------------------------------------------------------------------

describe("InspectorMetrics — cache-read colour class", () => {
  it("applies emerald accent to the cache-read cell", () => {
    const { getByTestId } = render(InspectorMetrics, {
      props: {
        session: fakeSession(),
        turns: [],
        inputTokens: 0,
        outputTokens: 0,
        cacheReadTokens: 0,
      },
    });
    expect(getByTestId("inspector-metrics-token-cache-read")).toHaveClass("text-emerald-400");
  });
});

// ---------------------------------------------------------------------------
// Tool calls — counters
// ---------------------------------------------------------------------------

describe("InspectorMetrics — tool-call counters", () => {
  it("counts total / running / failed correctly", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          // done + ok
          fakeToolCall({ id: "tc1", done: true, ok: true, durationMs: 50 }),
          // in-flight
          fakeToolCall({ id: "tc2", done: false, ok: null, durationMs: null }),
          // done + failed
          fakeToolCall({ id: "tc3", done: true, ok: false, durationMs: 80 }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorMetrics, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-metrics-tool-total")).toHaveTextContent("3");
    expect(getByTestId("inspector-metrics-tool-running")).toHaveTextContent("1");
    expect(getByTestId("inspector-metrics-tool-failed")).toHaveTextContent("1");
  });

  it("renders 0 for running when no calls are in flight", () => {
    const turns = [
      fakeTurn({
        toolCalls: [fakeToolCall({ id: "tc1", done: true, ok: true, durationMs: 10 })],
      }),
    ];
    const { getByTestId } = render(InspectorMetrics, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-metrics-tool-running")).toHaveTextContent("0");
  });
});

// ---------------------------------------------------------------------------
// Tool calls — running colour class (amber at > 0, muted at 0)
// ---------------------------------------------------------------------------

describe("InspectorMetrics — running-count colour class", () => {
  it("applies amber colour when running > 0", () => {
    const turns = [
      fakeTurn({
        toolCalls: [fakeToolCall({ id: "tc1", done: false, ok: null, durationMs: null })],
      }),
    ];
    const { getByTestId } = render(InspectorMetrics, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-metrics-tool-running")).toHaveClass("text-amber-400");
    expect(getByTestId("inspector-metrics-tool-running")).not.toHaveClass("text-fg-muted");
  });

  it("applies muted colour when running === 0", () => {
    const { getByTestId } = render(InspectorMetrics, {
      props: { session: fakeSession(), turns: [] },
    });
    expect(getByTestId("inspector-metrics-tool-running")).toHaveClass("text-fg-muted");
    expect(getByTestId("inspector-metrics-tool-running")).not.toHaveClass("text-amber-400");
  });
});

// ---------------------------------------------------------------------------
// Tool calls — failed colour class (rose at > 0, muted at 0)
// ---------------------------------------------------------------------------

describe("InspectorMetrics — failed-count colour class", () => {
  it("applies rose colour when failed > 0", () => {
    const turns = [
      fakeTurn({
        toolCalls: [fakeToolCall({ id: "tc1", done: true, ok: false, durationMs: 10 })],
      }),
    ];
    const { getByTestId } = render(InspectorMetrics, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-metrics-tool-failed")).toHaveClass("text-rose-400");
    expect(getByTestId("inspector-metrics-tool-failed")).not.toHaveClass("text-fg-muted");
  });

  it("applies muted colour when failed === 0", () => {
    const turns = [
      fakeTurn({
        toolCalls: [fakeToolCall({ id: "tc1", done: true, ok: true, durationMs: 20 })],
      }),
    ];
    const { getByTestId } = render(InspectorMetrics, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-metrics-tool-failed")).toHaveClass("text-fg-muted");
    expect(getByTestId("inspector-metrics-tool-failed")).not.toHaveClass("text-rose-400");
  });
});

// ---------------------------------------------------------------------------
// Tool calls — total elapsed (finished calls only)
// ---------------------------------------------------------------------------

describe("InspectorMetrics — total elapsed", () => {
  it("sums durationMs over finished calls only", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          // finished: 500ms
          fakeToolCall({ id: "tc1", done: true, ok: true, durationMs: 500 }),
          // finished: 300ms
          fakeToolCall({ id: "tc2", done: true, ok: false, durationMs: 300 }),
          // in-flight: must NOT be counted
          fakeToolCall({ id: "tc3", done: false, ok: null, durationMs: null }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorMetrics, {
      props: { session: fakeSession(), turns },
    });
    // 500 + 300 = 800ms → "800ms"
    expect(getByTestId("inspector-metrics-tool-elapsed")).toHaveTextContent("800ms");
  });

  it("renders — when no tool calls have run at all", () => {
    const { getByTestId } = render(InspectorMetrics, {
      props: { session: fakeSession(), turns: [] },
    });
    expect(getByTestId("inspector-metrics-tool-elapsed")).toHaveTextContent(
      INSPECTOR_STRINGS.metricsToolCallsElapsedEmpty,
    );
  });

  it("renders — when all calls are still in flight (none finished)", () => {
    const turns = [
      fakeTurn({
        toolCalls: [fakeToolCall({ id: "tc1", done: false, ok: null, durationMs: null })],
      }),
    ];
    const { getByTestId } = render(InspectorMetrics, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-metrics-tool-elapsed")).toHaveTextContent(
      INSPECTOR_STRINGS.metricsToolCallsElapsedEmpty,
    );
  });

  it("formats elapsed ≥ 1s in seconds with one decimal", () => {
    const turns = [
      fakeTurn({
        toolCalls: [fakeToolCall({ id: "tc1", done: true, ok: true, durationMs: 2_500 })],
      }),
    ];
    const { getByTestId } = render(InspectorMetrics, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-metrics-tool-elapsed")).toHaveTextContent("2.5s");
  });

  it("formats elapsed ≥ 1 minute in Nm Ns form", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          // 1 min 30 s = 90 000 ms
          fakeToolCall({ id: "tc1", done: true, ok: true, durationMs: 90_000 }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorMetrics, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-metrics-tool-elapsed")).toHaveTextContent("1m 30s");
  });
});

// ---------------------------------------------------------------------------
// Empty state — both cards with zero data
// ---------------------------------------------------------------------------

describe("InspectorMetrics — empty state", () => {
  it("renders both cards even with all-zero data", () => {
    const { getByTestId } = render(InspectorMetrics, {
      props: {
        session: fakeSession(),
        turns: [],
        inputTokens: 0,
        outputTokens: 0,
        cacheReadTokens: 0,
      },
    });
    expect(getByTestId("inspector-metrics-token-totals")).toBeInTheDocument();
    expect(getByTestId("inspector-metrics-tool-calls")).toBeInTheDocument();
    expect(getByTestId("inspector-metrics-token-input")).toHaveTextContent("0");
    expect(getByTestId("inspector-metrics-tool-total")).toHaveTextContent("0");
  });
});
