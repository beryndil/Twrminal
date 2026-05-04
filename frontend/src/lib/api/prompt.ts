/**
 * Typed client for ``POST /api/sessions/{id}/prompt`` — the composer's
 * submit surface (``src/bearings/web/routes/sessions.py``;
 * ``docs/behavior/prompt-endpoint.md``).
 *
 * The endpoint returns ``202 Accepted`` with ``{ queued: true,
 * session_id }``; the client awaits that ack so the composer can clear
 * its draft only after the runtime has accepted the prompt for queueing.
 * Live deltas (the assistant turn) arrive over the per-session
 * WebSocket plumbed in ``agent.svelte.ts`` — the composer does not
 * receive them directly.
 */
import { sessionPromptEndpoint } from "../config";
import { postJson } from "./client";

/**
 * Wire shape for the 202 Accepted ack — one-to-one with
 * :class:`bearings.web.models.sessions.PromptAck`. Unexported because
 * callers only care about the resolution (queued vs thrown ApiError);
 * the shape is internal to this module's typing.
 */
interface PromptAck {
  queued: boolean;
  session_id: string;
}

/**
 * Submit ``content`` as a user-role prompt against ``sessionId``. The
 * promise resolves with the ack envelope on 202; on any non-2xx the
 * underlying :class:`ApiError` is rethrown so the caller can branch on
 * ``error.status`` (404 missing, 409 closed, 413 too large, 422
 * validation, 429 rate limited).
 *
 * ``forceAdvisor`` is the G9 per-turn advisor override: when ``true``,
 * the backend prepends the advisor-override instruction to the content
 * it sends to the SDK executor, directing it to call the advisor tool
 * for this turn only.  Set by the ``/advisor`` composer slash-command.
 */
export async function sendPrompt(
  sessionId: string,
  content: string,
  { forceAdvisor = false }: { forceAdvisor?: boolean } = {},
): Promise<PromptAck> {
  const body: Record<string, unknown> = { content };
  if (forceAdvisor) {
    body["force_advisor"] = true;
  }
  return await postJson<PromptAck>(sessionPromptEndpoint(sessionId), body);
}
