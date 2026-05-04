/**
 * Component tests for ``Conversation`` — history hydration on
 * session-id change, empty state, error surface, basic list
 * rendering.
 *
 * The WebSocket subscription side of the pane is stubbed by mocking
 * the agent module — we don't open a real socket in jsdom. The
 * fetch is stubbed via ``vi.stubGlobal``.
 */
import { render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../agent.svelte", () => ({
  connectSession: vi.fn(),
  disconnectSession: vi.fn(),
}));

import Conversation from "../Conversation.svelte";
import { _resetForTests } from "../../../stores/conversation.svelte";

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
