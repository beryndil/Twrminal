/**
 * Route-level tests for ``/sessions/new`` (gap-cycle-10-002).
 *
 * Coverage:
 *
 * * route-after-create (checklist): submitting a checklist session
 *   calls ``createSession`` with ``kind: 'checklist'``, skips
 *   ``sendPrompt``, and navigates to ``/sessions/{id}`` via ``goto``.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---- SvelteKit shims (must be declared before importing any module that
//      imports them) ----------------------------------------------------------

vi.mock("$app/navigation", () => ({
  goto: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("$app/state", () => ({
  page: { url: { searchParams: { get: () => null } } },
}));

// ---- API mocks --------------------------------------------------------------

vi.mock("../../../../lib/api/sessions", () => ({
  createSession: vi.fn(),
  getMostRecentSession: vi.fn().mockResolvedValue(null),
}));
vi.mock("../../../../lib/api/tags", () => ({
  listTags: vi.fn(),
}));
vi.mock("../../../../lib/api/prompt", () => ({
  sendPrompt: vi.fn(),
}));
vi.mock("../../../../lib/api/preferences", () => ({
  getPreferences: vi.fn().mockResolvedValue({
    default_working_dir: null,
    default_model: null,
  }),
}));
vi.mock("../../../../lib/api/routing", () => ({
  previewRouting: vi.fn().mockResolvedValue({
    executor: "sonnet",
    advisor: "opus",
    advisor_max_uses: 5,
    effort: "auto",
    source: "tag_rule",
    reason: "default",
    matched_rule_id: null,
    evaluated_rules: [],
    quota_downgrade_applied: false,
    quota_state: { overall_used_pct: 0, sonnet_used_pct: 0 },
  }),
}));
vi.mock("../../../../lib/api/quota", () => ({
  getCurrentQuota: vi.fn().mockResolvedValue({
    captured_at: 0,
    overall_used_pct: 0,
    sonnet_used_pct: 0,
    overall_resets_at: null,
    sonnet_resets_at: null,
    raw_payload: "{}",
  }),
}));
vi.mock("../../../../lib/api/templates", () => ({
  listTemplates: vi.fn().mockResolvedValue([]),
}));

// ---- Stub heavy child components that pull in stores / WS infra -------------

/* eslint-disable @typescript-eslint/no-explicit-any */
vi.mock("../../../../lib/components/new_session/FolderPicker.svelte", () => ({
  default: function FolderPickerStub(_anchor: any, _props: any) {},
}));
/* eslint-enable @typescript-eslint/no-explicit-any */

import { goto } from "$app/navigation";
import { createSession } from "../../../../lib/api/sessions";
import { listTags } from "../../../../lib/api/tags";
import { sendPrompt } from "../../../../lib/api/prompt";
import type { TagOut } from "../../../../lib/api/tags";
import type { SessionOut } from "../../../../lib/api/sessions";
import NewSessionPage from "../+page.svelte";

function makeTag(overrides: Partial<TagOut> = {}): TagOut {
  return {
    id: 1,
    name: "test",
    color: null,
    default_model: null,
    working_dir: "/test-wd",
    pinned: false,
    class_: "general",
    sort_order: 0,
    group: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeSession(overrides: Partial<SessionOut> = {}): SessionOut {
  return {
    id: "new-session-id",
    kind: "checklist",
    title: "(checklist)",
    description: null,
    session_instructions: null,
    working_dir: "/test-wd",
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

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  (listTags as ReturnType<typeof vi.fn>).mockResolvedValue([makeTag()]);
  (createSession as ReturnType<typeof vi.fn>).mockResolvedValue(makeSession());
});

afterEach(() => {
  vi.useRealTimers();
});

describe("/sessions/new — route-after-create (gap-cycle-10-002)", () => {
  it("checklist create: POSTs kind=checklist, skips sendPrompt, navigates to /sessions/{id}", async () => {
    const { getByTestId } = render(NewSessionPage);

    // Wait for tags to load so the tag chip is visible.
    await waitFor(() => {
      expect(getByTestId("new-session-tag-1")).toBeInTheDocument();
    });

    // Select the tag so the working-dir $effect runs and tagIds are populated.
    await fireEvent.click(getByTestId("new-session-tag-1"));

    // Switch to Checklist kind in the form.
    await fireEvent.click(getByTestId("new-session-kind-checklist"));

    // Submit.
    await fireEvent.click(getByTestId("new-session-submit"));

    // createSession must receive kind: 'checklist'.
    await waitFor(() => {
      expect(createSession).toHaveBeenCalledTimes(1);
    });
    const body = (createSession as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(body.kind).toBe("checklist");

    // sendPrompt must NOT be called for a checklist.
    expect(sendPrompt).not.toHaveBeenCalled();

    // goto must navigate to /sessions/{new-session-id}.
    await waitFor(() => {
      expect(goto).toHaveBeenCalledWith("/sessions/new-session-id");
    });
  });
});
