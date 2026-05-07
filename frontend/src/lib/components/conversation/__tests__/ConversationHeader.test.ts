/**
 * Component tests for ``ConversationHeader`` (gap-cycle-01-005,
 * gap-cycle-11-003).
 *
 * Acceptance criteria:
 * 1. Header renders title, severity shield, tag chips, model dropdown,
 *    cost indicator, and quota bars given a populated session row.
 * 2. Breadcrumb chip only renders when ``checklist_item_id`` is set;
 *    absent for an unpaired session.
 * 3. Changing the model dropdown opens the spec §7 ModelSwitchDialog.
 * 4. "Analyze and reorg" button (gap-cycle-11-003):
 *    - Renders for chat-kind sessions; disabled for non-chat kinds.
 *    - Click opens the ReorgProposalEditor panel (analyzeReorg runs).
 *    - Panel's onclose restores the button to idle (panel unmounts).
 *    - accept-proposal path calls reorgStore.openPicker with correct pivot.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// SvelteKit navigation — mocked so goto() doesn't throw in jsdom.
vi.mock("$app/navigation", () => ({ goto: vi.fn() }));

// Sessions store — provides the session row and per-session tag cache.
vi.mock("../../../stores/sessions.svelte", () => ({
  sessionsStore: {
    get sessions() {
      return _sessions;
    },
    get tagsBySessionId() {
      return _tagsBySessionId;
    },
  },
}));

// Conversation store — ContextMeter reads contextUsage / cacheHitRatio;
// TokenMeter reads sessionInputTokens / sessionOutputTokens.
// Both null/zero keeps the meters in their default state.
vi.mock("../../../stores/conversation.svelte", () => ({
  conversationStore: {
    get contextUsage() {
      return null;
    },
    get cacheHitRatio() {
      return null;
    },
    get sessionInputTokens() {
      return 1200;
    },
    get sessionOutputTokens() {
      return 400;
    },
  },
}));

// App-info — controls billing-mode resolution for the cost/meter swap.
// Default returns "payg" so existing cost-indicator tests remain valid.
let _billingMode: "payg" | "subscription" = "payg";
vi.mock("../../../utils/appInfo", () => ({
  fetchBillingMode: () => Promise.resolve(_billingMode),
}));

// Reorg store — analyzeReorg is called by ReorgProposalEditor on open.
// openPicker is called when the user accepts a proposal.
// vi.hoisted() is required because vi.mock factories are hoisted to the top
// of the file before variable declarations are reached.
const { analyzeReorgMock, openPickerMock } = vi.hoisted(() => ({
  analyzeReorgMock: vi.fn(),
  openPickerMock: vi.fn(),
}));
vi.mock("../../../stores/reorg.svelte", () => ({
  analyzeReorg: analyzeReorgMock,
  reorgStore: { openPicker: openPickerMock },
}));

// messages API — listMessages is called by ReorgProposalEditor's
// handleAccept to look up the seq for the accepted proposal's message.
const { listMessagesMock } = vi.hoisted(() => ({ listMessagesMock: vi.fn() }));
vi.mock("../../../api/messages", () => ({
  listMessages: listMessagesMock,
}));

import type { SessionOut } from "../../../api/sessions";
import type { TagOut } from "../../../api/tags";
import ConversationHeader from "../ConversationHeader.svelte";

// ---- Store state -------------------------------------------------------

type PartialSession = Partial<SessionOut> & { id: string; title: string; model: string };

let _sessions: PartialSession[] = [];
let _tagsBySessionId: Record<string, TagOut[]> = {};

function makeSession(overrides: Partial<PartialSession> = {}): PartialSession {
  return {
    id: "ses_1",
    title: "My Session",
    model: "sonnet",
    total_cost_usd: 0.12,
    last_context_tokens: null,
    checklist_item_id: null,
    paired_parent_title: null,
    permission_mode: null,
    ...overrides,
  };
}

function makeTag(overrides: Partial<TagOut> & { id: number; name: string; class_: TagOut["class_"] }): TagOut {
  return {
    color: null,
    default_model: null,
    working_dir: null,
    pinned: false,
    sort_order: 0,
    group: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function setSession(session: PartialSession, tags: TagOut[] = []): void {
  _sessions = [session];
  _tagsBySessionId = { [session.id]: tags };
}

// ---- Fetch stub --------------------------------------------------------

const fetchMock = vi.fn();

/**
 * Configure the fetch stub to route requests by URL prefix.
 *
 * - ``/api/quota/current`` → 503 by default (quota unavailable — QuotaBars
 *   renders the "—" state; the snapshot being null is fine for most tests).
 * - ``/api/checklist-items/{id}`` → caller-supplied payload when provided.
 */
function setupFetch(routes: Record<string, { status: number; body: unknown }> = {}): void {
  fetchMock.mockImplementation(async (url: string) => {
    for (const [prefix, config] of Object.entries(routes)) {
      if ((url as string).includes(prefix)) {
        return {
          status: config.status,
          statusText: config.status === 200 ? "OK" : "Error",
          json: async () => config.body,
        };
      }
    }
    // Default: quota endpoint unavailable.
    if ((url as string).includes("/api/quota/current")) {
      return {
        status: 503,
        statusText: "Service Unavailable",
        json: async () => ({ detail: "quota poller not configured" }),
      };
    }
    return {
      status: 404,
      statusText: "Not Found",
      json: async () => ({ detail: `unmocked: ${url as string}` }),
    };
  });
}

beforeEach(() => {
  _sessions = [];
  _tagsBySessionId = {};
  _billingMode = "payg";
  fetchMock.mockReset();
  setupFetch();
  vi.stubGlobal("fetch", fetchMock);
  analyzeReorgMock.mockResolvedValue([
    { messageId: "msg2", reason: "Natural chunk boundary" },
  ]);
  listMessagesMock.mockResolvedValue({
    items: [
      { id: "msg2", session_id: "ses_1", role: "assistant", content: "hi", seq: 2, created_at: "2026-01-01T10:01:00Z" },
    ],
    has_more: false,
  });
  openPickerMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

// ---- Tests -------------------------------------------------------------

describe("ConversationHeader", () => {
  // -- AC1: full surface with populated session ----------------------------

  it("renders nothing when sessionId is null", () => {
    const { queryByTestId } = render(ConversationHeader, { props: { sessionId: null } });
    expect(queryByTestId("conversation-header")).toBeNull();
  });

  it("renders nothing when the session is not in the store", () => {
    const { queryByTestId } = render(ConversationHeader, { props: { sessionId: "ses_unknown" } });
    expect(queryByTestId("conversation-header")).toBeNull();
  });

  it("renders the header element when a session exists", () => {
    setSession(makeSession());
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(getByTestId("conversation-header")).toBeDefined();
  });

  it("renders the session title in the header", () => {
    setSession(makeSession({ title: "Bearings v1 rebuild" }));
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(getByTestId("conversation-header-title")).toHaveTextContent("Bearings v1 rebuild");
  });

  it("renders the severity shield when a severity tag is attached", () => {
    const severityTag = makeTag({ id: 1, name: "P0", class_: "severity", color: "#ef4444" });
    setSession(makeSession(), [severityTag]);
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    const shield = getByTestId("conversation-header-severity");
    expect(shield).toBeDefined();
    expect(shield).toHaveTextContent("P0");
  });

  it("does NOT render the severity shield when no severity tag is attached", () => {
    const generalTag = makeTag({ id: 2, name: "bearings", class_: "general" });
    setSession(makeSession(), [generalTag]);
    const { queryByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(queryByTestId("conversation-header-severity")).toBeNull();
  });

  it("renders non-severity tag chips", () => {
    const tags = [
      makeTag({ id: 1, name: "bearings", class_: "project" }),
      makeTag({ id: 2, name: "executor", class_: "general" }),
    ];
    setSession(makeSession(), tags);
    const { getByTestId, getAllByTestId } = render(ConversationHeader, {
      props: { sessionId: "ses_1" },
    });
    expect(getByTestId("conversation-header-tags")).toBeDefined();
    expect(getAllByTestId("conversation-header-tag-chip")).toHaveLength(2);
  });

  it("does NOT render the tag chips wrapper when all tags are severity-class", () => {
    const severityTag = makeTag({ id: 1, name: "P1", class_: "severity" });
    setSession(makeSession(), [severityTag]);
    const { queryByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(queryByTestId("conversation-header-tags")).toBeNull();
  });

  it("renders the model selector (executor dropdown)", () => {
    setSession(makeSession({ model: "sonnet" }));
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(getByTestId("model-selector")).toBeDefined();
  });

  it("renders the permission-mode selector", () => {
    setSession(makeSession());
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(getByTestId("permission-mode-selector")).toBeDefined();
  });

  it("renders the total-cost indicator when cost is non-zero", () => {
    setSession(makeSession({ total_cost_usd: 0.42 }));
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(getByTestId("conversation-header-cost")).toHaveTextContent("$0.42");
  });

  it("does NOT render the cost indicator when total_cost_usd is 0", () => {
    setSession(makeSession({ total_cost_usd: 0 }));
    const { queryByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(queryByTestId("conversation-header-cost")).toBeNull();
  });

  it("renders the quota bars component", () => {
    setSession(makeSession());
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    // QuotaBars always renders its wrapper div regardless of snapshot state.
    expect(getByTestId("quota-bars")).toBeDefined();
  });

  // -- AC2: breadcrumb gating -------------------------------------------------

  it("does NOT render the breadcrumb when checklist_item_id is null", () => {
    setSession(makeSession({ checklist_item_id: null }));
    const { queryByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(queryByTestId("paired-chat-indicator")).toBeNull();
  });

  it("renders the breadcrumb chip when checklist_item_id is set", () => {
    setSession(
      makeSession({
        checklist_item_id: 42,
        paired_parent_title: "v1 rebuild",
      }),
    );
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    // PairedChatIndicator renders immediately (uses session title as item-
    // label fallback before the async item fetch completes).
    expect(getByTestId("paired-chat-indicator")).toBeDefined();
  });

  it("shows the parent title segment in the breadcrumb", () => {
    setSession(
      makeSession({
        checklist_item_id: 42,
        paired_parent_title: "My Checklist",
        title: "Item label",
      }),
    );
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(getByTestId("paired-chat-parent")).toHaveTextContent("My Checklist");
  });

  it("uses session title as item-label fallback before the item fetch resolves", () => {
    // fetch stays pending — item label is taken from session.title.
    fetchMock.mockImplementation(() => new Promise(() => {})); // never resolves
    setSession(
      makeSession({
        checklist_item_id: 42,
        paired_parent_title: "Checklist",
        title: "My Item",
      }),
    );
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(getByTestId("paired-chat-item")).toHaveTextContent("My Item");
  });

  it("updates the breadcrumb item label after the checklist item fetch completes", async () => {
    const itemPayload = {
      id: 42,
      checklist_id: "chk_abc",
      label: "Fetched Item Label",
      parent_item_id: null,
      notes: null,
      sort_order: 0,
      checked_at: null,
      chat_session_id: "ses_1",
      blocked_at: null,
      blocked_reason_category: null,
      blocked_reason_text: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    setupFetch({ "/api/checklist-items/42": { status: 200, body: itemPayload } });
    setSession(
      makeSession({
        checklist_item_id: 42,
        paired_parent_title: "Checklist",
        title: "Fallback Label",
      }),
    );
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    await waitFor(() => {
      expect(getByTestId("paired-chat-item")).toHaveTextContent("Fetched Item Label");
    });
  });

  it("renders the deleted breadcrumb state when paired_parent_title is null", () => {
    // checklist_item_id set but paired_parent_title null → parent deleted.
    setSession(
      makeSession({
        checklist_item_id: 42,
        paired_parent_title: null,
      }),
    );
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(getByTestId("paired-chat-deleted")).toHaveTextContent("(checklist deleted)");
  });

  // -- AC3: model dropdown opens the dialog -----------------------------------

  it("opens ModelSwitchDialog when a different executor model is selected", async () => {
    setSession(makeSession({ model: "sonnet" }));
    const { getByTestId, queryByTestId } = render(ConversationHeader, {
      props: { sessionId: "ses_1" },
    });
    expect(queryByTestId("model-switch-dialog")).toBeNull();
    const select = getByTestId("model-select") as HTMLSelectElement;
    select.value = "opus";
    await fireEvent.change(select);
    expect(getByTestId("model-switch-dialog")).toBeDefined();
  });

  it("closes ModelSwitchDialog when Cancel is clicked", async () => {
    setSession(makeSession({ model: "sonnet" }));
    const { getByTestId, queryByTestId } = render(ConversationHeader, {
      props: { sessionId: "ses_1" },
    });
    const select = getByTestId("model-select") as HTMLSelectElement;
    select.value = "opus";
    await fireEvent.change(select);
    expect(getByTestId("model-switch-dialog")).toBeDefined();
    await fireEvent.click(getByTestId("model-switch-cancel"));
    expect(queryByTestId("model-switch-dialog")).toBeNull();
  });

  // -- Billing mode: subscription renders TokenMeter / PAYG renders dollars ---

  it("renders the dollar cost indicator when billing mode is PAYG", async () => {
    _billingMode = "payg";
    setSession(makeSession({ total_cost_usd: 0.42 }));
    const { getByTestId, queryByTestId } = render(ConversationHeader, {
      props: { sessionId: "ses_1" },
    });
    // Dollar figure visible (cost > 0, PAYG).
    expect(getByTestId("conversation-header-cost")).toHaveTextContent("$0.42");
    // TokenMeter must be absent.
    expect(queryByTestId("token-meter")).toBeNull();
  });

  it("renders TokenMeter and hides the dollar figure when billing mode is subscription", async () => {
    _billingMode = "subscription";
    setSession(makeSession({ total_cost_usd: 0.42 }));
    const { queryByTestId } = render(ConversationHeader, {
      props: { sessionId: "ses_1" },
    });
    // Billing-mode promise resolves asynchronously; wait for the meter.
    await waitFor(() => {
      expect(queryByTestId("token-meter")).toBeDefined();
    });
    // Dollar figure must be absent regardless of cost value.
    expect(queryByTestId("conversation-header-cost")).toBeNull();
  });

  it("shows token totals from the conversation store in subscription mode", async () => {
    _billingMode = "subscription";
    setSession(makeSession({ total_cost_usd: 0.42 }));
    const { getByTestId } = render(ConversationHeader, {
      props: { sessionId: "ses_1" },
    });
    await waitFor(() => {
      // conversationStore mock returns 1200 in / 400 out.
      expect(getByTestId("token-meter-input")).toHaveTextContent("1.2k in");
      expect(getByTestId("token-meter-output")).toHaveTextContent("400 out");
    });
  });
});

// ---------------------------------------------------------------------------
// AC4: "Analyze and reorg" button + ReorgProposalEditor wiring
// (gap-cycle-11-003)
// ---------------------------------------------------------------------------

describe("ConversationHeader — analyze-reorg button (gap-cycle-11-003)", () => {
  it("renders the analyze-reorg button for a chat-kind session", () => {
    setSession(makeSession({ kind: "chat" }));
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(getByTestId("analyze-reorg-button")).toBeDefined();
  });

  it("button is enabled for a chat-kind session", () => {
    setSession(makeSession({ kind: "chat" }));
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(getByTestId("analyze-reorg-button")).not.toBeDisabled();
  });

  it("button is disabled for a non-chat (checklist) session", () => {
    setSession(makeSession({ kind: "checklist" }));
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(getByTestId("analyze-reorg-button")).toBeDisabled();
  });

  it("ReorgProposalEditor panel is not visible before the button is clicked", () => {
    setSession(makeSession({ kind: "chat" }));
    const { queryByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    expect(queryByTestId("reorg-proposal-editor")).toBeNull();
  });

  it("clicking the button opens the ReorgProposalEditor panel", async () => {
    setSession(makeSession({ kind: "chat" }));
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    await fireEvent.click(getByTestId("analyze-reorg-button"));
    await waitFor(() => {
      expect(getByTestId("reorg-proposal-editor")).toBeDefined();
    });
  });

  it("analyzeReorg() is called once when the panel opens", async () => {
    setSession(makeSession({ id: "ses_1", kind: "chat" }));
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    await fireEvent.click(getByTestId("analyze-reorg-button"));
    await waitFor(() => {
      expect(analyzeReorgMock).toHaveBeenCalledTimes(1);
      expect(analyzeReorgMock).toHaveBeenCalledWith("ses_1");
    });
  });

  it("closing the panel (rpe-close) hides the ReorgProposalEditor", async () => {
    setSession(makeSession({ kind: "chat" }));
    const { getByTestId, queryByTestId } = render(ConversationHeader, {
      props: { sessionId: "ses_1" },
    });
    await fireEvent.click(getByTestId("analyze-reorg-button"));
    await waitFor(() => expect(getByTestId("reorg-proposal-editor")).toBeDefined());
    await fireEvent.click(getByTestId("rpe-close"));
    await waitFor(() => {
      expect(queryByTestId("reorg-proposal-editor")).toBeNull();
    });
  });

  it("accepting a proposal calls reorgStore.openPicker with the correct pivot", async () => {
    setSession(makeSession({ id: "ses_1", kind: "chat" }));
    const { getByTestId } = render(ConversationHeader, { props: { sessionId: "ses_1" } });
    await fireEvent.click(getByTestId("analyze-reorg-button"));
    await waitFor(() => expect(getByTestId("rpe-proposal-msg2")).toBeDefined());
    await fireEvent.click(getByTestId("rpe-accept-msg2"));
    await waitFor(() => {
      expect(openPickerMock).toHaveBeenCalledWith({
        mode: "split",
        messageId: "msg2",
        sourceSessionId: "ses_1",
        seq: 2,
      });
    });
  });
});
