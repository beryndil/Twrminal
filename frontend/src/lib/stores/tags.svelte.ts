import * as api from '$lib/api';

class TagStore {
  list = $state<api.Tag[]>([]);
  loading = $state(false);
  error = $state<string | null>(null);

  async refresh(): Promise<void> {
    this.loading = true;
    this.error = null;
    try {
      this.list = await api.listTags();
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    } finally {
      this.loading = false;
    }
  }

  async create(body: api.TagCreate): Promise<api.Tag | null> {
    this.error = null;
    try {
      const created = await api.createTag(body);
      // Re-fetch so ordering (pinned-first / sort_order) comes from
      // the authoritative backend view instead of being re-sorted on
      // the client.
      await this.refresh();
      return created;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      return null;
    }
  }

  async update(id: number, patch: api.TagUpdate): Promise<api.Tag | null> {
    this.error = null;
    try {
      const updated = await api.updateTag(id, patch);
      await this.refresh();
      return updated;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      return null;
    }
  }

  async remove(id: number): Promise<boolean> {
    this.error = null;
    try {
      await api.deleteTag(id);
      this.list = this.list.filter((t) => t.id !== id);
      return true;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      return false;
    }
  }

  /** Bump the cached session_count on a tag, used after a local
   * attach/detach so the sidebar chip updates without a full refresh.
   * Clamps at 0 — never negative. */
  bumpCount(id: number, delta: number): void {
    this.list = this.list.map((t) =>
      t.id === id
        ? { ...t, session_count: Math.max(0, t.session_count + delta) }
        : t
    );
  }
}

export const tags = new TagStore();
