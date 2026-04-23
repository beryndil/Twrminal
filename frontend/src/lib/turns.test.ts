import { describe, expect, it } from 'vitest';
import type { Message } from '$lib/api';
import type { LiveToolCall } from '$lib/stores/conversation.svelte';
import {
  buildSettledTurns,
  buildStreamingTail,
  buildTurns,
  type TurnsInput
} from './turns';

function msg(partial: Partial<Message> & Pick<Message, 'id' | 'role' | 'content'>): Message {
  return {
    session_id: 'sess',
    thinking: null,
    created_at: '2026-04-20T00:00:00Z',
    ...partial
  };
}

function call(partial: Partial<LiveToolCall> & Pick<LiveToolCall, 'id' | 'messageId'>): LiveToolCall {
  return {
    name: 'Bash',
    input: {},
    output: null,
    error: null,
    ok: null,
    startedAt: 0,
    finishedAt: null,
    outputTruncated: false,
    ...partial
  };
}

function input(overrides: Partial<TurnsInput> = {}): TurnsInput {
  return {
    messages: [],
    toolCalls: [],
    streamingActive: false,
    streamingMessageId: null,
    streamingThinking: '',
    streamingText: '',
    ...overrides
  };
}

describe('buildTurns', () => {
  it('pairs each user message with the next assistant reply', () => {
    const turns = buildTurns(
      input({
        messages: [
          msg({ id: 'u1', role: 'user', content: 'hi' }),
          msg({ id: 'a1', role: 'assistant', content: 'hello', thinking: 'hm' }),
          msg({ id: 'u2', role: 'user', content: 'again' }),
          msg({ id: 'a2', role: 'assistant', content: 'sure' })
        ]
      })
    );
    expect(turns.map((t) => [t.user?.id, t.assistant?.id])).toEqual([
      ['u1', 'a1'],
      ['u2', 'a2']
    ]);
    expect(turns[0].thinking).toBe('hm');
  });

  it('attaches tool calls by message_id', () => {
    const turns = buildTurns(
      input({
        messages: [
          msg({ id: 'u1', role: 'user', content: 'q' }),
          msg({ id: 'a1', role: 'assistant', content: 'a' })
        ],
        toolCalls: [
          call({ id: 't1', messageId: 'a1' }),
          call({ id: 't2', messageId: 'a1' }),
          call({ id: 't3', messageId: 'other' })
        ]
      })
    );
    expect(turns).toHaveLength(1);
    expect(turns[0].toolCalls.map((t) => t.id)).toEqual(['t1', 't2']);
  });

  it('folds live streaming state into the tail turn', () => {
    const turns = buildTurns(
      input({
        messages: [msg({ id: 'u1', role: 'user', content: 'q' })],
        toolCalls: [call({ id: 't1', messageId: 'live' })],
        streamingActive: true,
        streamingMessageId: 'live',
        streamingThinking: 'pondering',
        streamingText: 'working…'
      })
    );
    expect(turns).toHaveLength(1);
    expect(turns[0].user?.id).toBe('u1');
    expect(turns[0].isStreaming).toBe(true);
    expect(turns[0].streamingContent).toBe('working…');
    expect(turns[0].streamingThinking).toBe('pondering');
    expect(turns[0].toolCalls.map((t) => t.id)).toEqual(['t1']);
  });

  it('keeps an orphan trailing user message as its own open turn', () => {
    const turns = buildTurns(
      input({
        messages: [
          msg({ id: 'u1', role: 'user', content: 'q' }),
          msg({ id: 'a1', role: 'assistant', content: 'a' }),
          msg({ id: 'u2', role: 'user', content: 'pending' })
        ]
      })
    );
    expect(turns).toHaveLength(2);
    expect(turns[1].user?.id).toBe('u2');
    expect(turns[1].assistant).toBeNull();
  });
});

describe('buildSettledTurns (cache)', () => {
  // The cache is keyed on assistant Message identity — reuse the SAME
  // object refs across calls to hit it. This mirrors what Svelte's
  // $state proxy gives us in practice (message objects are mutated
  // in-place, not replaced).
  it('returns reference-stable Turn objects when messages + tool-call order are unchanged', () => {
    const u = msg({ id: 'u1', role: 'user', content: 'q' });
    const a = msg({ id: 'a1', role: 'assistant', content: 'hello' });
    const tc1 = call({ id: 't1', messageId: 'a1' });
    const first = buildSettledTurns([u, a], [tc1]);
    const second = buildSettledTurns([u, a], [tc1]);
    expect(second[0]).toBe(first[0]);
  });

  it('rebuilds the settled turn when a new tool call is attached', () => {
    const u = msg({ id: 'u1', role: 'user', content: 'q' });
    const a = msg({ id: 'a1', role: 'assistant', content: 'hello' });
    const tc1 = call({ id: 't1', messageId: 'a1' });
    const tc2 = call({ id: 't2', messageId: 'a1' });
    const first = buildSettledTurns([u, a], [tc1]);
    const second = buildSettledTurns([u, a], [tc1, tc2]);
    expect(second[0]).not.toBe(first[0]);
    expect(second[0].toolCalls.map((t) => t.id)).toEqual(['t1', 't2']);
  });

  it('rebuilds the settled turn when tool-call order changes', () => {
    const u = msg({ id: 'u1', role: 'user', content: 'q' });
    const a = msg({ id: 'a1', role: 'assistant', content: 'hello' });
    const tc1 = call({ id: 't1', messageId: 'a1' });
    const tc2 = call({ id: 't2', messageId: 'a1' });
    const first = buildSettledTurns([u, a], [tc1, tc2]);
    const second = buildSettledTurns([u, a], [tc2, tc1]);
    expect(second[0]).not.toBe(first[0]);
    expect(second[0].toolCalls.map((t) => t.id)).toEqual(['t2', 't1']);
  });

  it('rebuilds the settled turn when thinking content changes in-place', () => {
    // The assistant object ref is the same, but its `.thinking` was
    // mutated (which happens when the reducer patches a message in
    // place). The cache guard on `thinking` equality catches this.
    const u = msg({ id: 'u1', role: 'user', content: 'q' });
    const a = msg({ id: 'a1', role: 'assistant', content: 'hello', thinking: 'v1' });
    const first = buildSettledTurns([u, a], []);
    a.thinking = 'v2';
    const second = buildSettledTurns([u, a], []);
    expect(second[0]).not.toBe(first[0]);
    expect(second[0].thinking).toBe('v2');
  });
});

describe('buildStreamingTail', () => {
  it('returns null-safe tail that absorbs an open trailing user turn', () => {
    const u = msg({ id: 'u1', role: 'user', content: 'q' });
    const settled = buildSettledTurns([u], []);
    const result = buildStreamingTail(settled, [], 'live', 'pondering', 'working…');
    expect(result).not.toBeNull();
    expect(result!.absorbsLastSettled).toBe(true);
    expect(result!.tail.user?.id).toBe('u1');
    expect(result!.tail.isStreaming).toBe(true);
    expect(result!.tail.streamingContent).toBe('working…');
    expect(result!.tail.streamingThinking).toBe('pondering');
  });

  it('does not absorb when the last settled turn is a closed (user, assistant) pair', () => {
    const u = msg({ id: 'u1', role: 'user', content: 'q' });
    const a = msg({ id: 'a1', role: 'assistant', content: 'done' });
    const settled = buildSettledTurns([u, a], []);
    const result = buildStreamingTail(settled, [], 'live', '', 'next…');
    expect(result).not.toBeNull();
    expect(result!.absorbsLastSettled).toBe(false);
    expect(result!.tail.user).toBeNull();
    expect(result!.tail.isStreaming).toBe(true);
  });

  it('attaches live tool calls whose messageId matches the streaming id', () => {
    const tc1 = call({ id: 't1', messageId: 'live' });
    const tc2 = call({ id: 't2', messageId: 'other' });
    const result = buildStreamingTail([], [tc1, tc2], 'live', '', '');
    expect(result!.tail.toolCalls.map((t) => t.id)).toEqual(['t1']);
  });
});
