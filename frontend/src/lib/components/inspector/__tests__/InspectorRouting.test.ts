/**
 * InspectorRouting tests — verifies the four spec §10 widgets render
 * against fixture messages: current-decision card, session totals,
 * quota delta, per-message timeline + "Why this model?" expandable.
 *
 * Uses the component's ``fetchMessages`` test seam to inject fixture
 * rows without spying on the global ``fetch``.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import InspectorRouting from "../InspectorRouting.svelte";
import type { MessageOut, MessagePage } from "../../../api/messages";
import type { SessionOut } from "../../../api/sessions";
import {
  INSPECTOR_STRINGS,
  ROUTING_SOURCE_QUOTA_DOWNGRADE,
  ROUTING_SOURCE_TAG_RULE,
} from "../../../config";

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

function msg(overrides: Partial<MessageOut> = {}): MessageOut {
  return {
    id: "msg_default",
    session_id: "ses_a",
    role: "assistant",
    content: "",
    created_at: "2026-01-01T00:00:00Z",
    executor_model: "sonnet",
    advisor_model: "opus",
    effort_level: "auto",
    routing_source: ROUTING_SOURCE_TAG_RULE,
    routing_reason: "matched bearings/architect",
    matched_rule_id: 42,
    executor_input_tokens: 100,
    executor_output_tokens: 200,
    advisor_input_tokens: 50,
    advisor_output_tokens: 25,
    advisor_calls_count: 1,
    cache_read_tokens: 10,
    input_tokens: null,
    output_tokens: null,
    seq: 1,
    pinned: false,
    hidden_from_context: false,
    ...overrides,
  };
}

/** Wrap rows in a full-transcript MessagePage (has_more always false). */
function fixtureFetcher(
  rows: MessageOut[],
): (sessionId: string, opts?: { signal?: AbortSignal }) => Promise<MessagePage> {
  return async (_sessionId, _opts) => ({ items: rows, has_more: false });
}

describe("InspectorRouting — loading + empty branches", () => {
  it("renders the documented loading copy before the fetch resolves", () => {
    type ResolveFn = (page: MessagePage) => void;
    let resolveFn: ResolveFn | null = null;
    const pendingFetch = (): Promise<MessagePage> =>
      new Promise<MessagePage>((resolve) => {
        resolveFn = resolve as ResolveFn;
      });
    const { getByTestId } = render(InspectorRouting, {
      props: { session: fakeSession(), fetchMessages: pendingFetch },
    });
    expect(getByTestId("inspector-routing-loading")).toHaveTextContent(
      INSPECTOR_STRINGS.routingLoading,
    );
    // Resolve so the test doesn't leak the dangling promise.
    (resolveFn as ResolveFn | null)?.({ items: [], has_more: false });
  });

  it("renders the empty-state copy when no assistant rows exist", async () => {
    const { findByTestId } = render(InspectorRouting, {
      props: { session: fakeSession(), fetchMessages: fixtureFetcher([]) },
    });
    const empty = await findByTestId("inspector-routing-empty");
    expect(empty).toHaveTextContent(INSPECTOR_STRINGS.routingEmpty);
  });

  it("filters out user / system rows lacking a routing source", async () => {
    const rows = [
      msg({ id: "u1", role: "user", executor_model: null, routing_source: null }),
      msg({ id: "a1" }),
    ];
    const { findByTestId } = render(InspectorRouting, {
      props: { session: fakeSession(), fetchMessages: fixtureFetcher(rows) },
    });
    await findByTestId("inspector-routing-current");
    const timelineRows = (await findByTestId("inspector-routing-timeline-list")).querySelectorAll(
      '[data-testid="inspector-routing-timeline-row"]',
    );
    expect(timelineRows).toHaveLength(1);
  });

  it("renders the error copy when the fetch rejects", async () => {
    const failing = (): Promise<MessagePage> => Promise.reject(new Error("boom"));
    const { findByTestId } = render(InspectorRouting, {
      props: { session: fakeSession(), fetchMessages: failing },
    });
    const error = await findByTestId("inspector-routing-error");
    expect(error).toHaveTextContent(INSPECTOR_STRINGS.routingError);
  });
});

describe("InspectorRouting — current-decision card", () => {
  it("renders the most recent routed row's executor / advisor / effort / source / reason", async () => {
    const rows = [
      msg({
        id: "a1",
        executor_model: "haiku",
        advisor_model: "opus",
        effort_level: "low",
        routing_source: ROUTING_SOURCE_TAG_RULE,
        routing_reason: "Quick lookup",
      }),
      msg({
        id: "a2",
        executor_model: "sonnet",
        advisor_model: "opus",
        effort_level: "auto",
        routing_source: ROUTING_SOURCE_QUOTA_DOWNGRADE,
        routing_reason: "Quota guard: overall 81%",
      }),
    ];
    const { findByTestId } = render(InspectorRouting, {
      props: { session: fakeSession(), fetchMessages: fixtureFetcher(rows) },
    });
    expect(await findByTestId("inspector-routing-current-executor")).toHaveTextContent(
      "Sonnet 4.6",
    );
    expect(await findByTestId("inspector-routing-current-advisor")).toHaveTextContent("Opus 4.6");
    expect(await findByTestId("inspector-routing-current-effort")).toHaveTextContent("auto");
    const source = await findByTestId("inspector-routing-current-source");
    expect(source).toHaveTextContent(
      INSPECTOR_STRINGS.routingSourceLabels[ROUTING_SOURCE_QUOTA_DOWNGRADE],
    );
    expect(source.getAttribute("data-quota-downgrade")).toBe("true");
    expect(await findByTestId("inspector-routing-current-reason")).toHaveTextContent(
      "Quota guard: overall 81%",
    );
  });

  it("renders the '(none)' label when the latest advisor is null", async () => {
    const rows = [
      msg({
        id: "a1",
        executor_model: "opus",
        advisor_model: null,
        advisor_calls_count: 0,
        effort_level: "xhigh",
      }),
    ];
    const { findByTestId } = render(InspectorRouting, {
      props: { session: fakeSession(), fetchMessages: fixtureFetcher(rows) },
    });
    expect(await findByTestId("inspector-routing-current-advisor")).toHaveTextContent(
      INSPECTOR_STRINGS.routingCurrentAdvisorNone,
    );
  });
});

describe("InspectorRouting — session totals + quota delta", () => {
  it("sums advisor calls / advisor tokens / executor tokens across routed rows", async () => {
    const rows = [
      msg({
        id: "a1",
        executor_model: "sonnet",
        executor_input_tokens: 100,
        executor_output_tokens: 200,
        advisor_input_tokens: 30,
        advisor_output_tokens: 20,
        advisor_calls_count: 2,
      }),
      msg({
        id: "a2",
        executor_model: "haiku",
        executor_input_tokens: 50,
        executor_output_tokens: 80,
        advisor_input_tokens: 10,
        advisor_output_tokens: 15,
        advisor_calls_count: 1,
      }),
    ];
    const { findByTestId } = render(InspectorRouting, {
      props: { session: fakeSession(), fetchMessages: fixtureFetcher(rows) },
    });
    expect(await findByTestId("inspector-routing-total-advisor-calls")).toHaveTextContent("3");
    // 30+20+10+15 = 75
    expect(await findByTestId("inspector-routing-total-advisor-tokens")).toHaveTextContent("75");
    // 100+200+50+80 = 430
    expect(await findByTestId("inspector-routing-total-executor-tokens")).toHaveTextContent("430");
  });

  it("computes the quota delta — overall = exec+advisor; sonnet = sonnet-executor only", async () => {
    const rows = [
      msg({
        id: "a1",
        executor_model: "sonnet",
        executor_input_tokens: 100,
        executor_output_tokens: 200, // +300 sonnet, +300 overall
        advisor_input_tokens: 50,
        advisor_output_tokens: 25, // +75 overall
        advisor_calls_count: 1,
      }),
      msg({
        id: "a2",
        executor_model: "haiku",
        executor_input_tokens: 60,
        executor_output_tokens: 40, // +100 overall, NOT sonnet
        advisor_input_tokens: 0,
        advisor_output_tokens: 0,
        advisor_calls_count: 0,
      }),
    ];
    const { findByTestId } = render(InspectorRouting, {
      props: { session: fakeSession(), fetchMessages: fixtureFetcher(rows) },
    });
    expect(await findByTestId("inspector-routing-quota-delta-overall")).toHaveTextContent("475");
    expect(await findByTestId("inspector-routing-quota-delta-sonnet")).toHaveTextContent("300");
  });

  it("treats null token columns as zero (legacy backfill defence)", async () => {
    const rows = [
      msg({
        id: "a1",
        executor_input_tokens: null,
        executor_output_tokens: null,
        advisor_input_tokens: null,
        advisor_output_tokens: null,
        advisor_calls_count: null,
      }),
    ];
    const { findByTestId } = render(InspectorRouting, {
      props: { session: fakeSession(), fetchMessages: fixtureFetcher(rows) },
    });
    expect(await findByTestId("inspector-routing-total-advisor-calls")).toHaveTextContent("0");
    expect(await findByTestId("inspector-routing-total-advisor-tokens")).toHaveTextContent("0");
    expect(await findByTestId("inspector-routing-total-executor-tokens")).toHaveTextContent("0");
  });
});

describe("InspectorRouting — per-message timeline", () => {
  it("renders one timeline row + RoutingBadge per routed message", async () => {
    const rows = [
      msg({ id: "a1", executor_model: "haiku" }),
      msg({ id: "a2", executor_model: "sonnet" }),
      msg({ id: "a3", executor_model: "opus", advisor_model: null, advisor_calls_count: 0 }),
    ];
    const { findAllByTestId } = render(InspectorRouting, {
      props: { session: fakeSession(), fetchMessages: fixtureFetcher(rows) },
    });
    const timelineRows = await findAllByTestId("inspector-routing-timeline-row");
    expect(timelineRows).toHaveLength(3);
    expect(timelineRows[0].getAttribute("data-message-id")).toBe("a1");
    const badges = await findAllByTestId("routing-badge");
    expect(badges.length).toBeGreaterThanOrEqual(3);
  });
});

describe("InspectorRouting — 'Why this model?' expandable", () => {
  it("opens the eval-chain panel for the clicked row only", async () => {
    const rows = [
      msg({ id: "a1", matched_rule_id: 10, routing_reason: "first" }),
      msg({ id: "a2", matched_rule_id: 20, routing_reason: "second" }),
    ];
    const { findAllByTestId, queryAllByTestId } = render(InspectorRouting, {
      props: { session: fakeSession(), fetchMessages: fixtureFetcher(rows) },
    });
    const toggles = await findAllByTestId("inspector-routing-why-toggle");
    expect(queryAllByTestId("inspector-routing-why-body")).toHaveLength(0);

    const firstToggle = toggles.find((el) => el.getAttribute("data-message-id") === "a1");
    expect(firstToggle).toBeDefined();
    await fireEvent.click(firstToggle!);
    await waitFor(() => {
      const bodies = queryAllByTestId("inspector-routing-why-body");
      expect(bodies).toHaveLength(1);
      expect(bodies[0].getAttribute("data-message-id")).toBe("a1");
    });
  });

  it("collapses the eval-chain panel when toggled twice", async () => {
    const rows = [msg({ id: "a1" })];
    const { findByTestId, queryByTestId } = render(InspectorRouting, {
      props: { session: fakeSession(), fetchMessages: fixtureFetcher(rows) },
    });
    const toggle = await findByTestId("inspector-routing-why-toggle");
    await fireEvent.click(toggle);
    await waitFor(() => expect(queryByTestId("inspector-routing-why-body")).not.toBeNull());
    await fireEvent.click(toggle);
    await waitFor(() => expect(queryByTestId("inspector-routing-why-body")).toBeNull());
  });

  it("renders the matched-rule id when present and the fallback copy when null", async () => {
    const rows = [msg({ id: "a1", matched_rule_id: 42 }), msg({ id: "a2", matched_rule_id: null })];
    const { findAllByTestId, getAllByTestId } = render(InspectorRouting, {
      props: { session: fakeSession(), fetchMessages: fixtureFetcher(rows) },
    });
    const toggles = await findAllByTestId("inspector-routing-why-toggle");
    for (const toggle of toggles) {
      await fireEvent.click(toggle);
    }
    const bodies = getAllByTestId("inspector-routing-why-body");
    const a1Body = bodies.find((el) => el.getAttribute("data-message-id") === "a1");
    const a2Body = bodies.find((el) => el.getAttribute("data-message-id") === "a2");
    expect(a1Body?.textContent).toContain("#42");
    expect(a2Body?.textContent).toContain(INSPECTOR_STRINGS.routingTimelineNoMatchedRule);
  });
});
