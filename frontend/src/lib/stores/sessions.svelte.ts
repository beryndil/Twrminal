/**
 * Sessions store — sidebar list state + per-session tag cache.
 *
 * Per arch §2.2 the canonical sidebar-list store. Owns:
 *
 * - the last ``GET /api/sessions`` snapshot (filtered by the current
 *   tag-filter selection from :mod:`stores/tags.svelte.ts`);
 * - a per-session tag map (each session's attached tags), populated
 *   alongside the list so :class:`SessionRow` can render chips
 *   without a per-row fetch storm;
 * - a single in-flight ``AbortController`` so a rapid filter toggle
 *   (or a tab refocus while the previous request is pending) cancels
 *   the older fetch.
 * - a ``/ws/sessions`` WebSocket subscription (item 2.6) that merges
 *   upserts and deletes into the local session list so all open tabs
 *   update without a full re-fetch.
 *
 * The store deliberately does NOT subscribe to the tags store —
 * components own the wiring. The pattern is:
 *
 * ```svelte
 * $effect(() => {
 *   void refreshSessions(tagsStore.selectedIds);
 * });
 * ```
 *
 * That keeps the store layer side-effect-free and makes the
 * dependency graph one-way (components depend on stores; stores never
 * depend on each other).
 */
import { listSessions, type SessionOut } from "../api/sessions";
import { listSessionTags, type TagOut } from "../api/tags";
import { connectSessionsBroadcast } from "../api/wsSessions";

interface SessionsState {
  /** Last successful list response. */
  sessions: SessionOut[];
  /** Per-session tag list — keyed by ``SessionOut.id``. */
  tagsBySessionId: Record<string, TagOut[]>;
  /** ``true`` while a refresh is in flight. */
  loading: boolean;
  /** Last error from a refresh attempt (cleared on success). */
  error: Error | null;
}

const state: SessionsState = $state({
  sessions: [],
  tagsBySessionId: {},
  loading: false,
  error: null,
});

export const sessionsStore = state;

let refreshController: AbortController | null = null;

// ---- sessions-broadcast subscription (item 2.6) ----------------------------

/**
 * Apply a ``session_upsert`` message to the local sessions list.
 *
 * If a row with the same ``id`` is already present, replace it
 * in-place so the sidebar re-renders with the new data (title
 * change, closed_at stamp, etc.). If it is new (created in another
 * tab), prepend it so it appears at the top — matching the sort order
 * the ``GET /api/sessions`` endpoint uses (newest first).
 *
 * Tag chips for the new row are NOT updated: the sidebar only shows
 * chips after the full ``refreshSessions`` cycle, and a cross-tab
 * upsert is typically a title/status change, not a tag change. A
 * later ``refreshSessions()`` call restores full tag accuracy.
 */
function _applyUpsert(session: SessionOut): void {
  const idx = state.sessions.findIndex((s) => s.id === session.id);
  if (idx >= 0) {
    state.sessions[idx] = session;
  } else {
    state.sessions = [session, ...state.sessions];
  }
}

/**
 * Apply a ``session_delete`` message by removing the matching row.
 * No-ops when the id is not in the current list.
 */
function _applyDelete(sessionId: string): void {
  state.sessions = state.sessions.filter((s) => s.id !== sessionId);
}

// Start the broadcast subscription immediately when the module loads.
// ``connectSessionsBroadcast`` auto-reconnects so the subscription
// survives server restarts.  The returned ``Unsubscribe`` is not
// stored because this singleton lives for the page's lifetime.
connectSessionsBroadcast((event) => {
  if (event.type === "session_upsert") {
    _applyUpsert(event.session);
  } else if (event.type === "session_delete") {
    _applyDelete(event.session_id);
  } else if (event.type === "runner_state" && event.is_error) {
    // Agent loop entered ERROR state — set error_pending locally so
    // the sidebar pip flashes without waiting for a page reload.
    // The session_upsert from the recover route will clear it.
    const idx = state.sessions.findIndex((s) => s.id === event.session_id);
    if (idx !== -1) {
      state.sessions[idx] = { ...state.sessions[idx], error_pending: true };
    }
  }
});

/**
 * Refresh the sidebar list. ``tagFilter`` is the OR-semantics filter
 * set from :data:`tagsStore.selectedIds`; an empty set means "no
 * filter applied" (the route omits the ``tag_ids`` query param
 * entirely when the iterable is empty, mirroring the backend
 * contract).
 */
export async function refreshSessions(tagFilter: ReadonlySet<number>): Promise<void> {
  refreshController?.abort();
  const controller = new AbortController();
  refreshController = controller;
  state.loading = true;
  try {
    const params: Parameters<typeof listSessions>[0] = { signal: controller.signal };
    if (tagFilter.size > 0) {
      params.tagIds = tagFilter;
    }
    const sessions = await listSessions(params);
    if (controller.signal.aborted) {
      return;
    }
    state.sessions = sessions;
    // Per-session tag fetches run in parallel; one fetch per row is
    // acceptable for v1 (the typical project has ≤ a few dozen open
    // sessions). Item 2.5+ may collapse this into a single
    // ``/api/sessions?include_tags=true`` extension if the latency
    // becomes visible.
    const tagLists: Array<[string, TagOut[]]> = await Promise.all(
      sessions.map(async (session): Promise<[string, TagOut[]]> => {
        try {
          const tags = await listSessionTags(session.id, { signal: controller.signal });
          return [session.id, tags];
        } catch (error) {
          if (controller.signal.aborted || isAbortError(error)) {
            return [session.id, []];
          }
          // A single per-session fetch failure shouldn't blank the
          // whole sidebar — fall back to "no chips" for that row.
          return [session.id, []];
        }
      }),
    );
    if (controller.signal.aborted) {
      return;
    }
    const nextTagMap: Record<string, TagOut[]> = {};
    for (const [id, tags] of tagLists) {
      nextTagMap[id] = tags;
    }
    state.tagsBySessionId = nextTagMap;
    state.error = null;
  } catch (error) {
    if (controller.signal.aborted || isAbortError(error)) {
      return;
    }
    state.error = error instanceof Error ? error : new Error(String(error));
  } finally {
    if (refreshController === controller) {
      refreshController = null;
    }
    state.loading = false;
  }
}

export function _resetForTests(): void {
  state.sessions = [];
  state.tagsBySessionId = {};
  state.loading = false;
  state.error = null;
  refreshController?.abort();
  refreshController = null;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
