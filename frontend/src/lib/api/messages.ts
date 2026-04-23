/**
 * Message mutation client (Phase 8 of docs/context-menu-plan.md).
 *
 * Thin wrapper over `PATCH /api/messages/{id}`, the only message
 * mutation the server exposes. Two flag columns are mutable: `pinned`
 * (UX only) and `hidden_from_context` (drops the row from the prompt
 * context window assembled for the next agent turn). Content, thinking,
 * and token counts stay immutable — editing a persisted turn would
 * desync the SDK's view of the conversation from the DB.
 *
 * The `MessagePatchBody` shape mirrors the Pydantic model — both
 * fields optional, omit-to-skip. The `message.pin` and
 * `message.hide_from_context` context-menu handlers both call this.
 */

import type { Message } from './sessions';
import { jsonFetch } from './core';

export type MessagePatchBody = {
  pinned?: boolean;
  hidden_from_context?: boolean;
};

export function patchMessage(
  messageId: string,
  body: MessagePatchBody,
  fetchImpl: typeof fetch = fetch
): Promise<Message> {
  return jsonFetch<Message>(fetchImpl, `/api/messages/${messageId}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body)
  });
}
