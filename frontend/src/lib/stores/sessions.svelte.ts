import * as api from '$lib/api';

const STORAGE_KEY = 'twrminal:selectedSessionId';

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

  selected = $derived(this.list.find((s) => s.id === this.selectedId) ?? null);

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
}

export const sessions = new SessionStore();
