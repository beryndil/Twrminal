/**
 * InspectorUsage tests — verifies the four spec §10 widgets render
 * against fixture API responses: headroom chart shape, by-model
 * table, advisor effectiveness aggregate, rules-to-review list.
 *
 * Uses the component's three test seams (``fetchHistory``,
 * ``fetchByModel``, ``fetchOverrideRates``) so each test owns its
 * fixture data without spying on the global ``fetch``.
 */
import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import InspectorUsage from "../InspectorUsage.svelte";
import type { QuotaSnapshot } from "../../../api/quota";
import type { OverrideRateOut, UsageByModelRow } from "../../../api/usage";
import type { SessionOut } from "../../../api/sessions";
import { INSPECTOR_STRINGS, OVERRIDE_RATE_REVIEW_THRESHOLD } from "../../../config";

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

function snapshot(overrides: Partial<QuotaSnapshot> = {}): QuotaSnapshot {
  return {
    captured_at: 1_700_000_000,
    overall_used_pct: 0.5,
    sonnet_used_pct: 0.25,
    overall_resets_at: 1_700_604_800,
    sonnet_resets_at: 1_700_604_800,
    raw_payload: "{}",
    ...overrides,
  };
}

function modelRow(overrides: Partial<UsageByModelRow> = {}): UsageByModelRow {
  return {
    model: "sonnet",
    role: "executor",
    input_tokens: 0,
    output_tokens: 0,
    advisor_calls: 0,
    cache_read_tokens: 0,
    sessions: 0,
    ...overrides,
  };
}

function rate(overrides: Partial<OverrideRateOut> = {}): OverrideRateOut {
  return {
    rule_kind: "tag",
    rule_id: 1,
    fired_count: 10,
    overridden_count: 1,
    rate: 0.1,
    review: false,
    ...overrides,
  };
}

interface Seams {
  history: QuotaSnapshot[];
  byModel: UsageByModelRow[];
  rates: OverrideRateOut[];
}

function seams(s: Partial<Seams> = {}): {
  fetchHistory: () => Promise<QuotaSnapshot[]>;
  fetchByModel: () => Promise<UsageByModelRow[]>;
  fetchOverrideRates: () => Promise<OverrideRateOut[]>;
} {
  return {
    fetchHistory: async () => s.history ?? [],
    fetchByModel: async () => s.byModel ?? [],
    fetchOverrideRates: async () => s.rates ?? [],
  };
}

describe("InspectorUsage — loading + error branches", () => {
  it("renders the loading copy before the fetches resolve", () => {
    const pending: () => Promise<never> = () => new Promise(() => {});
    const { getByTestId } = render(InspectorUsage, {
      props: {
        session: fakeSession(),
        fetchHistory: pending,
        fetchByModel: pending,
        fetchOverrideRates: pending,
      },
    });
    expect(getByTestId("inspector-usage-loading")).toHaveTextContent(
      INSPECTOR_STRINGS.usageLoading,
    );
  });

  it("renders the error copy when any fetch rejects", async () => {
    const failing: () => Promise<never> = () => Promise.reject(new Error("boom"));
    const { findByTestId } = render(InspectorUsage, {
      props: {
        session: fakeSession(),
        fetchHistory: failing,
        fetchByModel: async () => [],
        fetchOverrideRates: async () => [],
      },
    });
    const error = await findByTestId("inspector-usage-error");
    expect(error).toHaveTextContent(INSPECTOR_STRINGS.usageError);
  });
});

describe("InspectorUsage — headroom chart", () => {
  it("renders the empty-state copy when no quota snapshots exist", async () => {
    const { findByTestId } = render(InspectorUsage, {
      props: { session: fakeSession(), ...seams() },
    });
    const empty = await findByTestId("inspector-usage-headroom-empty");
    expect(empty).toHaveTextContent(INSPECTOR_STRINGS.usageHeadroomEmpty);
  });

  it("renders the chart with one path per bucket and exposes point counts on data attrs", async () => {
    const history = [
      snapshot({ captured_at: 100, overall_used_pct: 0.1, sonnet_used_pct: 0.05 }),
      snapshot({ captured_at: 200, overall_used_pct: 0.4, sonnet_used_pct: 0.2 }),
      snapshot({ captured_at: 300, overall_used_pct: 0.7, sonnet_used_pct: 0.35 }),
    ];
    const { findByTestId } = render(InspectorUsage, {
      props: { session: fakeSession(), ...seams({ history }) },
    });
    const chart = await findByTestId("inspector-usage-headroom-chart");
    expect(chart.getAttribute("data-overall-points")).toBe("3");
    expect(chart.getAttribute("data-sonnet-points")).toBe("3");
    expect(await findByTestId("inspector-usage-headroom-overall-line")).toBeInTheDocument();
    expect(await findByTestId("inspector-usage-headroom-sonnet-line")).toBeInTheDocument();
  });

  it("plots a reset marker when the bucket reset timestamp advances", async () => {
    const history = [
      snapshot({
        captured_at: 100,
        overall_used_pct: 0.5,
        overall_resets_at: 200,
      }),
      snapshot({
        captured_at: 250,
        overall_used_pct: 0.05, // post-reset
        overall_resets_at: 800, // advanced past 200 → reset marker
      }),
      snapshot({
        captured_at: 350,
        overall_used_pct: 0.1,
        overall_resets_at: 800,
      }),
    ];
    const { findAllByTestId } = render(InspectorUsage, {
      props: { session: fakeSession(), ...seams({ history }) },
    });
    const markers = await findAllByTestId("inspector-usage-headroom-reset-marker");
    const overallMarkers = markers.filter((el) => el.getAttribute("data-bucket") === "overall");
    expect(overallMarkers.length).toBeGreaterThanOrEqual(1);
  });

  it("skips snapshots whose bucket pct is null without breaking the other series", async () => {
    const history = [
      snapshot({ captured_at: 100, overall_used_pct: 0.2, sonnet_used_pct: null }),
      snapshot({ captured_at: 200, overall_used_pct: 0.4, sonnet_used_pct: 0.1 }),
    ];
    const { findByTestId } = render(InspectorUsage, {
      props: { session: fakeSession(), ...seams({ history }) },
    });
    const chart = await findByTestId("inspector-usage-headroom-chart");
    expect(chart.getAttribute("data-overall-points")).toBe("2");
    expect(chart.getAttribute("data-sonnet-points")).toBe("1");
  });
});

describe("InspectorUsage — by-model table", () => {
  it("renders one row per model+role pair with the right token counts", async () => {
    const byModel = [
      modelRow({
        model: "sonnet",
        role: "executor",
        input_tokens: 1_000,
        output_tokens: 2_000,
        sessions: 5,
      }),
      modelRow({
        model: "opus",
        role: "advisor",
        input_tokens: 300,
        output_tokens: 400,
        advisor_calls: 7,
      }),
    ];
    const { findAllByTestId } = render(InspectorUsage, {
      props: { session: fakeSession(), ...seams({ byModel }) },
    });
    const rows = await findAllByTestId("inspector-usage-by-model-row");
    expect(rows).toHaveLength(2);
    const sonnetRow = rows.find(
      (el) =>
        el.getAttribute("data-model") === "sonnet" && el.getAttribute("data-role") === "executor",
    );
    expect(sonnetRow?.textContent).toContain("1,000");
    expect(sonnetRow?.textContent).toContain("2,000");
    const opusRow = rows.find(
      (el) =>
        el.getAttribute("data-model") === "opus" && el.getAttribute("data-role") === "advisor",
    );
    expect(opusRow?.textContent).toContain("300");
    expect(opusRow?.textContent).toContain("400");
    expect(opusRow?.textContent).toContain("7");
  });

  it("renders the empty-state copy when no model rows exist", async () => {
    const { findByTestId } = render(InspectorUsage, {
      props: { session: fakeSession(), ...seams() },
    });
    const empty = await findByTestId("inspector-usage-by-model-empty");
    expect(empty).toHaveTextContent(INSPECTOR_STRINGS.usageByModelEmpty);
  });
});

describe("InspectorUsage — advisor effectiveness", () => {
  it("renders the empty-state copy when no by-model rows exist", async () => {
    const { findByTestId } = render(InspectorUsage, {
      props: { session: fakeSession(), ...seams() },
    });
    expect(await findByTestId("inspector-usage-advisor-effectiveness-empty")).toHaveTextContent(
      INSPECTOR_STRINGS.usageAdvisorEffectivenessEmpty,
    );
  });

  it("computes calls/session and advisor share, tagged 'pulling its weight' for heavy share", async () => {
    const byModel = [
      modelRow({
        model: "sonnet",
        role: "executor",
        input_tokens: 1_000,
        output_tokens: 1_000, // 2,000 total executor
        sessions: 4,
      }),
      modelRow({
        model: "opus",
        role: "advisor",
        input_tokens: 400,
        output_tokens: 600, // 1,000 total advisor → share = 1000 / 3000 ≈ 33%
        advisor_calls: 8, // 8 / 4 sessions = 2.00
      }),
    ];
    const { findByTestId } = render(InspectorUsage, {
      props: { session: fakeSession(), ...seams({ byModel }) },
    });
    expect(
      await findByTestId("inspector-usage-advisor-effectiveness-calls-per-session"),
    ).toHaveTextContent("2.00");
    expect(await findByTestId("inspector-usage-advisor-effectiveness-share")).toHaveTextContent(
      "33%",
    );
    expect(await findByTestId("inspector-usage-advisor-effectiveness-read")).toHaveTextContent(
      INSPECTOR_STRINGS.usageAdvisorEffectivenessQualPulling,
    );
  });

  it("flags the marginal-share band when the advisor share sits between 5% and 15%", async () => {
    const byModel = [
      modelRow({
        model: "sonnet",
        role: "executor",
        input_tokens: 9_000,
        output_tokens: 0,
        sessions: 10,
      }),
      modelRow({
        model: "opus",
        role: "advisor",
        input_tokens: 800,
        output_tokens: 0, // 800 / 9800 ≈ 8.16%
        advisor_calls: 5,
      }),
    ];
    const { findByTestId } = render(InspectorUsage, {
      props: { session: fakeSession(), ...seams({ byModel }) },
    });
    expect(await findByTestId("inspector-usage-advisor-effectiveness-read")).toHaveTextContent(
      INSPECTOR_STRINGS.usageAdvisorEffectivenessQualMarginal,
    );
  });

  it("flags 'rarely consulted' when the advisor share is near zero", async () => {
    const byModel = [
      modelRow({
        model: "sonnet",
        role: "executor",
        input_tokens: 10_000,
        output_tokens: 0,
        sessions: 12,
      }),
    ];
    const { findByTestId } = render(InspectorUsage, {
      props: { session: fakeSession(), ...seams({ byModel }) },
    });
    expect(await findByTestId("inspector-usage-advisor-effectiveness-read")).toHaveTextContent(
      INSPECTOR_STRINGS.usageAdvisorEffectivenessQualUnused,
    );
  });
});

describe("InspectorUsage — rules-to-review", () => {
  it("renders the empty-state copy when no rules cross the review threshold", async () => {
    const rates = [
      rate({ rate: 0.1, review: false }),
      rate({ rule_id: 2, rate: 0.2, review: false }),
    ];
    const { findByTestId } = render(InspectorUsage, {
      props: { session: fakeSession(), ...seams({ rates }) },
    });
    const empty = await findByTestId("inspector-usage-rules-to-review-empty");
    expect(empty).toHaveTextContent(INSPECTOR_STRINGS.usageRulesToReviewEmpty);
  });

  it("highlights rules whose server-marked review flag is true", async () => {
    const rates = [
      rate({
        rule_kind: "tag",
        rule_id: 7,
        rate: 0.45,
        review: true,
        fired_count: 20,
        overridden_count: 9,
      }),
      rate({ rule_kind: "system", rule_id: 9, rate: 0.05, review: false }),
    ];
    const { findAllByTestId } = render(InspectorUsage, {
      props: { session: fakeSession(), ...seams({ rates }) },
    });
    const rows = await findAllByTestId("inspector-usage-rules-to-review-row");
    expect(rows).toHaveLength(1);
    const row = rows[0];
    expect(row.getAttribute("data-rule-kind")).toBe("tag");
    expect(row.getAttribute("data-rule-id")).toBe("7");
    expect(row.textContent).toContain("45.0%");
  });

  it("belt-and-braces filters by rate > threshold even when review flag is false", async () => {
    const rates = [
      rate({ rule_id: 1, rate: OVERRIDE_RATE_REVIEW_THRESHOLD + 0.05, review: false }),
    ];
    const { findAllByTestId } = render(InspectorUsage, {
      props: { session: fakeSession(), ...seams({ rates }) },
    });
    const rows = await findAllByTestId("inspector-usage-rules-to-review-row");
    expect(rows).toHaveLength(1);
  });
});
