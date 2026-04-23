/**
 * Tests for the `tool_output_delta` reducer path and the
 * `capToolOutput` helper. Covers the four gotchas the streaming
 * design has to handle as invariants:
 *   1. Ordering — deltas after `tool_call_end` are dropped.
 *   2. Append — multiple deltas concatenate in order.
 *   3. Memory cap — runaway output head-truncates at
 *      TOOL_OUTPUT_CAP_CHARS with a marker.
 *   4. (Persistence is a backend concern; covered by test_store.py.)
 *
 * Tests use unique session IDs per case so the singleton
 * `ConversationStore`'s per-session state stays isolated.
 */

import { describe, expect, it } from 'vitest';

import type { AgentEvent } from '$lib/api';
import {
  TOOL_OUTPUT_CAP_CHARS,
  capToolOutput,
  conversation
} from './conversation.svelte';

function startCall(sessionId: string, toolCallId: string, name = 'Bash'): AgentEvent {
  return {
    type: 'tool_call_start',
    session_id: sessionId,
    tool_call_id: toolCallId,
    name,
    input: {}
  };
}

function delta(sessionId: string, toolCallId: string, text: string): AgentEvent {
  return {
    type: 'tool_output_delta',
    session_id: sessionId,
    tool_call_id: toolCallId,
    delta: text
  };
}

function endCall(
  sessionId: string,
  toolCallId: string,
  output: string | null,
  ok = true
): AgentEvent {
  return {
    type: 'tool_call_end',
    session_id: sessionId,
    tool_call_id: toolCallId,
    ok,
    output,
    error: null
  };
}

function uniqueSession(tag: string): string {
  return `test-${tag}-${Math.random().toString(36).slice(2)}`;
}

describe('capToolOutput', () => {
  it('passes short strings through unchanged', () => {
    const { output, truncated } = capToolOutput('short');
    expect(output).toBe('short');
    expect(truncated).toBe(false);
  });

  it('head-truncates over-cap strings, preserving the tail', () => {
    const huge = 'a'.repeat(TOOL_OUTPUT_CAP_CHARS + 1000);
    const { output, truncated } = capToolOutput(huge);
    expect(truncated).toBe(true);
    expect(output.length).toBeLessThanOrEqual(TOOL_OUTPUT_CAP_CHARS + 100);
    // Last char must be from the tail (index N-1 of the original), so
    // the terminal-semantics "show me the recent output" holds.
    expect(output.endsWith('a')).toBe(true);
    expect(output.startsWith('…[truncated')).toBe(true);
  });

  it('reports exact dropped-char count in the marker', () => {
    const huge = 'x'.repeat(TOOL_OUTPUT_CAP_CHARS + 42);
    const { output } = capToolOutput(huge);
    expect(output).toContain('truncated 42');
  });
});

describe('tool_output_delta reducer', () => {
  it('appends a single delta to a running call', () => {
    const sid = uniqueSession('append-single');
    conversation.sessionId = sid;
    conversation.handleEvent(startCall(sid, 'tc-1'));
    conversation.handleEvent(delta(sid, 'tc-1', 'hello\n'));
    const tc = conversation.toolCalls.find((t) => t.id === 'tc-1');
    expect(tc?.output).toBe('hello\n');
    expect(tc?.outputTruncated).toBe(false);
    expect(tc?.finishedAt).toBe(null);
  });

  it('concatenates multiple deltas in arrival order', () => {
    const sid = uniqueSession('append-multi');
    conversation.sessionId = sid;
    conversation.handleEvent(startCall(sid, 'tc-2'));
    conversation.handleEvent(delta(sid, 'tc-2', 'line 1\n'));
    conversation.handleEvent(delta(sid, 'tc-2', 'line 2\n'));
    conversation.handleEvent(delta(sid, 'tc-2', 'line 3\n'));
    const tc = conversation.toolCalls.find((t) => t.id === 'tc-2');
    expect(tc?.output).toBe('line 1\nline 2\nline 3\n');
  });

  it('drops deltas that arrive after tool_call_end (ordering guard)', () => {
    const sid = uniqueSession('ordering');
    conversation.sessionId = sid;
    conversation.handleEvent(startCall(sid, 'tc-3'));
    conversation.handleEvent(delta(sid, 'tc-3', 'live\n'));
    conversation.handleEvent(endCall(sid, 'tc-3', 'live\ndone\n'));
    // A late delta — replay after reconnect could deliver this.
    conversation.handleEvent(delta(sid, 'tc-3', 'GHOST\n'));
    const tc = conversation.toolCalls.find((t) => t.id === 'tc-3');
    expect(tc?.output).toBe('live\ndone\n');
    expect(tc?.finishedAt).not.toBe(null);
  });

  it('ignores deltas for unknown tool call ids', () => {
    const sid = uniqueSession('unknown');
    conversation.sessionId = sid;
    // No start emitted; the delta should no-op rather than crash.
    expect(() =>
      conversation.handleEvent(delta(sid, 'never-started', 'x'))
    ).not.toThrow();
    expect(conversation.toolCalls).toEqual([]);
  });

  it('does not interfere across tool calls in the same session', () => {
    const sid = uniqueSession('isolation');
    conversation.sessionId = sid;
    conversation.handleEvent(startCall(sid, 'tc-a'));
    conversation.handleEvent(startCall(sid, 'tc-b'));
    conversation.handleEvent(delta(sid, 'tc-a', 'A\n'));
    conversation.handleEvent(delta(sid, 'tc-b', 'B\n'));
    conversation.handleEvent(delta(sid, 'tc-a', 'A2\n'));
    const a = conversation.toolCalls.find((t) => t.id === 'tc-a');
    const b = conversation.toolCalls.find((t) => t.id === 'tc-b');
    expect(a?.output).toBe('A\nA2\n');
    expect(b?.output).toBe('B\n');
  });

  it('head-truncates when cumulative deltas exceed the cap', () => {
    const sid = uniqueSession('cap');
    conversation.sessionId = sid;
    conversation.handleEvent(startCall(sid, 'tc-huge'));
    // Two feeds summing to just-over-cap. Use a repeating marker so
    // we can assert the tail survived.
    const firstChunk = 'a'.repeat(TOOL_OUTPUT_CAP_CHARS - 10);
    const secondChunk = 'B'.repeat(100);
    conversation.handleEvent(delta(sid, 'tc-huge', firstChunk));
    conversation.handleEvent(delta(sid, 'tc-huge', secondChunk));
    const tc = conversation.toolCalls.find((t) => t.id === 'tc-huge');
    expect(tc?.outputTruncated).toBe(true);
    expect(tc?.output).not.toBe(null);
    // The recent content (B's) must survive; that's terminal semantics.
    expect(tc?.output?.endsWith('B'.repeat(100))).toBe(true);
    // Truncation marker present.
    expect(tc?.output?.startsWith('…[truncated')).toBe(true);
    // outputTruncated is sticky once set — later small deltas don't clear it.
    conversation.handleEvent(delta(sid, 'tc-huge', '\ndone\n'));
    const after = conversation.toolCalls.find((t) => t.id === 'tc-huge');
    expect(after?.outputTruncated).toBe(true);
  });

  it('tool_call_end applies the cap to the canonical final output too', () => {
    const sid = uniqueSession('end-cap');
    conversation.sessionId = sid;
    conversation.handleEvent(startCall(sid, 'tc-finalhuge'));
    const huge = 'z'.repeat(TOOL_OUTPUT_CAP_CHARS + 500);
    conversation.handleEvent(endCall(sid, 'tc-finalhuge', huge));
    const tc = conversation.toolCalls.find((t) => t.id === 'tc-finalhuge');
    expect(tc?.outputTruncated).toBe(true);
    expect(tc?.output?.length).toBeLessThanOrEqual(TOOL_OUTPUT_CAP_CHARS + 100);
  });
});

describe('approval reducer', () => {
  function approvalRequest(
    sessionId: string,
    requestId: string,
    toolName = 'ExitPlanMode'
  ): AgentEvent {
    return {
      type: 'approval_request',
      session_id: sessionId,
      request_id: requestId,
      tool_name: toolName,
      input: { plan: '# do stuff' },
      tool_use_id: 'tu_1'
    };
  }

  function approvalResolved(
    sessionId: string,
    requestId: string,
    decision: 'allow' | 'deny' = 'allow'
  ): AgentEvent {
    return {
      type: 'approval_resolved',
      session_id: sessionId,
      request_id: requestId,
      decision
    };
  }

  it('approval_request populates pendingApproval', () => {
    const sid = uniqueSession('approval-req');
    conversation.sessionId = sid;
    conversation.handleEvent(approvalRequest(sid, 'req-a'));
    expect(conversation.pendingApproval?.request_id).toBe('req-a');
    expect(conversation.pendingApproval?.tool_name).toBe('ExitPlanMode');
  });

  it('approval_resolved with matching id clears the modal', () => {
    const sid = uniqueSession('approval-clear');
    conversation.sessionId = sid;
    conversation.handleEvent(approvalRequest(sid, 'req-b'));
    conversation.handleEvent(approvalResolved(sid, 'req-b', 'deny'));
    expect(conversation.pendingApproval).toBe(null);
  });

  it('approval_resolved for a different id leaves the modal up', () => {
    const sid = uniqueSession('approval-mismatch');
    conversation.sessionId = sid;
    conversation.handleEvent(approvalRequest(sid, 'req-c'));
    conversation.handleEvent(approvalResolved(sid, 'req-other', 'allow'));
    expect(conversation.pendingApproval?.request_id).toBe('req-c');
  });

  it('clearPendingApproval drops the modal only when the id matches', () => {
    const sid = uniqueSession('approval-optimistic');
    conversation.sessionId = sid;
    conversation.handleEvent(approvalRequest(sid, 'req-d'));
    conversation.clearPendingApproval(sid, 'req-wrong');
    expect(conversation.pendingApproval?.request_id).toBe('req-d');
    conversation.clearPendingApproval(sid, 'req-d');
    expect(conversation.pendingApproval).toBe(null);
  });
});

describe('todo_write_update reducer', () => {
  function todoUpdate(
    sessionId: string,
    todos: Array<{
      content: string;
      active_form: string | null;
      status: 'pending' | 'in_progress' | 'completed';
    }>
  ): AgentEvent {
    return {
      type: 'todo_write_update',
      session_id: sessionId,
      todos
    };
  }

  it('todos is null before any todo_write_update fires', () => {
    const sid = uniqueSession('todos-initial');
    conversation.sessionId = sid;
    // Kick the per-session state into existence without a TodoWrite.
    conversation.handleEvent(startCall(sid, 'tc-seed'));
    expect(conversation.todos).toBe(null);
  });

  it('first update assigns the full list (no prior state to merge)', () => {
    const sid = uniqueSession('todos-first');
    conversation.sessionId = sid;
    conversation.handleEvent(
      todoUpdate(sid, [
        { content: 'Read the spec', active_form: 'Reading the spec', status: 'in_progress' },
        { content: 'Write the code', active_form: 'Writing the code', status: 'pending' }
      ])
    );
    expect(conversation.todos).toHaveLength(2);
    expect(conversation.todos?.[0].status).toBe('in_progress');
    expect(conversation.todos?.[0].active_form).toBe('Reading the spec');
  });

  it('subsequent update fully replaces the list (no per-item merge)', () => {
    const sid = uniqueSession('todos-replace');
    conversation.sessionId = sid;
    conversation.handleEvent(
      todoUpdate(sid, [
        { content: 'A', active_form: null, status: 'in_progress' },
        { content: 'B', active_form: null, status: 'pending' }
      ])
    );
    conversation.handleEvent(
      todoUpdate(sid, [
        { content: 'A', active_form: null, status: 'completed' },
        { content: 'B', active_form: null, status: 'in_progress' },
        { content: 'C', active_form: null, status: 'pending' }
      ])
    );
    expect(conversation.todos).toHaveLength(3);
    expect(conversation.todos?.[0].status).toBe('completed');
    expect(conversation.todos?.[2].content).toBe('C');
  });

  it('empty todos array is distinct from null (explicit clear semantics)', () => {
    const sid = uniqueSession('todos-empty');
    conversation.sessionId = sid;
    conversation.handleEvent(
      todoUpdate(sid, [{ content: 'x', active_form: null, status: 'pending' }])
    );
    expect(conversation.todos).toHaveLength(1);
    conversation.handleEvent(todoUpdate(sid, []));
    expect(conversation.todos).toEqual([]);
    // null would mean "never invoked"; empty means "explicitly cleared".
    expect(conversation.todos).not.toBe(null);
  });

  it('todo_write_update for one session does not leak into another', () => {
    const sidA = uniqueSession('todos-iso-a');
    const sidB = uniqueSession('todos-iso-b');
    conversation.sessionId = sidA;
    conversation.handleEvent(
      todoUpdate(sidA, [{ content: 'A-task', active_form: null, status: 'in_progress' }])
    );
    // Event for a different session should not touch the active view.
    conversation.handleEvent(
      todoUpdate(sidB, [{ content: 'B-task', active_form: null, status: 'pending' }])
    );
    expect(conversation.todos).toHaveLength(1);
    expect(conversation.todos?.[0].content).toBe('A-task');
    conversation.sessionId = sidB;
    expect(conversation.todos?.[0].content).toBe('B-task');
  });
});

describe('loadingInitial flag', () => {
  // We don't exercise `conversation.load()` here (that would require
  // mocking $lib/api at the module boundary — the agent.svelte tests
  // show the pattern, not worth duplicating for one field). The
  // interesting invariants are that the flag is per-session and that
  // the derived getter follows the active session — a race-safety
  // property for rapid A→B session clicks.

  it('defaults to false for a freshly-seeded session state', () => {
    const sid = uniqueSession('loading-default');
    conversation.sessionId = sid;
    // Any handleEvent call seeds state via ensureState; pick a no-op
    // for an unknown tool id so we don't actually mutate anything
    // else on the state.
    conversation.handleEvent(delta(sid, 'never-started', 'x'));
    expect(conversation.loadingInitial).toBe(false);
  });

  it('returns false when no session is selected', () => {
    conversation.sessionId = null;
    expect(conversation.loadingInitial).toBe(false);
  });
});
