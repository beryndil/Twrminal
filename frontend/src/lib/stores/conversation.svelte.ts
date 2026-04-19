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

class ConversationStore {
  sessionId = $state<string | null>(null);
  messages = $state<api.Message[]>([]);
  streamingText = $state('');
  streamingActive = $state(false);
  toolCalls = $state<LiveToolCall[]>([]);
  error = $state<string | null>(null);

  async load(sessionId: string): Promise<void> {
    this.sessionId = sessionId;
    this.messages = [];
    this.reset();
    this.error = null;
    try {
      this.messages = await api.listMessages(sessionId);
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    }
  }

  reset(): void {
    this.streamingText = '';
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
        created_at: new Date().toISOString()
      }
    ];
    this.streamingText = '';
    this.streamingActive = true;
  }

  handleEvent(event: api.AgentEvent): void {
    switch (event.type) {
      case 'token':
        this.streamingText += event.text;
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
              created_at: new Date().toISOString()
            }
          ];
        }
        this.streamingText = '';
        this.streamingActive = false;
        return;
      case 'error':
        this.error = event.message;
        this.streamingActive = false;
        return;
      case 'user_message':
        return;
    }
  }
}

export const conversation = new ConversationStore();
