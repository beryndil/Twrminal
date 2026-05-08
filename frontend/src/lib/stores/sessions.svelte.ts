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
import { _applyTagDelete, _applyTagUpsert } from "./tags.svelte";

interface SessionsState {
  /** Last successful list response. */
  sessions: SessionOut[];
  /** Per-session tag list — keyed by ``SessionOut.id``. */
  tagsBySessionId: Record<string, TagOut[]>;
  /** ``true`` while a refresh is in flight. */
  loading: boolean;
  /** Last error from a refresh attempt (cleared on success). */
  error: Error | null;
  /**
   * Session ids whose agent runner is currently executing a turn
   * (``is_running`` from the ``runner_state`` WS broadcast). Cleared
   * when the runner_state event sets ``is_running=false``.
   */
  running: Set<string>;
  /**
   * Session ids whose agent runner is parked waiting for the user
   * (``is_awaiting_user`` from the ``runner_state`` WS broadcast) —
   * tool-use approval or ``AskUserQuestion``. Cleared when
   * ``is_awaiting_user`` returns to false.
   */
  awaiting: Set<string>;
}

const state: SessionsState = $state({
  sessions: [],
  tagsBySessionId: {},
  loading: false,
  error: null,
  running: new Set<string>(),
  awaiting: new Set<string>(),
});

export const sessionsStore = state;

// ---- Sessions-broadcast WebSocket connection status -----------------------

/**
 * Reactive connection status for the sessions-broadcast WebSocket.
 *
 * Read by ``BackendStatusBanner`` to determine whether the backend is
 * reachable. Updated via the :func:`connectSessionsBroadcast` state
 * callbacks wired below.
 *
 * Initial state is ``'closed'`` — the socket is not yet open at module
 * load time. The banner's 5-second grace period means the initial closed
 * state does NOT immediately display the banner on first page load.
 */
interface WsConnectionStatus {
  /** Current logical state of the sessions-broadcast WebSocket. */
  state: "open" | "closed" | "error";
  /**
   * The close code from the most recent ``CloseEvent``, or ``null``
   * before the first close event fires. ``4401`` indicates an auth
   * failure and suppresses the backend-unreachable banner.
   */
  lastCloseCode: number | null;
}

const wsStatus: WsConnectionStatus = $state({ state: "closed", lastCloseCode: null });

/** Read-only reactive view of the sessions-broadcast WebSocket status. */
export const wsConnectionStatus: WsConnectionStatus = wsStatus;

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
//
// The ``options`` callbacks update ``wsStatus`` so ``BackendStatusBanner``
// can reactively reflect the connection state without a second socket.
connectSessionsBroadcast(
  (event) => {
    if (event.type === "session_upsert") {
      _applyUpsert(event.session);
    } else if (event.type === "session_delete") {
      _applyDelete(event.session_id);
    } else if (event.type === "runner_state") {
      const { session_id, is_running, is_awaiting_user, is_error } = event;

      // Maintain running set — reassign so Svelte's proxy detects the change.
      const nextRunning = new Set(state.running);
      if (is_running) {
        nextRunning.add(session_id);
      } else {
        nextRunning.delete(session_id);
      }
      state.running = nextRunning;

      // Maintain awaiting set — same reassignment pattern.
      const nextAwaiting = new Set(state.awaiting);
      if (is_awaiting_user) {
        nextAwaiting.add(session_id);
      } else {
        nextAwaiting.delete(session_id);
      }
      state.awaiting = nextAwaiting;

      // Agent loop entered ERROR state — set error_pending locally so
      // the sidebar pip flashes without waiting for a page reload.
      // The session_upsert from the recover route will clear it.
      if (is_error) {
        const idx = state.sessions.findIndex((s) => s.id === session_id);
        if (idx !== -1) {
          state.sessions[idx] = { ...state.sessions[idx], error_pending: true };
        }
      }
    } else if (event.type === "tag_upsert") {
      // Forward tag change events to the tags store so filter panels in
      // all open tabs refresh without a full GET /api/tags round-trip
      // (feature-5-004 / CCW-3). The single /ws/sessions connection is
      // shared — no second WebSocket needed.
      _applyTagUpsert(event.tag);
    } else if (event.type === "tag_delete") {
      _applyTagDelete(event.tag_id);
    }
  },
  {
    onOpen() {
      wsStatus.state = "open";
      wsStatus.lastCloseCode = null;
    },
    onClose(code: number) {
      wsStatus.state = "closed";
      wsStatus.lastCloseCode = code;
    },
    onError() {
      wsStatus.state = "error";
    },
  },
);

/**
 * Refresh the sidebar list using the three-section faceted tag
 * filter. Each section's set applies OR-within (a session matches
 * when it carries any of the listed tags within the class); the
 * three sections compose AND-across (a session must satisfy every
 * non-empty section). An empty section is "no constraint from this
 * class" — the route omits the matching ``tag_ids_<class>=`` query
 * param so the backend leaves it unconstrained.
 */
export async function refreshSessions(filter: {
  project: ReadonlySet<number>;
  severity: ReadonlySet<number>;
  other: ReadonlySet<number>;
  severityNone?: boolean;
}): Promise<void> {
  refreshController?.abort();
  const controller = new AbortController();
  refreshController = controller;
  state.loading = true;
  try {
    const params: Parameters<typeof listSessions>[0] = { signal: controller.signal };
    if (filter.project.size > 0) {
      params.tagIdsProject = filter.project;
    }
    if (filter.severity.size > 0) {
      params.tagIdsSeverity = filter.severity;
    }
    if (filter.other.size > 0) {
      params.tagIdsOther = filter.other;
    }
    if (filter.severityNone) {
      params.severityNone = true;
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
  state.running = new Set<string>();
  state.awaiting = new Set<string>();
  refreshController?.abort();
  refreshController = null;
}

/** Override ``running`` ids for unit tests. */
export function _setRunningForTests(ids: string[]): void {
  state.running = new Set(ids);
}

/** Override ``awaiting`` ids for unit tests. */
export function _setAwaitingForTests(ids: string[]): void {
  state.awaiting = new Set(ids);
}

/**
 * Override ``wsConnectionStatus`` fields for unit tests.
 *
 * Directly mutates the ``$state`` object so Svelte's reactive system
 * propagates the change to any component that reads
 * ``wsConnectionStatus``.
 */
export function _setWsStatusForTests(patch: {
  state?: "open" | "closed" | "error";
  lastCloseCode?: number | null;
}): void {
  if (patch.state !== undefined) {
    wsStatus.state = patch.state;
  }
  if ("lastCloseCode" in patch) {
    wsStatus.lastCloseCode = patch.lastCloseCode ?? null;
  }
}

/** Reset ``wsConnectionStatus`` to initial state between tests. */
export function _resetWsStatusForTests(): void {
  wsStatus.state = "closed";
  wsStatus.lastCloseCode = null;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

// ---- Activity indicator (gap-cycle-08-001) ---------------------------------

/**
 * The four visible states of the per-row activity indicator pip.
 * Priority order: ``"red"`` > ``"orange"`` > ``"green"`` > ``null``.
 */
export type IndicatorState = "red" | "orange" | "green" | null;

/**
 * Pure helper: resolve the activity indicator state from the four
 * boolean inputs that drive the sidebar pip.
 *
 * Priority rules (first match wins):
 * 1. ``"red"``    — agent awaiting user input OR ``error_pending`` latched.
 * 2. ``"orange"`` — agent turn is running (not parked on a question).
 * 3. ``"green"``  — unviewed output (``last_completed_at > last_viewed_at``
 *                   and the row is not the currently-selected session).
 * 4. ``null``     — idle and caught up.
 *
 * The function is exported for direct unit-test coverage; the
 * ``SessionRow`` component derives its state by calling it with values
 * read from ``sessionsStore.running``, ``sessionsStore.awaiting``, and
 * the session row's own fields.
 */
export function indicatorState(params: {
  errorPending: boolean;
  awaiting: boolean;
  running: boolean;
  unviewed: boolean;
}): IndicatorState {
  if (params.errorPending || params.awaiting) return "red";
  if (params.running) return "orange";
  if (params.unviewed) return "green";
  return null;
}
