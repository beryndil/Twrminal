import * as api from '$lib/api';

/** Checklist store (v0.4.0, Slice 3).
 *
 * Holds the currently-rendered checklist and runs every mutation
 * optimistically — the server round-trip replaces the optimistic
 * row with the authoritative shape on success. Rollback on failure
 * surfaces as an `error` string; the component can render a toast
 * without dragging the loading fringe back up.
 *
 * Mutation ordering is enforced per-op by awaiting the server call;
 * rapid toggles on the same item still write in the order the user
 * clicked because the UI itself dispatches them sequentially. If
 * we later need strict serialization across items, introduce an
 * in-flight map keyed by item id.
 */
class ChecklistStore {
  current = $state<api.Checklist | null>(null);
  loading = $state(false);
  error = $state<string | null>(null);
  /** Session id currently loaded; used by the caller to dedupe
   * repeated `load()` calls when the user clicks back into the
   * already-open session. */
  sessionId = $state<string | null>(null);

  reset(): void {
    this.current = null;
    this.error = null;
    this.sessionId = null;
  }

  async load(sessionId: string): Promise<void> {
    this.loading = true;
    this.error = null;
    this.sessionId = sessionId;
    try {
      this.current = await api.getChecklist(sessionId);
    } catch (e) {
      this.current = null;
      this.error = e instanceof Error ? e.message : String(e);
    } finally {
      this.loading = false;
    }
  }

  async setNotes(notes: string | null): Promise<void> {
    if (!this.current || !this.sessionId) return;
    const prev = this.current;
    this.current = { ...prev, notes };
    try {
      const updated = await api.updateChecklist(this.sessionId, { notes });
      this.current = updated;
    } catch (e) {
      this.current = prev;
      this.error = e instanceof Error ? e.message : String(e);
    }
  }

  async add(label: string, parentId: number | null = null): Promise<void> {
    if (!this.current || !this.sessionId || label.trim() === '') return;
    try {
      const created = await api.createItem(this.sessionId, {
        label: label.trim(),
        parent_item_id: parentId
      });
      // Append — the server already assigned the next sort_order.
      this.current = { ...this.current, items: [...this.current.items, created] };
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    }
  }

  async toggle(itemId: number, checked: boolean): Promise<void> {
    if (!this.current || !this.sessionId) return;
    const stamp = checked ? new Date().toISOString() : null;
    const prevItems = this.current.items;
    this.current = {
      ...this.current,
      items: prevItems.map((i) => (i.id === itemId ? { ...i, checked_at: stamp } : i))
    };
    try {
      const updated = await api.toggleItem(this.sessionId, itemId, checked);
      this._replaceItem(updated);
    } catch (e) {
      this.current = { ...this.current, items: prevItems };
      this.error = e instanceof Error ? e.message : String(e);
    }
  }

  async update(itemId: number, patch: api.ItemUpdate): Promise<void> {
    const list = this.current;
    const sid = this.sessionId;
    if (!list || !sid) return;
    const prevItems = list.items;
    // Apply patch locally first so the edit commits feel instant.
    // Cast through `Partial<ChecklistItem>` so the optimistic shape
    // stays `ChecklistItem` — the server is the source of truth on
    // non-null constraints and the next `_replaceItem` reconciles.
    const optimistic = prevItems.map((i) =>
      i.id === itemId ? ({ ...i, ...patch } as api.ChecklistItem) : i
    );
    this.current = { ...list, items: optimistic };
    try {
      const updated = await api.updateItem(sid, itemId, patch);
      this._replaceItem(updated);
    } catch (e) {
      this.current = { ...list, items: prevItems };
      this.error = e instanceof Error ? e.message : String(e);
    }
  }

  async remove(itemId: number): Promise<void> {
    if (!this.current || !this.sessionId) return;
    const prevItems = this.current.items;
    this.current = {
      ...this.current,
      items: prevItems.filter((i) => i.id !== itemId)
    };
    try {
      await api.deleteItem(this.sessionId, itemId);
    } catch (e) {
      this.current = { ...this.current, items: prevItems };
      this.error = e instanceof Error ? e.message : String(e);
    }
  }

  async reorder(orderedIds: number[]): Promise<void> {
    if (!this.current || !this.sessionId) return;
    const prevItems = this.current.items;
    const byId = new Map(prevItems.map((i) => [i.id, i]));
    // Local re-sort: new order first, trailing anything the caller
    // omitted (keeps a safety net if the UI ever sends a partial
    // order — the server already tolerates it).
    const next = orderedIds
      .map((id) => byId.get(id))
      .filter((i): i is api.ChecklistItem => Boolean(i));
    for (const item of prevItems) {
      if (!orderedIds.includes(item.id)) next.push(item);
    }
    this.current = { ...this.current, items: next };
    try {
      await api.reorderItems(this.sessionId, orderedIds);
      // No re-fetch: the backend rewrote sort_order atomically and the
      // next `load()` will reflect it. The optimistic local order
      // matches what the server has.
    } catch (e) {
      this.current = { ...this.current, items: prevItems };
      this.error = e instanceof Error ? e.message : String(e);
    }
  }

  _replaceItem(updated: api.ChecklistItem): void {
    if (!this.current) return;
    this.current = {
      ...this.current,
      items: this.current.items.map((i) => (i.id === updated.id ? updated : i))
    };
  }
}

export const checklists = new ChecklistStore();
