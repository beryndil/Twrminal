/**
 * Component tests for ``ConversationHeader`` (gap-cycle-01-005).
 *
 * Acceptance criteria:
 * 1. Header renders title, severity shield, tag chips, model dropdown,
 *    cost indicator, and quota bars given a populated session row.
 * 2. Breadcrumb chip only renders when ``checklist_item_id`` is set;
 *    absent for an unpaired session.
 * 3. Changing the model dropdown opens the spec §7 ModelSwitchDialog.
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

// Conversation store — ContextMeter reads contextUsage / cacheHitRatio.
// Both null keeps the meter hidden (renders nothing), which is the
// correct behaviour before a turn completes.
vi.mock("../../../stores/conversation.svelte", () => ({
  conversationStore: {
    get contextUsage() {
      return null;
    },
    get cacheHitRatio() {
      return null;
    },
  },
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
  fetchMock.mockReset();
  setupFetch();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
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
});
