/**
 * Route-level tests for ``/sessions/new``.
 *
 * Coverage:
 *
 * * route-after-create (checklist) [gap-cycle-10-002]: submitting a
 *   checklist session calls ``createSession`` with ``kind: 'checklist'``,
 *   skips ``sendPrompt``, and navigates to ``/sessions/{id}`` via ``goto``.
 *
 * * Tag inline filter / create [gap-cycle-10-003]:
 *   - suggestion-on-type: typing filters the available tag list.
 *   - Enter-attaches-existing: exact-match tag is selected without a POST.
 *   - Enter-creates-and-attaches: no-match → POST /api/tags → tag appended
 *     and selected.
 *   - 422-inline-error: POST /api/tags returns a 422 body → error shown
 *     inline, selection unchanged.
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
  createTag: vi.fn(),
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
vi.mock("../../../../lib/api/quota", () => {
  const mockQuotaRow = {
    captured_at: 0,
    overall_used_pct: 0,
    sonnet_used_pct: 0,
    overall_resets_at: null,
    sonnet_resets_at: null,
    raw_payload: "{}",
  };
  return {
    getCurrentQuota: vi.fn().mockResolvedValue(mockQuotaRow),
    // NewSessionForm uses the safe wrapper; expose it alongside the raw fn.
    getCurrentQuotaSafe: vi.fn().mockResolvedValue(mockQuotaRow),
  };
});
vi.mock("../../../../lib/api/templates", () => ({
  listTemplates: vi.fn().mockResolvedValue([]),
}));

// ---- Stub heavy child components + stores that pull in WS infra -------------

/* eslint-disable @typescript-eslint/no-explicit-any */
vi.mock("../../../../lib/components/new_session/FolderPicker.svelte", () => ({
  default: function FolderPickerStub(_anchor: any, _props: any) {},
}));
// The sessions store opens a WebSocket that jsdom cannot handle; stub it out
// so importing the store in +page.svelte does not throw during test setup.
vi.mock("../../../../lib/stores/sessions.svelte", () => ({
  sessionsStore: {
    sessions: [],
    tagsBySessionId: {},
    loading: false,
    error: null,
    running: new Set(),
    awaiting: new Set(),
  },
  refreshSessions: vi.fn().mockResolvedValue(undefined),
  indicatorState: vi.fn().mockReturnValue(null),
  wsConnectionStatus: { state: "closed", lastCloseCode: null },
}));
/* eslint-enable @typescript-eslint/no-explicit-any */

import { goto } from "$app/navigation";
import { createSession } from "../../../../lib/api/sessions";
import { createTag, listTags } from "../../../../lib/api/tags";
import { ApiError } from "../../../../lib/api/client";
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
    open_session_count: 0,
    session_count: 0,
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

// ---------------------------------------------------------------------------
// gap-cycle-10-003: inline tag filter / create
// ---------------------------------------------------------------------------

describe("/sessions/new — tag inline filter/create (gap-cycle-10-003)", () => {
  it("suggestion-on-type: typing prefix filters the Available tag list", async () => {
    const alpha = makeTag({ id: 1, name: "alpha" });
    const beta = makeTag({ id: 2, name: "beta" });
    (listTags as ReturnType<typeof vi.fn>).mockResolvedValue([alpha, beta]);

    const { getByTestId, queryByTestId } = render(NewSessionPage);

    // Wait for tags to load.
    await waitFor(() => {
      expect(getByTestId("new-session-tag-1")).toBeInTheDocument();
    });

    const input = getByTestId("new-session-tag-input");

    // Type "al" — should show alpha chip, hide beta chip.
    await fireEvent.input(input, { target: { value: "al" } });
    await fireEvent.change(input, { target: { value: "al" } });

    await waitFor(() => {
      expect(getByTestId("new-session-tag-1")).toBeInTheDocument();
      expect(queryByTestId("new-session-tag-2")).toBeNull();
    });
  });

  it("Enter-attaches-existing: exact match attaches without POST /api/tags", async () => {
    const alpha = makeTag({ id: 1, name: "alpha" });
    (listTags as ReturnType<typeof vi.fn>).mockResolvedValue([alpha]);

    const { getByTestId } = render(NewSessionPage);

    // Wait for the available tag chip to appear (tags loaded).
    await waitFor(() => {
      expect(getByTestId("new-session-tag-1")).toBeInTheDocument();
    });

    const input = getByTestId("new-session-tag-input");

    // Type exact name (case variant) and press Enter.
    await fireEvent.input(input, { target: { value: "Alpha" } });
    await fireEvent.change(input, { target: { value: "Alpha" } });
    await fireEvent.keyDown(input, { key: "Enter" });

    // createTag must NOT be called — the existing tag is re-used.
    expect(createTag).not.toHaveBeenCalled();

    // The chip moves to the selected column (same testid, now aria-pressed="true").
    await waitFor(() => {
      expect(getByTestId("new-session-tag-1")).toHaveAttribute("aria-pressed", "true");
    });
  });

  it("Enter-creates-and-attaches: no match → POST /api/tags → chip appears in selected list", async () => {
    (listTags as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    const fresh = makeTag({ id: 99, name: "brand-new", working_dir: null });
    (createTag as ReturnType<typeof vi.fn>).mockResolvedValue(fresh);

    const { getByTestId } = render(NewSessionPage);

    // The input is always rendered when not loading/error; no need to wait for
    // tags — just wait for the component to mount.
    await waitFor(() => {
      expect(getByTestId("new-session-page")).toBeInTheDocument();
    });
    // Wait for the tags loading state to settle (listTags resolves to []).
    await waitFor(() => {
      expect(getByTestId("new-session-tag-input")).toBeInTheDocument();
    });

    const input = getByTestId("new-session-tag-input");
    await fireEvent.input(input, { target: { value: "brand-new" } });
    await fireEvent.change(input, { target: { value: "brand-new" } });
    await fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(createTag).toHaveBeenCalledWith({ name: "brand-new" });
    });

    // The newly created tag (id=99) should appear in the selected column.
    await waitFor(() => {
      expect(getByTestId("new-session-tag-99")).toHaveAttribute("aria-pressed", "true");
    });
  });

  it("422-inline-error: POST /api/tags 422 → inline error, no tag selected", async () => {
    (listTags as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (createTag as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(422, { detail: "name already exists" }, "POST /api/tags → 422"),
    );

    const { getByTestId, queryByTestId } = render(NewSessionPage);

    // Wait for tag loading to settle (listTags resolves to []), then the input appears.
    await waitFor(() => {
      expect(getByTestId("new-session-tag-input")).toBeInTheDocument();
    });

    const input = getByTestId("new-session-tag-input");
    await fireEvent.input(input, { target: { value: "dupe" } });
    await fireEvent.change(input, { target: { value: "dupe" } });
    await fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(getByTestId("new-session-tag-create-error")).toHaveTextContent("name already exists");
    });

    // No tag chip should have been added to the selected list.
    expect(queryByTestId("new-session-tag-99")).toBeNull();
  });
});
