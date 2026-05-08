/**
 * Integration tests for ``NewSessionForm`` (item 2.4 / spec §6).
 *
 * Coverage:
 *
 * * two-axis selector state — executor / advisor / advisor max /
 *   effort dropdowns render with the spec §3 alphabet, manual changes
 *   flip the "routed-from" line to "Manual override";
 * * debounced preview call — typing the first message → wait
 *   :data:`ROUTING_PREVIEW_DEBOUNCE_MS` (300 ms) → exactly one POST
 *   to ``/api/routing/preview`` with the matching body. Tests use
 *   vitest fake timers so the assertion holds regardless of host
 *   scheduler;
 * * Opus-executor advisor row collapse (spec §2);
 * * downgrade banner conditional — appears only when the preview
 *   reports ``quota_downgrade_applied`` AND the user has not already
 *   overridden;
 * * "Use anyway" override path — clicking the override restores the
 *   original executor and switches the routed-from line to "Manual
 *   override".
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  EXECUTOR_MODEL_OPUS,
  EXECUTOR_MODEL_SONNET,
  ROUTING_PREVIEW_DEBOUNCE_MS,
  ROUTING_SOURCE_QUOTA_DOWNGRADE,
  ROUTING_SOURCE_TAG_RULE,
  SESSION_KIND_CHAT,
  SESSION_KIND_CHECKLIST,
} from "../../../config";
import type { RoutingPreview } from "../../../api/routing";
import type { QuotaSnapshot } from "../../../api/quota";
import NewSessionForm from "../NewSessionForm.svelte";

function makePreview(overrides: Partial<RoutingPreview> = {}): RoutingPreview {
  return {
    executor: "sonnet",
    advisor: "opus",
    advisor_max_uses: 5,
    effort: "auto",
    source: ROUTING_SOURCE_TAG_RULE,
    reason: "Workhorse default",
    matched_rule_id: 1,
    evaluated_rules: [1],
    quota_downgrade_applied: false,
    quota_state: { overall_used_pct: 0.42, sonnet_used_pct: 0.18 },
    ...overrides,
  };
}

function makeQuotaSnapshot(overrides: Partial<QuotaSnapshot> = {}): QuotaSnapshot {
  return {
    captured_at: 1_700_000_000,
    overall_used_pct: 0.42,
    sonnet_used_pct: 0.18,
    overall_resets_at: null,
    sonnet_resets_at: null,
    raw_payload: "{}",
    ...overrides,
  };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("NewSessionForm — selector state", () => {
  it("renders the two-axis selector with the spec §3 alphabet", () => {
    const previewRouting = vi.fn().mockResolvedValue(makePreview());
    const getCurrentQuota = vi.fn().mockResolvedValue(makeQuotaSnapshot());
    const { getByTestId } = render(NewSessionForm, {
      props: {
        tagIds: [1],
        previewRouting,
        getCurrentQuota,
      },
    });
    const executor = getByTestId("new-session-executor") as HTMLSelectElement;
    const advisor = getByTestId("new-session-advisor") as HTMLSelectElement;
    const effort = getByTestId("new-session-effort") as HTMLSelectElement;
    expect(Array.from(executor.options).map((o) => o.value)).toEqual([
      "sonnet",
      "haiku",
      "opus",
      "opusplan",
    ]);
    expect(Array.from(advisor.options).map((o) => o.value)).toEqual(["", "opus"]);
    expect(Array.from(effort.options).map((o) => o.value)).toEqual([
      "auto",
      "low",
      "medium",
      "high",
      "xhigh",
    ]);
  });

  it("collapses the advisor row to the hint when executor=opus (spec §2)", async () => {
    const previewRouting = vi.fn().mockResolvedValue(makePreview());
    const getCurrentQuota = vi.fn().mockResolvedValue(makeQuotaSnapshot());
    const { getByTestId, queryByTestId } = render(NewSessionForm, {
      props: { tagIds: [], previewRouting, getCurrentQuota },
    });
    const executor = getByTestId("new-session-executor") as HTMLSelectElement;
    await fireEvent.change(executor, { target: { value: EXECUTOR_MODEL_OPUS } });
    expect(getByTestId("new-session-advisor-hint")).toBeInTheDocument();
    expect(queryByTestId("new-session-advisor")).toBeNull();
  });

  it("flips the routed-from line to 'Manual override' once the user touches a selector (spec §6)", async () => {
    const previewRouting = vi.fn().mockResolvedValue(makePreview());
    const getCurrentQuota = vi.fn().mockResolvedValue(makeQuotaSnapshot());
    const { getByTestId } = render(NewSessionForm, {
      props: { tagIds: [], previewRouting, getCurrentQuota },
    });
    await vi.advanceTimersByTimeAsync(ROUTING_PREVIEW_DEBOUNCE_MS);
    await waitFor(() => {
      expect(getByTestId("routing-preview")).toHaveAttribute("data-kind", "ready");
    });
    const executor = getByTestId("new-session-executor") as HTMLSelectElement;
    await fireEvent.change(executor, { target: { value: "haiku" } });
    expect(getByTestId("routing-preview")).toHaveAttribute("data-kind", "manual");
  });
});

describe("NewSessionForm — debounced preview", () => {
  it("waits 300ms after the last keystroke before issuing exactly one preview POST", async () => {
    const previewRouting = vi.fn().mockResolvedValue(makePreview());
    const getCurrentQuota = vi.fn().mockResolvedValue(makeQuotaSnapshot());
    const { getByTestId } = render(NewSessionForm, {
      props: { tagIds: [1, 2], previewRouting, getCurrentQuota },
    });
    // Mount-time tag-driven preview fires immediately on $effect; let
    // it settle so the tests below count only message-driven calls.
    await vi.advanceTimersByTimeAsync(ROUTING_PREVIEW_DEBOUNCE_MS);
    previewRouting.mockClear();

    const textarea = getByTestId("new-session-first-message") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "p" } });
    await vi.advanceTimersByTimeAsync(100);
    await fireEvent.input(textarea, { target: { value: "pl" } });
    await vi.advanceTimersByTimeAsync(100);
    await fireEvent.input(textarea, { target: { value: "pla" } });
    await vi.advanceTimersByTimeAsync(100);
    await fireEvent.input(textarea, { target: { value: "plan" } });
    // Still inside the debounce window — no call yet.
    expect(previewRouting).toHaveBeenCalledTimes(0);
    await vi.advanceTimersByTimeAsync(ROUTING_PREVIEW_DEBOUNCE_MS);

    expect(previewRouting).toHaveBeenCalledTimes(1);
    const [body] = previewRouting.mock.calls[0];
    expect(body).toEqual({ tags: [1, 2], message: "plan" });
  });

  it("renders the failure copy when the preview fetch raises", async () => {
    const previewRouting = vi.fn().mockRejectedValue(new Error("boom"));
    const getCurrentQuota = vi.fn().mockResolvedValue(makeQuotaSnapshot());
    const { getByTestId } = render(NewSessionForm, {
      props: { tagIds: [], previewRouting, getCurrentQuota },
    });
    await vi.advanceTimersByTimeAsync(ROUTING_PREVIEW_DEBOUNCE_MS);
    await waitFor(() => {
      expect(getByTestId("routing-preview")).toHaveAttribute("data-kind", "error");
    });
  });
});

describe("NewSessionForm — downgrade banner + 'Use anyway' override", () => {
  it("renders the downgrade banner when the preview reports a quota downgrade", async () => {
    const previewRouting = vi.fn().mockResolvedValue(
      makePreview({
        executor: "sonnet",
        source: ROUTING_SOURCE_QUOTA_DOWNGRADE,
        quota_downgrade_applied: true,
        quota_state: { overall_used_pct: 0.82, sonnet_used_pct: 0.4 },
      }),
    );
    const getCurrentQuota = vi.fn().mockResolvedValue(makeQuotaSnapshot());
    const { getByTestId } = render(NewSessionForm, {
      props: { tagIds: [], previewRouting, getCurrentQuota },
    });
    await vi.advanceTimersByTimeAsync(ROUTING_PREVIEW_DEBOUNCE_MS);
    await waitFor(() => {
      expect(getByTestId("recost-dialog")).toBeInTheDocument();
    });
    expect(getByTestId("recost-dialog-copy").textContent ?? "").toContain(
      "Routing downgraded to Sonnet",
    );
    expect(getByTestId("recost-dialog-copy").textContent ?? "").toContain("(overall quota at 82%)");
  });

  it("hides the banner once the user clicks 'Use Opus anyway' and restores the executor", async () => {
    const previewRouting = vi.fn().mockResolvedValue(
      makePreview({
        executor: "sonnet",
        source: ROUTING_SOURCE_QUOTA_DOWNGRADE,
        quota_downgrade_applied: true,
        quota_state: { overall_used_pct: 0.82, sonnet_used_pct: 0.4 },
      }),
    );
    const getCurrentQuota = vi.fn().mockResolvedValue(makeQuotaSnapshot());
    const { getByTestId, queryByTestId } = render(NewSessionForm, {
      props: { tagIds: [], previewRouting, getCurrentQuota },
    });
    await vi.advanceTimersByTimeAsync(ROUTING_PREVIEW_DEBOUNCE_MS);
    await waitFor(() => {
      expect(getByTestId("recost-dialog")).toBeInTheDocument();
    });
    await fireEvent.click(getByTestId("recost-dialog-use-anyway"));
    expect(queryByTestId("recost-dialog")).toBeNull();
    expect((getByTestId("new-session-executor") as HTMLSelectElement).value).toBe(
      EXECUTOR_MODEL_OPUS,
    );
    // Spec §6 — once the user has overridden, the routed-from line
    // reads "Manual override" and stays that way.
    expect(getByTestId("routing-preview")).toHaveAttribute("data-kind", "manual");
  });

  it("does NOT render the banner on a normal tag-rule preview", async () => {
    const previewRouting = vi.fn().mockResolvedValue(makePreview());
    const getCurrentQuota = vi.fn().mockResolvedValue(makeQuotaSnapshot());
    const { queryByTestId } = render(NewSessionForm, {
      props: { tagIds: [], previewRouting, getCurrentQuota },
    });
    await vi.advanceTimersByTimeAsync(ROUTING_PREVIEW_DEBOUNCE_MS);
    expect(queryByTestId("recost-dialog")).toBeNull();
  });
});

describe("NewSessionForm — submission", () => {
  it("calls onSubmit with the routing payload when Start Session is pressed", async () => {
    const previewRouting = vi.fn().mockResolvedValue(makePreview());
    const getCurrentQuota = vi.fn().mockResolvedValue(makeQuotaSnapshot());
    const onSubmit = vi.fn();
    const { getByTestId } = render(NewSessionForm, {
      props: {
        tagIds: [3],
        workingDir: "/wd",
        previewRouting,
        getCurrentQuota,
        onSubmit,
      },
    });
    await vi.advanceTimersByTimeAsync(ROUTING_PREVIEW_DEBOUNCE_MS);
    const textarea = getByTestId("new-session-first-message") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "build the thing" } });
    await vi.advanceTimersByTimeAsync(ROUTING_PREVIEW_DEBOUNCE_MS);
    await fireEvent.click(getByTestId("new-session-submit"));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.tagIds).toEqual([3]);
    expect(payload.workingDir).toBe("/wd");
    expect(payload.firstMessage).toBe("build the thing");
    expect(payload.routing.executor).toBe(EXECUTOR_MODEL_SONNET);
    expect(payload.routing.override).toBe(false);
  });
});

describe("NewSessionForm — kind toggle (gap-cycle-10-002)", () => {
  it("renders both Chat and Checklist kind buttons", () => {
    const previewRouting = vi.fn().mockResolvedValue(makePreview());
    const getCurrentQuota = vi.fn().mockResolvedValue(makeQuotaSnapshot());
    const { getByTestId } = render(NewSessionForm, {
      props: { tagIds: [], previewRouting, getCurrentQuota },
    });
    expect(getByTestId("new-session-kind-chat")).toBeInTheDocument();
    expect(getByTestId("new-session-kind-checklist")).toBeInTheDocument();
  });

  it("hides routing axes, first-message textarea, and RoutingPreview when Checklist is selected", async () => {
    const previewRouting = vi.fn().mockResolvedValue(makePreview());
    const getCurrentQuota = vi.fn().mockResolvedValue(makeQuotaSnapshot());
    const { getByTestId, queryByTestId } = render(NewSessionForm, {
      props: { tagIds: [], previewRouting, getCurrentQuota },
    });
    // Verify chat fields are present initially.
    expect(getByTestId("new-session-executor")).toBeInTheDocument();
    expect(getByTestId("new-session-first-message")).toBeInTheDocument();
    // Switch to Checklist.
    await fireEvent.click(getByTestId("new-session-kind-checklist"));
    expect(queryByTestId("new-session-executor")).toBeNull();
    expect(queryByTestId("new-session-advisor")).toBeNull();
    expect(queryByTestId("new-session-effort")).toBeNull();
    expect(queryByTestId("new-session-first-message")).toBeNull();
    expect(queryByTestId("routing-preview")).toBeNull();
  });

  it("submit payload includes kind: chat when Chat is selected (default)", async () => {
    const previewRouting = vi.fn().mockResolvedValue(makePreview());
    const getCurrentQuota = vi.fn().mockResolvedValue(makeQuotaSnapshot());
    const onSubmit = vi.fn();
    const { getByTestId } = render(NewSessionForm, {
      props: { tagIds: [1], workingDir: "/wd", previewRouting, getCurrentQuota, onSubmit },
    });
    await vi.advanceTimersByTimeAsync(ROUTING_PREVIEW_DEBOUNCE_MS);
    await fireEvent.input(getByTestId("new-session-first-message") as HTMLTextAreaElement, {
      target: { value: "hello" },
    });
    await fireEvent.click(getByTestId("new-session-submit"));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0].kind).toBe(SESSION_KIND_CHAT);
  });

  it("submit payload includes kind: checklist when Checklist is selected", async () => {
    const previewRouting = vi.fn().mockResolvedValue(makePreview());
    const getCurrentQuota = vi.fn().mockResolvedValue(makeQuotaSnapshot());
    const onSubmit = vi.fn();
    const { getByTestId } = render(NewSessionForm, {
      props: { tagIds: [1], workingDir: "/wd", previewRouting, getCurrentQuota, onSubmit },
    });
    await fireEvent.click(getByTestId("new-session-kind-checklist"));
    await fireEvent.click(getByTestId("new-session-submit"));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0].kind).toBe(SESSION_KIND_CHECKLIST);
  });
});
