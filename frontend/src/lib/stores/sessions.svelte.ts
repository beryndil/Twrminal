import * as api from '$lib/api';

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
   * re-renders the open/closed split without a full refresh. */
  async close(id: string): Promise<api.Session | null> {
    this.error = null;
    try {
      const closed = await api.closeSession(id);
      this.list = this.list.map((s) => (s.id === id ? closed : s));
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
      return reopened;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      return null;
    }
  }

  /** Called by the conversation store when a MessageComplete event
   * carries a cost delta, so the sidebar row reflects the new total
   * without waiting for a full `refresh()`. Also mirrors the server's
   * updated_at touch + re-sort so the active session floats to the
   * top of the list. No-op if the session isn't in the list (e.g.
   * it was deleted mid-stream). */
  bumpCost(id: string, deltaUsd: number): void {
    const now = new Date().toISOString();
    const hit = this.list.find((s) => s.id === id);
    if (!hit) return;
    const updated: api.Session = {
      ...hit,
      updated_at: now,
      total_cost_usd:
        deltaUsd > 0 ? hit.total_cost_usd + deltaUsd : hit.total_cost_usd
    };
    const rest = this.list.filter((s) => s.id !== id);
    this.list = [updated, ...rest];
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

  /** Poll the backend for session ids with in-flight runners. Safe to
   * call repeatedly — existing timer is cleared first. Called from
   * +page.svelte on boot so navigation away from a streaming session
   * keeps the badge accurate. */
  startRunningPoll(): void {
    this.stopRunningPoll();
    const tick = async () => {
      try {
        const ids = await api.listRunningSessions();
        this.running = new Set(ids);
      } catch {
        // Polling is a cosmetic feature — if the token expired or the
        // server blinked, just drop the running set. The auth layer
        // handles real 401s elsewhere.
        this.running = new Set();
      }
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
