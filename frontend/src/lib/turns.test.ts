import { describe, expect, it } from 'vitest';
import type { Message } from '$lib/api';
import type { LiveToolCall } from '$lib/stores/conversation.svelte';
import { buildTurns, type TurnsInput } from './turns';

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
