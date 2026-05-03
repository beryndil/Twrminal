/**
 * Tests for the conversation store reducer + ingest path.
 *
 * Behavioral coverage:
 *
 * - Hydrate from persisted history (item 1.9 ``MessageOut`` rows).
 * - User message → user bubble appears.
 * - message_start + token + message_complete → assistant bubble
 *   grows in place.
 * - tool_call_start + tool_output_delta + tool_call_end → drawer
 *   row opens, body streams, status finalises.
 * - tool_output_delta past the soft cap truncates the visible body
 *   (tail-bookend) but ``rawLength`` keeps the full count.
 * - error event attaches to the in-flight assistant turn.
 * - duplicate seq is ignored on ingest.
 */
import { afterEach, describe, expect, it } from "vitest";

import {
  _resetForTests,
  applyEvent,
  conversationStore,
  hydrateTurns,
  ingestFrame,
  resetConversation,
  type MessageTurnView,
} from "../conversation.svelte";
import { CHAT_TOOL_OUTPUT_SOFT_CAP_CHARS, WS_FRAME_KIND_EVENT } from "../../config";

afterEach(() => {
  _resetForTests();
});

const sid = "ses_a";

const userMsg: MessageTurnView = {
  id: "u1",
  role: "user",
  body: "hello",
  thinking: "",
  complete: true,
  toolCalls: [],
  routing: null,
  error: null,
  createdAt: null,
};

describe("applyEvent — user/assistant lifecycle", () => {
  it("appends a user bubble on user_message", () => {
    const next = applyEvent([], {
      session_id: sid,
      type: "user_message",
      message_id: "u1",
      content: "hello",
    });
    expect(next).toHaveLength(1);
    expect(next[0]).toMatchObject({ id: "u1", role: "user", body: "hello" });
  });

  it("opens an assistant bubble on message_start and grows it on token", () => {
    let turns = applyEvent([userMsg], {
      session_id: sid,
      type: "message_start",
      message_id: "a1",
    });
    turns = applyEvent(turns, {
      session_id: sid,
      type: "token",
      message_id: "a1",
      delta: "hi",
    });
    turns = applyEvent(turns, {
      session_id: sid,
      type: "token",
      message_id: "a1",
      delta: " there",
    });
    expect(turns[1]).toMatchObject({
      id: "a1",
      role: "assistant",
      body: "hi there",
      complete: false,
    });
  });

  it("marks the turn complete on message_complete", () => {
    let turns = applyEvent([], {
      session_id: sid,
      type: "message_start",
      message_id: "a1",
    });
    turns = applyEvent(turns, {
      session_id: sid,
      type: "token",
      message_id: "a1",
      delta: "hi",
    });
    turns = applyEvent(turns, {
      session_id: sid,
      type: "message_complete",
      message_id: "a1",
      content: "",
      executor_input_tokens: 1,
      executor_output_tokens: 2,
      advisor_input_tokens: null,
      advisor_output_tokens: null,
      advisor_calls_count: 0,
      cache_read_tokens: null,
      input_tokens: null,
      output_tokens: null,
    });
    expect(turns[0].complete).toBe(true);
  });
});

describe("applyEvent — tool drawer", () => {
  function withAssistantTurn(): readonly MessageTurnView[] {
    return applyEvent([], {
      session_id: sid,
      type: "message_start",
      message_id: "a1",
    });
  }

  it("opens a tool drawer row on tool_call_start", () => {
    const turns = applyEvent(withAssistantTurn(), {
      session_id: sid,
      type: "tool_call_start",
      message_id: "a1",
      tool_call_id: "t1",
      tool_name: "Bash",
      tool_input_json: '{"cmd":"ls"}',
    });
    expect(turns[0].toolCalls).toEqual([
      expect.objectContaining({ id: "t1", name: "Bash", inputJson: '{"cmd":"ls"}', done: false }),
    ]);
  });

  it("streams output via tool_output_delta and finalises on tool_call_end", () => {
    let turns = applyEvent(withAssistantTurn(), {
      session_id: sid,
      type: "tool_call_start",
      message_id: "a1",
      tool_call_id: "t1",
      tool_name: "Bash",
      tool_input_json: "{}",
    });
    turns = applyEvent(turns, {
      session_id: sid,
      type: "tool_output_delta",
      tool_call_id: "t1",
      delta: "hello\n",
    });
    turns = applyEvent(turns, {
      session_id: sid,
      type: "tool_output_delta",
      tool_call_id: "t1",
      delta: "world\n",
    });
    turns = applyEvent(turns, {
      session_id: sid,
      type: "tool_call_end",
      message_id: "a1",
      tool_call_id: "t1",
      ok: true,
      duration_ms: 42,
      output_summary: "",
      error_message: null,
    });
    const tc = turns[0].toolCalls[0];
    expect(tc.output).toBe("hello\nworld\n");
    expect(tc.done).toBe(true);
    expect(tc.ok).toBe(true);
    expect(tc.durationMs).toBe(42);
  });

  it("truncates display output past the soft cap (tail-bookend)", () => {
    const big = "x".repeat(CHAT_TOOL_OUTPUT_SOFT_CAP_CHARS + 1000);
    let turns = applyEvent(withAssistantTurn(), {
      session_id: sid,
      type: "tool_call_start",
      message_id: "a1",
      tool_call_id: "t1",
      tool_name: "Bash",
      tool_input_json: "{}",
    });
    turns = applyEvent(turns, {
      session_id: sid,
      type: "tool_output_delta",
      tool_call_id: "t1",
      delta: big,
    });
    const tc = turns[0].toolCalls[0];
    expect(tc.output).toHaveLength(CHAT_TOOL_OUTPUT_SOFT_CAP_CHARS);
    expect(tc.rawLength).toBe(big.length);
  });

  it("attaches an error message to the in-flight assistant turn on error event", () => {
    let turns = applyEvent(withAssistantTurn(), {
      session_id: sid,
      type: "token",
      message_id: "a1",
      delta: "partial",
    });
    turns = applyEvent(turns, {
      session_id: sid,
      type: "error",
      message: "boom",
      fatal: false,
    });
    expect(turns[0]).toMatchObject({ id: "a1", error: "boom", complete: true });
  });
});

describe("ingestFrame — replay cursor", () => {
  it("ignores frames with seq <= lastSeq", () => {
    resetConversation("ses_a");
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 1,
      event: { session_id: "ses_a", type: "user_message", message_id: "u1", content: "a" },
    });
    expect(conversationStore.turns).toHaveLength(1);
    expect(conversationStore.lastSeq).toBe(1);
    // Replay of the same frame — no duplicate row.
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 1,
      event: { session_id: "ses_a", type: "user_message", message_id: "u1", content: "a" },
    });
    expect(conversationStore.turns).toHaveLength(1);
  });
});

describe("ingestFrame — pendingApproval", () => {
  it("sets pendingApproval on approval_request", () => {
    resetConversation("ses_a");
    expect(conversationStore.pendingApproval).toBeNull();
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 1,
      event: {
        session_id: "ses_a",
        type: "approval_request",
        request_id: "req_1",
        tool_name: "Bash",
        tool_input_json: '{"cmd":"ls"}',
      },
    });
    expect(conversationStore.pendingApproval).toMatchObject({
      requestId: "req_1",
      toolName: "Bash",
      toolInputJson: '{"cmd":"ls"}',
    });
  });

  it("clears pendingApproval on approval_resolved with matching request_id", () => {
    resetConversation("ses_a");
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 1,
      event: {
        session_id: "ses_a",
        type: "approval_request",
        request_id: "req_1",
        tool_name: "Read",
        tool_input_json: "{}",
      },
    });
    expect(conversationStore.pendingApproval).not.toBeNull();
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 2,
      event: {
        session_id: "ses_a",
        type: "approval_resolved",
        request_id: "req_1",
        approved: true,
      },
    });
    expect(conversationStore.pendingApproval).toBeNull();
  });

  it("does NOT clear pendingApproval on approval_resolved with mismatched request_id", () => {
    resetConversation("ses_a");
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 1,
      event: {
        session_id: "ses_a",
        type: "approval_request",
        request_id: "req_1",
        tool_name: "Edit",
        tool_input_json: "{}",
      },
    });
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 2,
      event: {
        session_id: "ses_a",
        type: "approval_resolved",
        request_id: "req_other",
        approved: false,
      },
    });
    expect(conversationStore.pendingApproval?.requestId).toBe("req_1");
  });

  it("clears pendingApproval on resetConversation", () => {
    resetConversation("ses_a");
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 1,
      event: {
        session_id: "ses_a",
        type: "approval_request",
        request_id: "req_1",
        tool_name: "Bash",
        tool_input_json: "{}",
      },
    });
    expect(conversationStore.pendingApproval).not.toBeNull();
    resetConversation("ses_b");
    expect(conversationStore.pendingApproval).toBeNull();
  });
});

describe("hydrateTurns", () => {
  it("loads persisted MessageOut rows into typed MessageTurnView", () => {
    hydrateTurns("ses_a", [
      {
        id: "u1",
        session_id: "ses_a",
        role: "user",
        content: "hi",
        created_at: "2026-01-01T00:00:00Z",
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
      {
        id: "a1",
        session_id: "ses_a",
        role: "assistant",
        content: "hello",
        created_at: "2026-01-01T00:00:01Z",
        executor_model: "sonnet",
        advisor_model: null,
        effort_level: "med",
        routing_source: "tag_rule",
        routing_reason: "matched bearings/architect",
        matched_rule_id: 1,
        executor_input_tokens: 10,
        executor_output_tokens: 20,
        advisor_input_tokens: null,
        advisor_output_tokens: null,
        advisor_calls_count: 0,
        cache_read_tokens: null,
        input_tokens: null,
        output_tokens: null,
      },
    ]);
    expect(conversationStore.turns).toHaveLength(2);
    expect(conversationStore.turns[1].routing?.executorModel).toBe("sonnet");
  });
});
