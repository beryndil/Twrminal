/**
 * Typed client for ``GET /api/history/search?q=`` — sidebar search
 * (item 2.4).
 *
 * Backend route: :func:`bearings.web.routes.history.search_history`.
 * Pydantic shape: :class:`bearings.web.models.history.HistorySearchResult`.
 */
import { API_HISTORY_SEARCH_ENDPOINT } from "../config";
import { getJson } from "./client";

/**
 * One search hit — mirrors
 * :class:`bearings.web.models.history.HistorySearchResult`.
 *
 * ``kind`` is ``"session"`` for session-title/description matches,
 * ``"message"`` for message-content matches.
 *
 * ``message_id`` is ``null`` for session hits; the message row id for
 * message hits (the sidebar navigates to ``/sessions/{session_id}#msg-{id}``).
 */
export interface HistorySearchResult {
  kind: "session" | "message";
  session_id: string;
  session_title: string;
  message_id: string | null;
  snippet: string;
}

/**
 * Search sessions and messages for ``q``.
 *
 * Never rejects on a network/server error — an empty array is returned
 * instead so the sidebar search degrades gracefully when the backend is
 * unreachable.
 */
export async function searchHistory(q: string): Promise<HistorySearchResult[]> {
  if (!q.trim()) return [];
  try {
    const url = `${API_HISTORY_SEARCH_ENDPOINT}?q=${encodeURIComponent(q.trim())}`;
    return await getJson<HistorySearchResult[]>(url);
  } catch {
    return [];
  }
}
