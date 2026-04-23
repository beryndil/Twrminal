/**
 * Session-templates store (Phase 9b.3 of docs/context-menu-plan.md).
 *
 * Holds the newest-first catalog of saved templates. The sidebar picker
 * reads `list` directly; context-menu actions mutate via `create`,
 * `remove`, `instantiate`. Keeps the list in local state so the picker
 * stays reactive without every render round-tripping the server.
 *
 * Boot path: the picker component calls `refresh()` on mount. No
 * fetch-on-read — the initial render of an un-refreshed store yields an
 * empty list, matching the other surface stores (`checkpoints`,
 * `tags`).
 */

import * as api from '$lib/api';

import { sessions } from './sessions.svelte';

class TemplatesStore {
  /** Newest-first list from `GET /api/templates`. Starts empty so a
   * picker rendered before the first `refresh()` shows "no templates"
   * rather than a spinner forever. */
  list = $state<api.Template[]>([]);
  loading = $state(false);
  error = $state<string | null>(null);

  async refresh(): Promise<void> {
    this.loading = true;
    this.error = null;
    try {
      this.list = await api.listTemplates();
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    } finally {
      this.loading = false;
    }
  }

  /** Create and prepend. The server returns the inserted row already
   * decoded (tag_ids as list[int]) so we can splice it into the local
   * list without a re-fetch. */
  async create(body: api.TemplateCreate): Promise<api.Template | null> {
    this.error = null;
    try {
      const created = await api.createTemplate(body);
      this.list = [created, ...this.list];
      return created;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      return null;
    }
  }

  /** Optimistic delete — drop the row locally before the server call so
   * the picker UI is snappy; restore on failure. Returns true when the
   * row was present and the server acknowledged. */
  async remove(id: string): Promise<boolean> {
    const prev = this.list;
    const next = prev.filter((t) => t.id !== id);
    if (next.length === prev.length) return false;
    this.list = next;
    try {
      await api.deleteTemplate(id);
      return true;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      this.list = prev;
      return false;
    }
  }

  /** Spawn a new session from `id`. Pushes the returned session into
   * the sessions store up front so the sidebar row appears immediately;
   * the server also emits a `session_upsert` frame so the background
   * poll would reconcile anyway. Returns the new session for callers
   * that want to navigate via `sessions.select(id)`. */
  async instantiate(
    id: string,
    body: api.TemplateInstantiateRequest = {}
  ): Promise<api.Session | null> {
    this.error = null;
    try {
      const created = await api.instantiateTemplate(id, body);
      sessions.applyUpsert(created);
      return created;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      return null;
    }
  }

  /** Test-only: reset all state. Production callers never need this. */
  _reset(): void {
    this.list = [];
    this.loading = false;
    this.error = null;
  }
}

export const templates = new TemplatesStore();
