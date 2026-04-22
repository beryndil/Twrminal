import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';

import type { Message, Session } from '$lib/api';
import { conversation } from '$lib/stores/conversation.svelte';
import { sessions } from '$lib/stores/sessions.svelte';

// Controllable stand-in for the agent singleton. ChecklistChat reads
// `agent.state`, `agent.sessionId`, and calls `agent.connect(sid)`,
// `agent.send(text)`, `agent.stop()`, `agent.close()`. The stub lets
// each test drive those surfaces without opening a real WebSocket.
const connect = vi.fn(async (_sid: string) => {});
const send = vi.fn((_text: string) => true);
const stop = vi.fn(() => true);
const close = vi.fn(() => {});
const agentStub: {
  state: 'idle' | 'connecting' | 'open' | 'closed' | 'error';
  sessionId: string | null;
  connect: (sid: string) => Promise<void>;
  send: (text: string) => boolean;
  stop: () => boolean;
  close: () => void;
} = {
  state: 'open',
  sessionId: 'sess-cl',
  connect,
  send,
  stop,
  close
};

vi.mock('$lib/agent.svelte', () => ({
  get agent() {
    return agentStub;
  }
}));

const { default: ChecklistChat } = await import('./ChecklistChat.svelte');

function session(overrides: Partial<Session> = {}): Session {
  return {
    id: 'sess-cl',
    created_at: '2026-04-22T00:00:00+00:00',
    updated_at: '2026-04-22T00:00:00+00:00',
    working_dir: '/tmp',
    model: 'claude-opus-4-7',
    title: 'Plan',
    description: null,
    max_budget_usd: null,
    total_cost_usd: 0,
    message_count: 0,
    session_instructions: null,
    permission_mode: null,
    last_context_pct: null,
    last_context_tokens: null,
    last_context_max: null,
    closed_at: null,
    kind: 'checklist',
    checklist_item_id: null,
    last_completed_at: null,
    last_viewed_at: null,
    tag_ids: [],
    ...overrides
  };
}

function message(overrides: Partial<Message> = {}): Message {
  return {
    id: 'msg-1',
    session_id: 'sess-cl',
    role: 'assistant',
    content: 'Hello',
    thinking: null,
    created_at: '2026-04-22T00:00:10+00:00',
    input_tokens: null,
    output_tokens: null,
    cache_read_tokens: null,
    cache_creation_tokens: null,
    ...overrides
  };
}

// Seed the conversation store's per-session state by calling its
// public surface rather than reaching into the private map.
function seedConversation(sid: string, messages: Message[]): void {
  conversation.sessionId = sid;
  for (const m of messages) {
    if (m.role === 'user') {
      conversation.pushUserMessage(sid, m.content);
    } else {
      // Assistant messages need to flow through handleEvent —
      // simulate a complete turn so the store records the row.
      conversation.handleEvent({
        type: 'message_start',
        session_id: sid,
        message_id: m.id
      } as never);
      conversation.handleEvent({
        type: 'token',
        session_id: sid,
        message_id: m.id,
        text: m.content
      } as never);
      conversation.handleEvent({
        type: 'message_complete',
        session_id: sid,
        message_id: m.id,
        cost_usd: 0,
        input_tokens: 0,
        output_tokens: 0,
        cache_read_tokens: 0,
        cache_creation_tokens: 0
      } as never);
    }
  }
}

beforeEach(() => {
  connect.mockClear();
  send.mockClear();
  stop.mockClear();
  close.mockClear();
  agentStub.state = 'open';
  agentStub.sessionId = 'sess-cl';
  sessions.list = [session()];
  sessions.selectedId = 'sess-cl';
  // Reset the conversation store between tests by pointing it at a
  // fresh session id so stale messages don't bleed between tests.
  conversation.sessionId = null;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  sessions.list = [];
  sessions.selectedId = null;
});

describe('ChecklistChat', () => {
  it('renders the panel header and an empty-state hint when there are no messages', () => {
    const { getByTestId } = render(ChecklistChat);
    expect(getByTestId('checklist-chat')).toBeTruthy();
    // Empty-state copy reassures the user this isn't broken.
    // Whitespace normalisation — the rendered copy wraps across lines.
    const text = getByTestId('checklist-chat-messages').textContent?.replace(/\s+/g, ' ');
    expect(text).toMatch(/current state is injected/i);
  });

  it('calls agent.connect when no socket is yet attached to this session', async () => {
    agentStub.state = 'idle';
    agentStub.sessionId = null;
    render(ChecklistChat);
    await waitFor(() => expect(connect).toHaveBeenCalledWith('sess-cl'));
  });

  it('skips agent.connect when the socket is already open on this session', () => {
    agentStub.state = 'open';
    agentStub.sessionId = 'sess-cl';
    render(ChecklistChat);
    expect(connect).not.toHaveBeenCalled();
  });

  it('renders user and assistant messages with distinct data-testids', async () => {
    seedConversation('sess-cl', [
      message({ id: 'm-u', role: 'user', content: 'What is left?' }),
      message({ id: 'm-a', role: 'assistant', content: 'Three items remain.' })
    ]);
    const { findByTestId } = render(ChecklistChat);
    const userBubble = await findByTestId('checklist-chat-user');
    const asstBubble = await findByTestId('checklist-chat-assistant');
    expect(userBubble.textContent).toMatch(/What is left\?/);
    expect(asstBubble.textContent).toMatch(/Three items remain\./);
  });

  it('sends the draft via agent.send when the Send button is clicked', async () => {
    const { getByTestId } = render(ChecklistChat);
    const input = getByTestId('checklist-chat-input') as HTMLTextAreaElement;
    await fireEvent.input(input, { target: { value: 'look at item 3' } });
    const btn = getByTestId('checklist-chat-send') as HTMLButtonElement;
    await fireEvent.click(btn);
    expect(send).toHaveBeenCalledWith('look at item 3');
  });

  it('submits on Enter and inserts a newline on Shift+Enter', async () => {
    const { getByTestId } = render(ChecklistChat);
    const input = getByTestId('checklist-chat-input') as HTMLTextAreaElement;
    await fireEvent.input(input, { target: { value: 'ping' } });
    // Plain Enter fires send.
    await fireEvent.keyDown(input, { key: 'Enter' });
    expect(send).toHaveBeenCalledWith('ping');
    send.mockClear();
    // Shift+Enter must not fire send.
    await fireEvent.input(input, { target: { value: 'two' } });
    await fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(send).not.toHaveBeenCalled();
  });

  it('disables Send while the draft is empty', async () => {
    const { getByTestId } = render(ChecklistChat);
    const btn = getByTestId('checklist-chat-send') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    const input = getByTestId('checklist-chat-input') as HTMLTextAreaElement;
    await fireEvent.input(input, { target: { value: 'hi' } });
    await waitFor(() => expect(btn.disabled).toBe(false));
  });

  it('disables the input and never sends when the checklist is closed', async () => {
    sessions.list = [session({ closed_at: '2026-04-22T00:05:00+00:00' })];
    const { getByTestId } = render(ChecklistChat);
    const input = getByTestId('checklist-chat-input') as HTMLTextAreaElement;
    expect(input.disabled).toBe(true);
    await fireEvent.input(input, { target: { value: 'q' } });
    await fireEvent.keyDown(input, { key: 'Enter' });
    expect(send).not.toHaveBeenCalled();
  });
});
