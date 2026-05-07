/**
 * Component tests for ``Conversation`` — history hydration on
 * session-id change, empty state, error surface, basic list
 * rendering, and streaming auto-scroll behavior (gap-cycle-16-001).
 *
 * The WebSocket subscription side of the pane is stubbed by mocking
 * the agent module — we don't open a real socket in jsdom. The
 * fetch is stubbed via ``vi.stubGlobal``.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { flushSync } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../agent.svelte", () => ({
  connectSession: vi.fn(),
  disconnectSession: vi.fn(),
}));

// Prevent ConversationHeader's fetchBillingMode() from hitting the network.
vi.mock("../../../utils/appInfo", () => ({
  fetchBillingMode: () => Promise.resolve("payg"),
}));

import Conversation from "../Conversation.svelte";
import {
  _resetForTests,
  ingestFrame,
  resetConversation,
} from "../../../stores/conversation.svelte";
import { WS_FRAME_KIND_EVENT } from "../../../config";

const fetchMock = vi.fn();

interface MockResponse {
  status: number;
  statusText: string;
  json: () => Promise<unknown>;
}

/**
 * Per-test URL → response routing. Each test populates this map with
 * the messages-fetch payload it cares about; the gutter (G6) fetches
 * ``/api/checkpoints?session_id=…`` and gets an empty list by default.
 */
let routes: Record<string, MockResponse> = {};

function setMessagesResponse(sessionId: string, payload: MockResponse): void {
  routes[`/api/sessions/${sessionId}/messages?limit=100`] = payload;
}

beforeEach(() => {
  fetchMock.mockReset();
  routes = {};
  fetchMock.mockImplementation(async (url: string) => {
    if (url.includes("/api/checkpoints")) {
      return { status: 200, statusText: "OK", json: async () => [] };
    }
    const route = routes[url];
    if (route !== undefined) return route;
    return {
      status: 500,
      statusText: "no mock",
      json: async () => ({ detail: `unmocked URL ${url}` }),
    };
  });
  vi.stubGlobal("fetch", fetchMock);
  _resetForTests();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Conversation — empty / null session", () => {
  it("renders the no-session-open empty state when no sessionId is supplied", () => {
    const { queryByTestId } = render(Conversation, { props: { sessionId: null } });
    // With null sessionId the store stays empty; the empty-transcript
    // copy applies (no fetch fires).
    expect(queryByTestId("conversation")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("Conversation — hydration", () => {
  it("hits /api/sessions/<id>/messages on mount with a session id", async () => {
    setMessagesResponse("ses_a", {
      status: 200,
      statusText: "OK",
      json: async () => ({ items: [], has_more: false }),
    });
    render(Conversation, { props: { sessionId: "ses_a" } });
    await waitFor(() => {
      // The conversation hydrates via /api/sessions/<id>/messages AND
      // the gutter fetches /api/checkpoints?session_id=<id> (G6) — both
      // fire on session-id change.
      const calls = fetchMock.mock.calls;
      const messageUrls = calls.map((c) => c[0] as string);
      expect(messageUrls.some((url) => url === "/api/sessions/ses_a/messages?limit=100")).toBe(
        true,
      );
      expect(messageUrls.some((url) => url.startsWith("/api/checkpoints?session_id="))).toBe(true);
    });
  });

  it("renders the empty-transcript copy when the history is empty", async () => {
    setMessagesResponse("ses_a", {
      status: 200,
      statusText: "OK",
      json: async () => ({ items: [], has_more: false }),
    });
    const { findByTestId } = render(Conversation, { props: { sessionId: "ses_a" } });
    expect(await findByTestId("conversation-empty")).toBeTruthy();
  });

  it("renders one MessageTurn per persisted row", async () => {
    setMessagesResponse("ses_a", {
      status: 200,
      statusText: "OK",
      json: async () => ({
        has_more: false,
        items: [
          {
            id: "u1",
            seq: 1,
            session_id: "ses_a",
            role: "user",
            content: "hi",
            created_at: "2026-04-29T00:00:00Z",
            executor_model: null,
            advisor_model: null,
            effort_level: null,
            routing_source: null,
            routing_reason: null,
            matched_rule_id: null,
            executor_input_tokens: null,
            executor_output_tokens: null,
            advisor_input_tokens: null,
            advisor_output_tokens: null,
            advisor_calls_count: null,
            cache_read_tokens: null,
            input_tokens: null,
            output_tokens: null,
          },
        ],
      }),
    });
    const { findAllByTestId } = render(Conversation, { props: { sessionId: "ses_a" } });
    const turns = await findAllByTestId("message-turn");
    expect(turns).toHaveLength(1);
  });

  it("surfaces the error banner on a non-2xx history fetch", async () => {
    setMessagesResponse("ses_a", {
      status: 500,
      statusText: "Server Error",
      json: async () => ({}),
    });
    const { findByTestId } = render(Conversation, { props: { sessionId: "ses_a" } });
    expect(await findByTestId("conversation-error")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Streaming auto-scroll (gap-cycle-16-001)
//
// These tests drive state through ``ingestFrame`` (the conversation.svelte.ts
// ingestFrame harness) and observe whether ``bodyEl.scrollTop`` gets written.
// jsdom has no real layout so we mock ``scrollHeight`` via
// ``Object.defineProperty`` and intercept the ``scrollTop`` setter.
// ---------------------------------------------------------------------------

/**
 * Install scroll-property mocks on ``bodyEl`` and return a getter for the
 * most recent ``scrollTop`` assignment value.
 */
function mockScrollProps(el: HTMLElement): { getScrollTop: () => number } {
  let scrollTopValue = 0;
  Object.defineProperty(el, "scrollHeight", {
    get: () => 1000,
    configurable: true,
  });
  Object.defineProperty(el, "scrollTop", {
    get: () => scrollTopValue,
    set: (v: number) => {
      scrollTopValue = v;
    },
    configurable: true,
  });
  return { getScrollTop: () => scrollTopValue };
}

/** Flush Svelte reactive effects then drain the microtask queue. */
async function flushAll(): Promise<void> {
  flushSync();
  await new Promise<void>((r) => queueMicrotask(r));
}

describe("Conversation — streaming auto-scroll (gap-cycle-16-001)", () => {
  it("(a) token event re-fires auto-scroll while atBottom=true", async () => {
    setMessagesResponse("ses_sc1", {
      status: 200,
      statusText: "OK",
      json: async () => ({ items: [], has_more: false }),
    });
    const { getByTestId } = render(Conversation, { props: { sessionId: "ses_sc1" } });
    await waitFor(() => expect(getByTestId("conversation-body")).toBeTruthy());
    const bodyEl = getByTestId("conversation-body");
    const { getScrollTop } = mockScrollProps(bodyEl);

    // Open an in-flight assistant turn.
    resetConversation("ses_sc1");
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 1,
      event: { session_id: "ses_sc1", type: "message_start", message_id: "a1" },
    });
    await flushAll();

    // Dispatch a token — extends body without changing turns.length.
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 2,
      event: { session_id: "ses_sc1", type: "token", message_id: "a1", delta: "hello" },
    });
    await flushAll();

    // auto-scroll effect must have written scrollTop = scrollHeight (1000).
    expect(getScrollTop()).toBe(1000);
  });

  it("(b) tool_output_delta event re-fires auto-scroll while atBottom=true", async () => {
    setMessagesResponse("ses_sc2", {
      status: 200,
      statusText: "OK",
      json: async () => ({ items: [], has_more: false }),
    });
    const { getByTestId } = render(Conversation, { props: { sessionId: "ses_sc2" } });
    await waitFor(() => expect(getByTestId("conversation-body")).toBeTruthy());
    const bodyEl = getByTestId("conversation-body");
    const { getScrollTop } = mockScrollProps(bodyEl);

    resetConversation("ses_sc2");
    // Open assistant turn with a tool call.
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 1,
      event: { session_id: "ses_sc2", type: "message_start", message_id: "a2" },
    });
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 2,
      event: {
        session_id: "ses_sc2",
        type: "tool_call_start",
        message_id: "a2",
        tool_call_id: "tc1",
        tool_name: "Bash",
        tool_input_json: "{}",
      },
    });
    await flushAll();

    // Dispatch a tool_output_delta — extends output without changing turns.length.
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 3,
      event: {
        session_id: "ses_sc2",
        type: "tool_output_delta",
        tool_call_id: "tc1",
        delta: "line1\n",
      },
    });
    await flushAll();

    expect(getScrollTop()).toBe(1000);
  });

  it("(c) token event does NOT write scrollTop when user has scrolled up (atBottom=false)", async () => {
    setMessagesResponse("ses_sc3", {
      status: 200,
      statusText: "OK",
      json: async () => ({ items: [], has_more: false }),
    });
    const { getByTestId } = render(Conversation, { props: { sessionId: "ses_sc3" } });
    await waitFor(() => expect(getByTestId("conversation-body")).toBeTruthy());
    const bodyEl = getByTestId("conversation-body");
    const { getScrollTop } = mockScrollProps(bodyEl);

    // Simulate user scrolling up: scrollHeight=1000, scrollTop=0, clientHeight=0
    // → dist = 1000 >= 16 → atBottom=false.
    fireEvent.scroll(bodyEl);
    flushSync();

    resetConversation("ses_sc3");
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 1,
      event: { session_id: "ses_sc3", type: "message_start", message_id: "a3" },
    });
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 2,
      event: { session_id: "ses_sc3", type: "token", message_id: "a3", delta: "hi" },
    });
    await flushAll();

    // scrollTop must remain 0 — effect must not yank the viewport.
    expect(getScrollTop()).toBe(0);
  });
});
