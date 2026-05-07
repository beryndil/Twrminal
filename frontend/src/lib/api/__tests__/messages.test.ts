/**
 * Tests for :func:`listMessages` / :func:`getMessage` — wire-shape
 * round-trip, query-param projection, error surfacing.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getMessage,
  listMessages,
  listToolCalls,
  type MessageOut,
  type MessagePage,
  type ToolCallOut,
} from "../messages";

const sampleRow: MessageOut = {
  id: "msg_1",
  session_id: "ses_a",
  role: "assistant",
  content: "hi",
  created_at: "2026-04-29T00:00:00Z",
  executor_model: "sonnet",
  advisor_model: null,
  effort_level: "med",
  routing_source: "tag_rule",
  routing_reason: "matched bearings/architect",
  matched_rule_id: 5,
  executor_input_tokens: 100,
  executor_output_tokens: 200,
  advisor_input_tokens: null,
  advisor_output_tokens: null,
  advisor_calls_count: 0,
  cache_read_tokens: 50,
  input_tokens: 300,
  output_tokens: 200,
  seq: 42,
  pinned: false,
  hidden_from_context: false,
};

const samplePage: MessagePage = {
  items: [sampleRow],
  has_more: false,
};

describe("listMessages", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns a MessagePage envelope", async () => {
    fetchMock.mockResolvedValueOnce({
      status: 200,
      statusText: "OK",
      json: async () => samplePage,
    });
    const page = await listMessages("ses_a");
    expect(page).toEqual(samplePage);
    expect(page.items[0].seq).toBe(42);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe("/api/sessions/ses_a/messages");
  });

  it("adds a ``limit`` query param when supplied", async () => {
    fetchMock.mockResolvedValueOnce({
      status: 200,
      statusText: "OK",
      json: async () => ({ items: [], has_more: false }),
    });
    await listMessages("ses_a", { limit: 50 });
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("limit=50");
  });

  it("adds a ``before`` query param when supplied", async () => {
    fetchMock.mockResolvedValueOnce({
      status: 200,
      statusText: "OK",
      json: async () => ({ items: [], has_more: false }),
    });
    await listMessages("ses_a", { before: 99 });
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("before=99");
  });

  it("adds both ``limit`` and ``before`` when supplied together", async () => {
    fetchMock.mockResolvedValueOnce({
      status: 200,
      statusText: "OK",
      json: async () => ({ items: [], has_more: false }),
    });
    await listMessages("ses_a", { limit: 100, before: 55 });
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("limit=100");
    expect(url).toContain("before=55");
  });

  it("URL-encodes the session id", async () => {
    fetchMock.mockResolvedValueOnce({
      status: 200,
      statusText: "OK",
      json: async () => ({ items: [], has_more: false }),
    });
    await listMessages("a/b");
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("a%2Fb");
  });
});

describe("getMessage", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("hits the single-message endpoint", async () => {
    fetchMock.mockResolvedValueOnce({
      status: 200,
      statusText: "OK",
      json: async () => sampleRow,
    });
    const row = await getMessage("msg_1");
    expect(row.id).toBe("msg_1");
    expect(row.seq).toBe(42);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe("/api/messages/msg_1");
  });
});

// ---------------------------------------------------------------------------
// listToolCalls (gap-cycle-03-012)
// ---------------------------------------------------------------------------

const sampleToolCall: ToolCallOut = {
  id: "toolu_01",
  session_id: "ses_a",
  message_id: "msg_1",
  tool_name: "Bash",
  input_json: '{"command":"ls"}',
  output: "file.txt",
  ok: true,
  duration_ms: 15,
  error_message: null,
  created_at: "2026-01-01T00:00:00Z",
};

describe("listToolCalls", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns empty array without fetching when messageIds is empty", async () => {
    const result = await listToolCalls("ses_a", []);
    expect(result).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("hits /api/sessions/{id}/tool_calls with message_ids params", async () => {
    fetchMock.mockResolvedValueOnce({
      status: 200,
      statusText: "OK",
      json: async () => [sampleToolCall],
    });
    const result = await listToolCalls("ses_a", ["msg_1", "msg_2"]);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("toolu_01");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/api/sessions/ses_a/tool_calls");
    expect(url).toContain("message_ids=msg_1");
    expect(url).toContain("message_ids=msg_2");
  });

  it("URL-encodes the session id", async () => {
    fetchMock.mockResolvedValueOnce({
      status: 200,
      statusText: "OK",
      json: async () => [],
    });
    await listToolCalls("a/b", ["msg_x"]);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("a%2Fb");
  });
});
