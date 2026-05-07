/**
 * Agent WebSocket client — owns one connection per active session.
 *
 * Per arch §2.2: ``agent.svelte.ts — agent-WS client + per-session
 * conversation reducer entrypoint.`` This module:
 *
 * 1. Builds the ``ws[s]://<host>/ws/sessions/{id}`` URL (mirroring
 *    :data:`bearings.web.streaming.SINCE_SEQ_QUERY_PARAM`'s
 *    ``?since_seq=<n>`` resume cursor).
 * 2. Parses incoming text frames via :func:`parseStreamFrame`.
 * 3. Dispatches event frames into :mod:`stores/conversation.svelte.ts`
 *    via :func:`ingestFrame`.
 * 4. Auto-reconnects on close — each reconnect uses the
 *    conversation store's ``lastSeq`` so the runner replays only
 *    frames the client missed.
 *
 * Reconnect policy is a small exponential backoff capped at
 * :data:`MAX_RECONNECT_DELAY_MS`. The cap is short on purpose: the
 * UI must feel live; a 30-second backoff would defeat the
 * "reconnect / replay" guarantee in
 * ``docs/behavior/tool-output-streaming.md``.
 */
import { conversationStore, ingestFrame, setError } from "./stores/conversation.svelte";
import { parseStreamFrame } from "./api/streaming";
import { sessionStreamPath, WS_FRAME_KIND_EVENT, WS_SINCE_SEQ_QUERY_PARAM } from "./config";
import { maybeFireTurnNotification } from "./utils/notify";

const INITIAL_RECONNECT_DELAY_MS = 250;
const MAX_RECONNECT_DELAY_MS = 4_000;

interface ActiveConnection {
  sessionId: string;
  socket: WebSocket;
  closed: boolean;
  retryDelayMs: number;
  retryHandle: ReturnType<typeof setTimeout> | null;
}

let active: ActiveConnection | null = null;

/**
 * Open (or replace) the WebSocket subscription for ``sessionId``.
 * Idempotent on the same session id — calling twice in a row is a
 * no-op. Calling with a different id closes the previous connection
 * and opens a new one. The conversation store's ``lastSeq`` is used
 * as the resume cursor on reconnect.
 */
export function connectSession(sessionId: string): void {
  if (active !== null && active.sessionId === sessionId && !active.closed) {
    return;
  }
  disconnectSession();
  openSocket(sessionId);
}

/** Close the current subscription, if any. Safe to call when no connection is active. */
export function disconnectSession(): void {
  if (active === null) {
    return;
  }
  active.closed = true;
  if (active.retryHandle !== null) {
    clearTimeout(active.retryHandle);
  }
  try {
    active.socket.close();
  } catch {
    // ``close`` may throw if the socket is already closing; the
    // disconnect contract is "best-effort" and the WS layer cleans
    // itself up when the GC runs.
  }
  active = null;
}

function openSocket(sessionId: string): void {
  const url = buildWsUrl(sessionId, conversationStore.lastSeq);
  const socket = new WebSocket(url);
  const conn: ActiveConnection = {
    sessionId,
    socket,
    closed: false,
    retryDelayMs: INITIAL_RECONNECT_DELAY_MS,
    retryHandle: null,
  };
  active = conn;
  socket.addEventListener("message", (event) => {
    if (typeof event.data !== "string") {
      return;
    }
    const frame = parseStreamFrame(event.data);
    if (frame === null) {
      return;
    }
    ingestFrame(frame);
    // Fire a desktop notification when an assistant turn completes and
    // the tab is hidden or unfocused. maybeFireTurnNotification performs
    // all prerequisite checks (opt-in, permission, visibility).
    if (frame.kind === WS_FRAME_KIND_EVENT && frame.event.type === "message_complete") {
      maybeFireTurnNotification();
    }
  });
  socket.addEventListener("close", () => {
    if (conn.closed) {
      return;
    }
    scheduleReconnect(conn);
  });
  socket.addEventListener("error", () => {
    // The browser's WS layer fires ``error`` then ``close``; we react
    // on close. The error event itself is opaque (no detail) — record
    // it on the store so the conversation pane can render the
    // "Backend unreachable" banner per chat.md §"Error states".
    setError(new Error("WebSocket transport error"));
  });
}

function scheduleReconnect(conn: ActiveConnection): void {
  if (active !== conn) {
    // A newer connection has taken over; abort.
    return;
  }
  const delay = conn.retryDelayMs;
  conn.retryDelayMs = Math.min(conn.retryDelayMs * 2, MAX_RECONNECT_DELAY_MS);
  conn.retryHandle = setTimeout(() => {
    if (conn.closed || active !== conn) {
      return;
    }
    openSocket(conn.sessionId);
  }, delay);
}

function buildWsUrl(sessionId: string, sinceSeq: number): string {
  const path = sessionStreamPath(sessionId);
  const base =
    typeof window === "undefined"
      ? `ws://localhost${path}`
      : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}${path}`;
  const sep = base.includes("?") ? "&" : "?";
  return `${base}${sep}${WS_SINCE_SEQ_QUERY_PARAM}=${sinceSeq}`;
}
