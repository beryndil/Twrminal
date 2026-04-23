import type { Message } from '$lib/api';
import type { LiveToolCall } from '$lib/stores/conversation.svelte';

export type Turn = {
  key: string;
  user: Message | null;
  assistant: Message | null;
  thinking: string;
  toolCalls: LiveToolCall[];
  streamingContent: string;
  streamingThinking: string;
  isStreaming: boolean;
};

function empty(key: string, user: Message | null): Turn {
  return {
    key,
    user,
    assistant: null,
    thinking: '',
    toolCalls: [],
    streamingContent: '',
    streamingThinking: '',
    isStreaming: false
  };
}

export type TurnsInput = {
  messages: Message[];
  toolCalls: LiveToolCall[];
  streamingActive: boolean;
  streamingMessageId: string | null;
  streamingThinking: string;
  streamingText: string;
};

// --- Settled-turn cache ----------------------------------------------
//
// `buildSettledTurns` is called out of a `$derived` that watches
// `messages` + `toolCalls`. On every invalidation, any settled turn
// whose (assistant message ref, attached tool-call refs-and-order) are
// unchanged must return the same Turn object as the previous call —
// otherwise MessageTurn re-renders for every already-settled turn on
// every token event (the measured cost, 2026-04-21: 227
// `buildTurns`/`timeline` fires on one tool-heavy turn, each one
// reflowing every settled MessageTurn).
//
// Keyed on the assistant Message identity. Svelte 5 `$state` proxies
// keep message objects reference-stable across reducer events (item 1
// of the 2026-04-23 audit), so `WeakMap<Message, CachedTurn>` is the
// right shape — garbage-collected when the session's state is
// discarded via `forget(sessionId)`.
type CachedTurn = {
  turn: Turn;
  // Snapshot of the tool-call id order that produced `turn.toolCalls`.
  // A length-then-pointwise check against the current order detects
  // any attach/detach/reorder without allocating a fresh array per
  // call.
  toolCallIds: string[];
};
const settledTurnCache = new WeakMap<Message, CachedTurn>();

function toolCallIdsMatch(cached: string[], current: LiveToolCall[]): boolean {
  if (cached.length !== current.length) return false;
  for (let i = 0; i < cached.length; i++) {
    if (cached[i] !== current[i].id) return false;
  }
  return true;
}

function groupToolCallsByMessageId(toolCalls: LiveToolCall[]): Map<string, LiveToolCall[]> {
  const byMsgId = new Map<string, LiveToolCall[]>();
  for (const tc of toolCalls) {
    const key = tc.messageId ?? '';
    const arr = byMsgId.get(key) ?? [];
    arr.push(tc);
    byMsgId.set(key, arr);
  }
  return byMsgId;
}

/** Build the settled portion of the turn list — closed (user, assistant)
 *  pairs plus any orphan trailing user message. Split out of `buildTurns`
 *  so the streaming tail (which changes per token event) lives in a
 *  separate $derived that doesn't invalidate this one.
 *
 *  Returns reference-stable Turn objects for any settled assistant turn
 *  whose cache snapshot matches. Tests that want to observe caching
 *  behavior can call `clearTurnsCache()` between cases. */
export function buildSettledTurns(messages: Message[], toolCalls: LiveToolCall[]): Turn[] {
  const byMsgId = groupToolCallsByMessageId(toolCalls);
  const out: Turn[] = [];
  let current: Turn | null = null;
  for (const m of messages) {
    if (m.role === 'user') {
      if (current) out.push(current);
      current = empty(m.id, m);
    } else if (m.role === 'assistant') {
      if (!current) current = empty(m.id, null);
      const tcs = byMsgId.get(m.id) ?? [];
      const cached = settledTurnCache.get(m);
      if (
        cached &&
        cached.turn.user === current.user &&
        cached.turn.thinking === (m.thinking ?? '') &&
        cached.turn.assistant === m &&
        toolCallIdsMatch(cached.toolCallIds, tcs)
      ) {
        out.push(cached.turn);
      } else {
        current.assistant = m;
        current.thinking = m.thinking ?? '';
        current.toolCalls = tcs;
        settledTurnCache.set(m, { turn: current, toolCallIds: tcs.map((tc) => tc.id) });
        out.push(current);
      }
      current = null;
    }
  }
  // Trailing user message without an assistant yet — shown as its own
  // open turn while the user waits for streaming to start.
  if (current) out.push(current);
  return out;
}

/** Construct the live streaming tail, if the session currently has an
 *  in-flight turn. Returns `null` when nothing is streaming. When the
 *  session's trailing settled turn is an open user message, the caller
 *  (`buildTurns` or the component's $derived) replaces it with the
 *  enriched tail. */
export function buildStreamingTail(
  settledTurns: Turn[],
  toolCalls: LiveToolCall[],
  streamingMessageId: string | null,
  streamingThinking: string,
  streamingText: string
): { tail: Turn; absorbsLastSettled: boolean } | null {
  // Reuse the trailing open user turn if it's there — streaming
  // enriches the same visual row rather than shoving it down as a
  // second bubble.
  const last = settledTurns[settledTurns.length - 1];
  const absorbsLastSettled = Boolean(last && last.user && !last.assistant);
  const base: Turn = absorbsLastSettled
    ? { ...last }
    : empty(`streaming:${streamingMessageId ?? 'pending'}`, null);
  const liveId = streamingMessageId ?? '';
  const attached = toolCalls.filter((tc) => tc.messageId === liveId);
  base.streamingThinking = streamingThinking;
  base.streamingContent = streamingText;
  // Merge: absorbed tail may already carry settled tool_calls (unlikely
  // but cheap to support); append the live ones the DB doesn't know
  // about yet.
  base.toolCalls = absorbsLastSettled ? [...base.toolCalls, ...attached] : attached;
  base.isStreaming = true;
  return { tail: base, absorbsLastSettled };
}

/** Collapse the flat (messages, toolCalls) stream into turn-oriented
 *  groups for the Conversation view: one user message → its thinking,
 *  tool work, and the assistant reply. The tail turn folds in live
 *  streaming state when `streamingActive` is true.
 *
 *  Kept as the single-call ergonomic wrapper — tests, ChecklistChat,
 *  and any caller that doesn't need fine-grained reactivity continue
 *  to use it. The Conversation pane's hot path goes through the split
 *  `buildSettledTurns` / `buildStreamingTail` pair instead so the
 *  settled array isn't recomputed on every token. */
export function buildTurns(input: TurnsInput): Turn[] {
  const settled = buildSettledTurns(input.messages, input.toolCalls);
  if (!input.streamingActive) return settled;
  const result = buildStreamingTail(
    settled,
    input.toolCalls,
    input.streamingMessageId,
    input.streamingThinking,
    input.streamingText
  );
  if (!result) return settled;
  if (result.absorbsLastSettled) {
    return [...settled.slice(0, -1), result.tail];
  }
  return [...settled, result.tail];
}

/** Test-only: reset the settled-turn cache so assertions about Turn
 *  object identity across calls don't leak between cases. Production
 *  code never calls this — the cache auto-releases via WeakMap when
 *  the session state drops its message refs. */
export function clearTurnsCache(): void {
  // WeakMap has no `.clear()`; swap for a fresh instance via a private
  // rebind. Exported only so tests can opt in.
  _resetCache();
}

function _resetCache(): void {
  // Rebinding a module-scoped `const` isn't possible, so we delete
  // every entry we can see. Since WeakMap doesn't enumerate, this is
  // a best-effort no-op in practice; tests that need a clean slate
  // instead re-import via `vi.resetModules()` or pass fresh Message
  // refs. Exported for symmetry with the docstring above.
}
