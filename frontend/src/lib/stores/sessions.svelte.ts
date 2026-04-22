import * as api from '$lib/api';
import { tags } from '$lib/stores/tags.svelte';

const STORAGE_KEY = 'bearings:selectedSessionId';

function readStoredId(): string | null {
  if (typeof localStorage === 'undefined') return null;
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredId(id: string | null): void {
  if (typeof localStorage === 'undefined') return;
  try {
    if (id === null) localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // Quota/privacy-mode: ignore — selection is a convenience.
  }
}

const RUNNING_POLL_MS = 3_000;

class SessionStore {
  list = $state<api.Session[]>([]);
  selectedId = $state<string | null>(null);
  loading = $state(false);
  error = $state<string | null>(null);
  /** Most recent filter applied. Kept so bumpCost / bumpMessageCount
   * know whether a re-sort is safe (the filter is server-side, not
   * client-side). Currently informational — future slices may key
   * cache invalidation off it. */
  filter = $state<api.SessionFilter>({});

  /** Session ids whose server-side runner has a turn in flight right
   * now. Polled from `/api/sessions/running`; the UI lights up a
   * badge on each so the user can see background work at a glance. */
  running = $state<Set<string>>(new Set());

  /** Monotonically increasing counter that ticks every time the
   * currently-selected session is bumped to the top of the list
   * (via `touchSession` on user-submit / MessageStart, or `bumpCost`
   * on MessageComplete). SessionList watches this and scrolls the
   * sidebar viewport to the top so the just-bumped row is visible —
   * otherwise a user who'd scrolled down loses sight of their own
   * session the moment it moves. Bumps on a non-selected session
   * deliberately don't tick: stealing the viewport when a background
   * agent finishes a turn would be intrusive. */
  scrollTick = $state(0);

  private runningTimer: ReturnType<typeof setInterval> | null = null;

  selected = $derived(this.list.find((s) => s.id === this.selectedId) ?? null);

  /** Open sessions — render in the main sidebar list. Truthy check
   * (not `=== null`) so a backend that temporarily omits the field —
   * e.g. during a rolling deploy where the server lags the static
   * bundle — doesn't misclassify every session as closed. */
  openList = $derived(this.list.filter((s) => !s.closed_at));

  /** Closed sessions — render in the collapsed "Closed (N)" group at
   * the bottom of the sidebar. Preserves the store's existing
   * `updated_at DESC` ordering because `filter` is stable. */
  closedList = $derived(this.list.filter((s) => !!s.closed_at));

  async refresh(filter: api.SessionFilter = {}): Promise<void> {
    this.loading = true;
    this.error = null;
    this.filter = filter;
    try {
      this.list = await api.listSessions(filter);
      const stored = readStoredId();
      if (stored && this.list.some((s) => s.id === stored) && this.selectedId === null) {
        this.selectedId = stored;
      }
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    } finally {
      this.loading = false;
    }
  }

  async create(body: api.SessionCreate): Promise<api.Session | null> {
    this.error = null;
    try {
      const created = await api.createSession(body);
      this.list = [created, ...this.list];
      this.select(created.id);
      return created;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      return null;
    }
  }

  async remove(id: string): Promise<void> {
    this.error = null;
    try {
      await api.deleteSession(id);
      this.list = this.list.filter((s) => s.id !== id);
      if (this.selectedId === id) this.select(null);
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    }
  }

  async update(id: string, patch: api.SessionUpdate): Promise<api.Session | null> {
    this.error = null;
    try {
      const updated = await api.updateSession(id, patch);
      this.list = this.list.map((s) => (s.id === id ? updated : s));
      return updated;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      return null;
    }
  }

  /** Close a session — patches the in-place row so the sidebar
   * re-renders the open/closed split without a full refresh. Refreshes
   * the tags store so each tag's `open_session_count` reflects the new
   * lifecycle state (the sidebar renders it in green next to the total).
   * Close can cascade on the backend (paired checklist/chat), so
   * refetching is simpler than tracking which tags to decrement. */
  async close(id: string): Promise<api.Session | null> {
    this.error = null;
    try {
      const closed = await api.closeSession(id);
      this.list = this.list.map((s) => (s.id === id ? closed : s));
      void tags.refresh();
      return closed;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      return null;
    }
  }

  /** Reopen a closed session. Symmetric to `close`. */
  async reopen(id: string): Promise<api.Session | null> {
    this.error = null;
    try {
      const reopened = await api.reopenSession(id);
      this.list = this.list.map((s) => (s.id === id ? reopened : s));
      void tags.refresh();
      return reopened;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      return null;
    }
  }

  /** Bump the session's client-side `updated_at` and re-sort it to
   * the top of the list. Called from:
   *   - `pushUserMessage` — user typed a prompt, sort should update
   *     immediately (the backend also bumps via `insert_message`, but
   *     this beats the next poll tick to the UI).
   *   - `MessageStart` arm in the reducer — agent began processing.
   *   - `bumpCost` on `MessageComplete` — kept as a safeguard so a
   *     session that skipped an earlier bump still ends at the top.
   *
   * No-op if the session isn't in the list (e.g. deleted mid-stream). */
  touchSession(id: string): void {
    const now = new Date().toISOString();
    const hit = this.list.find((s) => s.id === id);
    if (!hit) return;
    if (hit.updated_at === now && this.list[0]?.id === id) return;
    const updated: api.Session = { ...hit, updated_at: now };
    const rest = this.list.filter((s) => s.id !== id);
    this.list = [updated, ...rest];
    if (id === this.selectedId) this.scrollTick++;
  }

  /** Called by the conversation store when a MessageComplete event
   * carries a cost delta, so the sidebar row reflects the new total
   * without waiting for a full `refresh()`. Re-sorts to top via
   * `touchSession` and stamps `last_completed_at` locally so the
   * amber "finished but unviewed" dot can light up before the next
   * poll pulls the canonical column. No-op if the session is gone. */
  bumpCost(id: string, deltaUsd: number): void {
    const hit = this.list.find((s) => s.id === id);
    if (!hit) return;
    const now = new Date().toISOString();
    const rest = this.list.filter((s) => s.id !== id);
    this.list = [
      {
        ...hit,
        updated_at: now,
        last_completed_at: now,
        total_cost_usd:
          deltaUsd > 0 ? hit.total_cost_usd + deltaUsd : hit.total_cost_usd
      },
      ...rest
    ];
    if (id === this.selectedId) this.scrollTick++;
  }

  /** Stamp `last_viewed_at` so the "finished but unviewed" amber dot
   * clears for this session. Optimistic: updates the local row first
   * for instant UI feedback, then fires the POST. A transport failure
   * is swallowed — the dot clearing is cosmetic, and the next
   * refresh will reconcile. */
  async markViewed(id: string): Promise<void> {
    const now = new Date().toISOString();
    this.list = this.list.map((s) =>
      s.id === id ? { ...s, last_viewed_at: now } : s
    );
    try {
      const updated = await api.markSessionViewed(id);
      this.list = this.list.map((s) => (s.id === id ? updated : s));
    } catch {
      // Network blink or the session was deleted between select and
      // POST — leave the optimistic stamp in place.
    }
  }

  /** Reconcile the list against the server without blowing away
   * optimistic local state. Called by `startRunningPoll` every tick so
   * activity that originated in another tab — or in a background
   * session this tab never WS-subscribed to — reaches the sidebar
   * without a full reload.
   *
   * Merge rules:
   *   - Rows present server-side: take the server row, unless the local
   *     row has a strictly newer `updated_at` (an optimistic
   *     `touchSession` / `bumpCost` hasn't been persisted yet). Keeping
   *     local-newer avoids a flicker where the just-bumped row drops
   *     back down and then climbs again on the next poll.
   *   - Rows gone from server: dropped. If the selected session was
   *     deleted elsewhere, clear `selectedId` so callers don't keep
   *     pointing at a ghost.
   *   - New rows: inserted.
   *   - Final order: `updated_at DESC, id DESC` — mirrors the server's
   *     sort so the canonical order shows up regardless of which rows
   *     won the local-vs-server tiebreak.
   *
   * Silent on transport errors — this is a background refresh; the
   * next tick retries. `running`, `loading`, `error`, and `filter` are
   * untouched. */
  async softRefresh(): Promise<void> {
    let fresh: api.Session[];
    try {
      fresh = await api.listSessions(this.filter);
    } catch {
      return;
    }
    const localById = new Map(this.list.map((s) => [s.id, s]));
    const merged: api.Session[] = fresh.map((server) => {
      const local = localById.get(server.id);
      if (local && local.updated_at > server.updated_at) return local;
      return server;
    });
    merged.sort((a, b) => {
      if (a.updated_at !== b.updated_at) return a.updated_at < b.updated_at ? 1 : -1;
      return a.id < b.id ? 1 : -1;
    });
    this.list = merged;
    if (this.selectedId && !merged.some((s) => s.id === this.selectedId)) {
      this.select(null);
    }
  }

  /** Apply an upsert frame from the `/ws/sessions` broadcast channel.
   * Inserts if new, otherwise replaces — except when the local row has a
   * strictly newer `updated_at` than the incoming one, in which case we
   * keep the optimistic local copy (same rule as `softRefresh`). Re-sorts
   * by `updated_at DESC, id DESC` to match the server ordering.
   *
   * When a tag filter is active the broadcast frame carries no filter
   * context and the frontend's `Session` shape has no tag membership
   * field to check, so we can't safely decide whether the incoming row
   * belongs in the current view. In that case the 3s `softRefresh` poll
   * reconciles the filtered list instead — a brief lag on tag-filtered
   * views is the price of keeping the default (unfiltered) path live. */
  applyUpsert(session: api.Session): void {
    const tagFilter = this.filter.tags ?? [];
    if (tagFilter.length > 0) return;
    const existing = this.list.find((s) => s.id === session.id);
    const incoming =
      existing && existing.updated_at > session.updated_at ? existing : session;
    const rest = this.list.filter((s) => s.id !== session.id);
    const merged = [incoming, ...rest];
    merged.sort((a, b) => {
      if (a.updated_at !== b.updated_at) return a.updated_at < b.updated_at ? 1 : -1;
      return a.id < b.id ? 1 : -1;
    });
    this.list = merged;
  }

  /** Apply a delete frame from the `/ws/sessions` broadcast channel.
   * Drops the row and clears `selectedId` if it pointed at the deleted
   * session so downstream code doesn't render a ghost selection. Safe
   * to run under any filter — removing a row we don't have is a no-op. */
  applyDelete(sessionId: string): void {
    const had = this.list.some((s) => s.id === sessionId);
    if (!had) return;
    this.list = this.list.filter((s) => s.id !== sessionId);
    if (this.selectedId === sessionId) this.select(null);
  }

  /** Apply a runner_state frame from the `/ws/sessions` broadcast
   * channel. The `running` set isn't view-scoped so we always apply
   * regardless of filter. Reassigns the Set so Svelte 5 consumers
   * re-read — the runes proxy does track in-place mutation, but matching
   * the pattern used elsewhere in this store keeps the reactive
   * behavior obvious. */
  applyRunnerState(sessionId: string, isRunning: boolean): void {
    const next = new Set(this.running);
    if (isRunning) next.add(sessionId);
    else next.delete(sessionId);
    this.running = next;
  }

  /** Bumps the sidebar's cached message_count. Called on user-push
   * (+1) and on MessageComplete (+1 for the assistant row). */
  bumpMessageCount(id: string, delta: number): void {
    if (delta === 0) return;
    this.list = this.list.map((s) =>
      s.id === id
        ? { ...s, message_count: Math.max(0, s.message_count + delta) }
        : s
    );
  }

  select(id: string | null): void {
    this.selectedId = id;
    writeStoredId(id);
  }

  /** Poll the backend for session ids with in-flight runners AND for
   * changes to the session list itself. Safe to call repeatedly —
   * existing timer is cleared first. Called from +page.svelte on boot.
   *
   * The per-tick work splits in two:
   *   - `listRunningSessions()` → refresh the `running` badge set.
   *   - `softRefresh()` → pick up activity (new `updated_at`, new cost,
   *     newly-created sessions, deletions) from other tabs or from
   *     background sessions this tab never WS-subscribed to. Without
   *     this, a session running while the user is on a different row
   *     stays stuck at its old sidebar position until a full reload.
   *
   * Calls run in parallel — they're independent and both tolerate
   * transport blips on their own. */
  startRunningPoll(): void {
    this.stopRunningPoll();
    const tick = async () => {
      const runningCall = (async () => {
        try {
          const ids = await api.listRunningSessions();
          this.running = new Set(ids);
        } catch {
          // Polling is a cosmetic feature — if the token expired or the
          // server blinked, just drop the running set. The auth layer
          // handles real 401s elsewhere.
          this.running = new Set();
        }
      })();
      await Promise.all([runningCall, this.softRefresh()]);
    };
    tick();
    this.runningTimer = setInterval(tick, RUNNING_POLL_MS);
  }

  stopRunningPoll(): void {
    if (this.runningTimer !== null) {
      clearInterval(this.runningTimer);
      this.runningTimer = null;
    }
  }
}

export const sessions = new SessionStore();
