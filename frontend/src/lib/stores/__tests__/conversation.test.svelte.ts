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
  hydrateTodos,
  hydrateTokens,
  hydrateTurns,
  hydrateToolCalls,
  ingestFrame,
  resetConversation,
  type MessageTurnView,
} from "../conversation.svelte";
import { CHAT_TOOL_OUTPUT_SOFT_CAP_CHARS, WS_FRAME_KIND_EVENT } from "../../config";
import type { ToolCallOut } from "../../api/messages";

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
  resumed: false,
  seq: 0,
  attachments: [],
  stopped: false,
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
    hydrateTurns("ses_a", {
      items: [
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
          seq: 1,
          pinned: false,
          hidden_from_context: false,
          evaluated_rules: [],
          stopped: false,
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
          seq: 2,
          pinned: false,
          hidden_from_context: false,
          evaluated_rules: [],
          stopped: false,
        },
      ],
      has_more: false,
    });
    expect(conversationStore.turns).toHaveLength(2);
    expect(conversationStore.turns[1].routing?.executorModel).toBe("sonnet");
    expect(conversationStore.hasMore).toBe(false);
    expect(conversationStore.oldestSeq).toBe(1);
  });

  it("sets hasMore and oldestSeq from the page", () => {
    hydrateTurns("ses_b", {
      items: [
        {
          id: "u2",
          session_id: "ses_b",
          role: "user",
          content: "x",
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
          seq: 7,
          pinned: false,
          hidden_from_context: false,
          evaluated_rules: [],
          stopped: false,
        },
      ],
      has_more: true,
    });
    expect(conversationStore.hasMore).toBe(true);
    expect(conversationStore.oldestSeq).toBe(7);
  });
});

// ---------------------------------------------------------------------------
// hydrateToolCalls (gap-cycle-03-012)
// ---------------------------------------------------------------------------

/** Minimal MessageOut stub for test fixtures. */
function makeMsg(id: string, role: "user" | "assistant") {
  return {
    id,
    session_id: "ses_a",
    role,
    content: "x",
    created_at: "2026-01-01T00:00:00Z",
    executor_model: role === "assistant" ? "sonnet" : null,
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
    seq: 1,
    pinned: false,
    hidden_from_context: false,
    evaluated_rules: [],
    stopped: false,
  };
}

function makeToolCallOut(
  id: string,
  messageId: string,
  overrides: Partial<ToolCallOut> = {},
): ToolCallOut {
  return {
    id,
    session_id: "ses_a",
    message_id: messageId,
    tool_name: "Bash",
    input_json: '{"command":"ls"}',
    output: "file.txt",
    ok: true,
    duration_ms: 10,
    error_message: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("hydrateToolCalls", () => {
  it("attaches tool calls to the matching assistant turn", () => {
    hydrateTurns("ses_a", {
      items: [makeMsg("u1", "user"), makeMsg("a1", "assistant")],
      has_more: false,
    });
    hydrateToolCalls([makeToolCallOut("toolu_1", "a1")]);
    const assistantTurn = conversationStore.turns.find((t) => t.id === "a1");
    expect(assistantTurn?.toolCalls).toHaveLength(1);
    expect(assistantTurn?.toolCalls[0].id).toBe("toolu_1");
    expect(assistantTurn?.toolCalls[0].name).toBe("Bash");
    expect(assistantTurn?.toolCalls[0].done).toBe(true);
    expect(assistantTurn?.toolCalls[0].ok).toBe(true);
  });

  it("does not attach tool calls to user turns", () => {
    hydrateTurns("ses_a", {
      items: [makeMsg("u1", "user"), makeMsg("a1", "assistant")],
      has_more: false,
    });
    // message_id points at user turn — should be ignored
    hydrateToolCalls([makeToolCallOut("toolu_x", "u1")]);
    const userTurn = conversationStore.turns.find((t) => t.id === "u1");
    expect(userTurn?.toolCalls).toHaveLength(0);
  });

  it("preserves turns with existing tool calls (WS replay wins)", () => {
    hydrateTurns("ses_a", {
      items: [makeMsg("a1", "assistant")],
      has_more: false,
    });
    // Simulate WS replay already populated tool calls.
    const wsToolCall = {
      id: "toolu_ws",
      name: "Read",
      inputJson: "{}",
      output: "ws output",
      rawLength: 9,
      done: true,
      ok: true,
      durationMs: 5,
      errorMessage: null,
      liveElapsedMs: 0,
      startedAt: 0,
    };
    conversationStore.turns = conversationStore.turns.map((t) =>
      t.id === "a1" ? { ...t, toolCalls: [wsToolCall] } : t,
    );
    // hydrateToolCalls should not overwrite the WS-populated row.
    hydrateToolCalls([makeToolCallOut("toolu_db", "a1")]);
    const turn = conversationStore.turns.find((t) => t.id === "a1");
    expect(turn?.toolCalls).toHaveLength(1);
    expect(turn?.toolCalls[0].id).toBe("toolu_ws");
  });

  it("applies display cap to long output", () => {
    const longOutput = "x".repeat(CHAT_TOOL_OUTPUT_SOFT_CAP_CHARS + 100);
    hydrateTurns("ses_a", {
      items: [makeMsg("a1", "assistant")],
      has_more: false,
    });
    hydrateToolCalls([makeToolCallOut("toolu_long", "a1", { output: longOutput })]);
    const turn = conversationStore.turns.find((t) => t.id === "a1");
    expect(turn?.toolCalls[0].output.length).toBe(CHAT_TOOL_OUTPUT_SOFT_CAP_CHARS);
    expect(turn?.toolCalls[0].rawLength).toBe(longOutput.length);
  });

  it("no-ops on empty tool_calls array", () => {
    hydrateTurns("ses_a", {
      items: [makeMsg("a1", "assistant")],
      has_more: false,
    });
    hydrateToolCalls([]);
    expect(conversationStore.turns[0].toolCalls).toHaveLength(0);
  });

  it("tool_call_start is idempotent when call already exists from DB hydration", () => {
    // Simulate DB hydration having already set tool calls.
    hydrateTurns("ses_a", {
      items: [makeMsg("a1", "assistant")],
      has_more: false,
    });
    hydrateToolCalls([makeToolCallOut("toolu_dup", "a1", { output: "db output" })]);
    // Now WS replay sends tool_call_start for the same id — should skip.
    const turns = applyEvent(conversationStore.turns, {
      type: "tool_call_start",
      session_id: "ses_a",
      message_id: "a1",
      tool_call_id: "toolu_dup",
      tool_name: "Bash",
      tool_input_json: "{}",
    });
    const turn = turns.find((t) => t.id === "a1");
    expect(turn?.toolCalls).toHaveLength(1); // still 1, not 2
    expect(turn?.toolCalls[0].id).toBe("toolu_dup");
  });

  it("tool_output_delta is skipped for done=true calls (hydrated)", () => {
    hydrateTurns("ses_a", {
      items: [makeMsg("a1", "assistant")],
      has_more: false,
    });
    hydrateToolCalls([makeToolCallOut("toolu_done", "a1", { output: "final" })]);
    // WS replay sends a delta — should not append to done call.
    const turns = applyEvent(conversationStore.turns, {
      type: "tool_output_delta",
      session_id: "ses_a",
      tool_call_id: "toolu_done",
      delta: " extra",
    });
    const turn = turns.find((t) => t.id === "a1");
    expect(turn?.toolCalls[0].output).toBe("final"); // unchanged
  });
});

// ---------------------------------------------------------------------------
// LiveTodos hydration (gap-cycle-03-013)
// ---------------------------------------------------------------------------

const sampleTodos = [
  { id: "t1", content: "write tests", status: "in_progress" as const, priority: "high" as const },
  { id: "t2", content: "ship it", status: "pending" as const, priority: "medium" as const },
];

describe("hydrateTodos — seed before WS event", () => {
  it("sets liveTodos from a JSON string before any WS event arrives", () => {
    expect(conversationStore.liveTodos).toHaveLength(0);
    hydrateTodos(JSON.stringify(sampleTodos));
    expect(conversationStore.liveTodos).toHaveLength(2);
    expect(conversationStore.liveTodos[0]).toMatchObject({
      id: "t1",
      content: "write tests",
      status: "in_progress",
    });
    expect(conversationStore.liveTodos[1]).toMatchObject({
      id: "t2",
      content: "ship it",
      status: "pending",
    });
  });

  it("silently ignores malformed JSON and leaves liveTodos unchanged", () => {
    hydrateTodos(JSON.stringify(sampleTodos));
    hydrateTodos("not-json{{");
    // liveTodos unchanged from the previous valid seed
    expect(conversationStore.liveTodos).toHaveLength(2);
  });

  it("later todo_write_update WS event replaces the hydrated seed", () => {
    hydrateTodos(JSON.stringify(sampleTodos));
    expect(conversationStore.liveTodos).toHaveLength(2);

    const replacement = [{ content: "new task", status: "pending" as const }];
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 1,
      event: {
        type: "todo_write_update",
        session_id: "ses_a",
        todos_json: JSON.stringify(replacement),
      },
    });
    expect(conversationStore.liveTodos).toHaveLength(1);
    expect(conversationStore.liveTodos[0]).toMatchObject({
      content: "new task",
      status: "pending",
    });
  });

  it("resetConversation clears the hydrated liveTodos", () => {
    hydrateTodos(JSON.stringify(sampleTodos));
    expect(conversationStore.liveTodos).toHaveLength(2);
    resetConversation(null);
    expect(conversationStore.liveTodos).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Token totals hydration (gap-cycle-13-003)
// ---------------------------------------------------------------------------

const sampleTokenTotals = {
  input: 1000,
  output: 500,
  cache_read: 200,
  cache_creation: 0,
};

/** Minimal message_complete frame for token accumulation tests. */
function makeMessageComplete(
  messageId: string,
  overrides: {
    executor_input_tokens?: number | null;
    executor_output_tokens?: number | null;
    cache_read_tokens?: number | null;
  } = {},
) {
  return {
    kind: WS_FRAME_KIND_EVENT as typeof WS_FRAME_KIND_EVENT,
    seq: Math.floor(Math.random() * 1_000_000) + 1,
    event: {
      session_id: sid,
      type: "message_complete" as const,
      message_id: messageId,
      content: "",
      executor_input_tokens: overrides.executor_input_tokens ?? 100,
      executor_output_tokens: overrides.executor_output_tokens ?? 50,
      advisor_input_tokens: null,
      advisor_output_tokens: null,
      advisor_calls_count: 0,
      cache_read_tokens: overrides.cache_read_tokens ?? null,
      input_tokens: null,
      output_tokens: null,
    },
  };
}

describe("hydrateTokens — seed before WS events", () => {
  it("sets all four session token counters from the DB aggregate", () => {
    expect(conversationStore.sessionInputTokens).toBe(0);
    expect(conversationStore.sessionOutputTokens).toBe(0);
    expect(conversationStore.sessionCacheReadTokens).toBe(0);
    expect(conversationStore.sessionCacheWriteTokens).toBe(0);
    hydrateTokens(sampleTokenTotals);
    expect(conversationStore.sessionInputTokens).toBe(1000);
    expect(conversationStore.sessionOutputTokens).toBe(500);
    expect(conversationStore.sessionCacheReadTokens).toBe(200);
    expect(conversationStore.sessionCacheWriteTokens).toBe(0);
  });

  it("sets _tokensHydratedPending so WS replay is suppressed", () => {
    hydrateTokens(sampleTokenTotals);
    expect(conversationStore._tokensHydratedPending).toBe(true);
  });

  it("WS message_complete events during replay do NOT add to hydrated totals", () => {
    resetConversation(sid);
    hydrateTokens(sampleTokenTotals);
    // Simulate WS replay delivering a historical message_complete.
    ingestFrame(makeMessageComplete("a1"));
    // Token counters must remain at the hydrated values (no accumulation).
    expect(conversationStore.sessionInputTokens).toBe(1000);
    expect(conversationStore.sessionOutputTokens).toBe(500);
  });

  it("runner_status clears _tokensHydratedPending", () => {
    resetConversation(sid);
    hydrateTokens(sampleTokenTotals);
    expect(conversationStore._tokensHydratedPending).toBe(true);
    // runner_status is synthetic (seq=0) — goes through the pre-dedup path.
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 0,
      event: {
        type: "runner_status",
        session_id: sid,
        streaming_active: false,
        current_turn_id: null,
      },
    });
    expect(conversationStore._tokensHydratedPending).toBe(false);
  });

  it("message_complete after runner_status adds delta on top of hydrated totals", () => {
    resetConversation(sid);
    hydrateTokens(sampleTokenTotals);
    // End of replay.
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 0,
      event: {
        type: "runner_status",
        session_id: sid,
        streaming_active: false,
        current_turn_id: null,
      },
    });
    // New live turn completes.
    ingestFrame(
      makeMessageComplete("a_new", { executor_input_tokens: 50, executor_output_tokens: 25 }),
    );
    expect(conversationStore.sessionInputTokens).toBe(1050);
    expect(conversationStore.sessionOutputTokens).toBe(525);
  });

  it("cache_read counter included in hydration and live accumulation", () => {
    resetConversation(sid);
    hydrateTokens({ input: 0, output: 0, cache_read: 400, cache_creation: 0 });
    // End of replay.
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 0,
      event: {
        type: "runner_status",
        session_id: sid,
        streaming_active: false,
        current_turn_id: null,
      },
    });
    // New live turn with cache read.
    ingestFrame(
      makeMessageComplete("a_cache", {
        executor_input_tokens: 10,
        executor_output_tokens: 5,
        cache_read_tokens: 100,
      }),
    );
    expect(conversationStore.sessionCacheReadTokens).toBe(500);
  });

  it("resetConversation clears hydrated token counters and pending flag", () => {
    hydrateTokens(sampleTokenTotals);
    expect(conversationStore.sessionInputTokens).toBe(1000);
    expect(conversationStore._tokensHydratedPending).toBe(true);
    resetConversation(null);
    expect(conversationStore.sessionInputTokens).toBe(0);
    expect(conversationStore.sessionOutputTokens).toBe(0);
    expect(conversationStore.sessionCacheReadTokens).toBe(0);
    expect(conversationStore.sessionCacheWriteTokens).toBe(0);
    expect(conversationStore._tokensHydratedPending).toBe(false);
  });

  it("without hydration, WS accumulation works as before (no regression)", () => {
    resetConversation(sid);
    // No hydrateTokens call — _tokensHydratedPending stays false.
    // runner_status fires (end of replay) — flag already false.
    ingestFrame({
      kind: WS_FRAME_KIND_EVENT,
      seq: 0,
      event: {
        type: "runner_status",
        session_id: sid,
        streaming_active: false,
        current_turn_id: null,
      },
    });
    ingestFrame(
      makeMessageComplete("a1", { executor_input_tokens: 200, executor_output_tokens: 80 }),
    );
    expect(conversationStore.sessionInputTokens).toBe(200);
    expect(conversationStore.sessionOutputTokens).toBe(80);
  });
});
