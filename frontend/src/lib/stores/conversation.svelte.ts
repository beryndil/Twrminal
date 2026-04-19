import * as api from '$lib/api';

export type LiveToolCall = {
  id: string;
  name: string;
  input: Record<string, unknown>;
  output: string | null;
  error: string | null;
  ok: boolean | null; // null until tool_call_end arrives
  startedAt: number;
  finishedAt: number | null;
};

function hydrateToolCall(row: api.ToolCall): LiveToolCall {
  let parsedInput: Record<string, unknown> = {};
  try {
    parsedInput = JSON.parse(row.input) as Record<string, unknown>;
  } catch {
    // Malformed JSON — show as empty rather than crash the panel.
  }
  const startedAt = new Date(row.started_at).getTime();
  const finishedAt = row.finished_at ? new Date(row.finished_at).getTime() : null;
  const ok = finishedAt === null ? null : row.error === null;
  return {
    id: row.id,
    name: row.name,
    input: parsedInput,
    output: row.output,
    error: row.error,
    ok,
    startedAt,
    finishedAt
  };
}

class ConversationStore {
  sessionId = $state<string | null>(null);
  messages = $state<api.Message[]>([]);
  streamingText = $state('');
  streamingThinking = $state('');
  streamingActive = $state(false);
  toolCalls = $state<LiveToolCall[]>([]);
  totalCost = $state(0);
  highlightQuery = $state('');
  error = $state<string | null>(null);

  async load(sessionId: string): Promise<void> {
    this.sessionId = sessionId;
    this.messages = [];
    this.reset();
    this.error = null;
    try {
      const [session, messages, toolCalls] = await Promise.all([
        api.getSession(sessionId),
        api.listMessages(sessionId),
        api.listToolCalls(sessionId)
      ]);
      this.messages = messages;
      this.toolCalls = toolCalls.map(hydrateToolCall);
      this.totalCost = session.total_cost_usd;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    }
  }

  reset(): void {
    this.streamingText = '';
    this.streamingThinking = '';
    this.streamingActive = false;
    this.toolCalls = [];
  }

  pushUserMessage(sessionId: string, content: string): void {
    this.messages = [
      ...this.messages,
      {
        id: crypto.randomUUID().replaceAll('-', ''),
        session_id: sessionId,
        role: 'user',
        content,
        thinking: null,
        created_at: new Date().toISOString()
      }
    ];
    this.streamingText = '';
    this.streamingThinking = '';
    this.streamingActive = true;
    // Sending a new prompt clears a stale "jumped from search" hint.
    this.highlightQuery = '';
  }

  handleEvent(event: api.AgentEvent): void {
    switch (event.type) {
      case 'token':
        this.streamingText += event.text;
        return;
      case 'thinking':
        this.streamingThinking += event.text;
        return;
      case 'tool_call_start':
        this.toolCalls = [
          ...this.toolCalls,
          {
            id: event.tool_call_id,
            name: event.name,
            input: event.input,
            output: null,
            error: null,
            ok: null,
            startedAt: Date.now(),
            finishedAt: null
          }
        ];
        return;
      case 'tool_call_end':
        this.toolCalls = this.toolCalls.map((tc) =>
          tc.id === event.tool_call_id
            ? {
                ...tc,
                ok: event.ok,
                output: event.output,
                error: event.error,
                finishedAt: Date.now()
              }
            : tc
        );
        return;
      case 'message_complete':
        if (this.streamingText || this.sessionId) {
          this.messages = [
            ...this.messages,
            {
              id: event.message_id,
              session_id: event.session_id,
              role: 'assistant',
              content: this.streamingText,
              thinking: this.streamingThinking || null,
              created_at: new Date().toISOString()
            }
          ];
        }
        if (event.cost_usd !== null) {
          this.totalCost += event.cost_usd;
        }
        this.streamingText = '';
        this.streamingThinking = '';
        this.streamingActive = false;
        return;
      case 'error':
        this.error = event.message;
        this.streamingActive = false;
        return;
      case 'message_start':
      case 'user_message':
        return;
    }
  }
}

export const conversation = new ConversationStore();
