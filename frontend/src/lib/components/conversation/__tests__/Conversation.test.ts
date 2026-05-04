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

beforeEach(() => {
  fetchMock.mockReset();
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
    fetchMock.mockResolvedValueOnce({
      status: 200,
      statusText: "OK",
      json: async () => ({ items: [], has_more: false }),
    });
    render(Conversation, { props: { sessionId: "ses_a" } });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
      const url = fetchMock.mock.calls[0][0] as string;
      expect(url).toBe("/api/sessions/ses_a/messages?limit=100");
    });
  });

  it("renders the empty-transcript copy when the history is empty", async () => {
    fetchMock.mockResolvedValueOnce({
      status: 200,
      statusText: "OK",
      json: async () => ({ items: [], has_more: false }),
    });
    const { findByTestId } = render(Conversation, { props: { sessionId: "ses_a" } });
    expect(await findByTestId("conversation-empty")).toBeTruthy();
  });

  it("renders one MessageTurn per persisted row", async () => {
    fetchMock.mockResolvedValueOnce({
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
    fetchMock.mockResolvedValueOnce({
      status: 500,
      statusText: "Server Error",
      json: async () => ({}),
    });
    const { findByTestId } = render(Conversation, { props: { sessionId: "ses_a" } });
    expect(await findByTestId("conversation-error")).toBeTruthy();
  });
});
