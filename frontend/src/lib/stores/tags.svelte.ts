import * as api from '$lib/api';

/** localStorage key for the collapsed/expanded state of the whole tag
 * filter panel (migration 0021 / v0.2.14). Expanded on first run per
 * Daisy; the value lives in the browser and isn't synced to the DB. */
const COLLAPSED_KEY = 'bearings.tagFilterPanel.collapsed';

/** Sentinel id for the virtual "No severity" entry in the severity
 * filter list. Real tag ids come from SQLite AUTOINCREMENT (always
 * positive), so -1 is guaranteed to not collide. The backend
 * `list_sessions(severity_tag_ids=[-1])` interprets this as
 * "sessions with no severity-group tag attached" — the filter path
 * for sessions orphaned by a deleted severity tag. */
export const SEVERITY_NONE_ID = -1;

function readCollapsed(): boolean {
  // Guard against SSR / jsdom: both set `globalThis` but jsdom's
  // localStorage is real, while SvelteKit SSR has none. Either way,
  // a missing or malformed value means "expanded on first run."
  if (typeof localStorage === 'undefined') return false;
  try {
    return localStorage.getItem(COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

function writeCollapsed(value: boolean): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(COLLAPSED_KEY, value ? '1' : '0');
  } catch {
    // Quota exhausted / private-mode — the collapse preference is
    // cosmetic, not worth surfacing an error.
  }
}

class TagStore {
  list = $state<api.Tag[]>([]);
  loading = $state(false);
  error = $state<string | null>(null);
  /** General-group tag ids selected as a filter on the sidebar session
   * list. Multi-select follows Finder semantics: a plain click replaces
   * the selection with the clicked id (or clears it if that was the
   * only selected id); shift-click toggles the clicked id inside the
   * current selection (add if absent, remove if present).
   *
   * Combination inside this list is OR (v0.7.4 — Dave's "anything
   * containing either tag" change). Empty selection means "show
   * nothing" — the sidebar starts blank until the user either picks
   * tags or clicks the All button. Combines with `selectedSeverity`
   * via AND between the two axes. */
  selected = $state<number[]>([]);
  /** Severity-group tag ids selected as a filter. Separate from
   * `selected` because the UI surfaces them in their own section
   * (below the HR divider) and the server takes them as a separate
   * query param. Combination inside this list is OR (a session has
   * exactly one severity — matching any selected severity is what the
   * user wants). Empty = no severity filter. */
  selectedSeverity = $state<number[]>([]);
  /** Whether the entire tag-filter panel is collapsed. Persisted to
   * localStorage — Daisy wants the state to survive reloads. Expanded
   * on first run. */
  panelCollapsed = $state<boolean>(readCollapsed());

  /** Derived: tags in the user-editable general group. Severity tags
   * are surfaced separately so they don't clutter the primary list. */
  generalList = $derived(this.list.filter((t) => t.tag_group !== 'severity'));
  /** Derived: tags in the severity group, sorted by the seed order
   * (Blocker → Critical → Medium → Low → Quality of Life). */
  severityList = $derived(
    this.list
      .filter((t) => t.tag_group === 'severity')
      .slice()
      .sort((a, b) => a.sort_order - b.sort_order)
  );

  hasFilter = $derived(this.selected.length > 0);
  /** True when at least one severity filter is active. Kept as its own
   * derived so the sidebar can show the severity-chip clear button
   * independently of the general-tag chip. */
  hasSeverityFilter = $derived(this.selectedSeverity.length > 0);
  /** Combined any-filter-active signal — drives things like the boot-
   * time refresh key. */
  hasAnyFilter = $derived(this.hasFilter || this.hasSeverityFilter);

  /** v0.7.4: always include `tags` (even empty) on the filter payload
   * so the API client distinguishes "nothing selected → match
   * nothing" from the legacy unfiltered path that some non-sidebar
   * callers still use. Empty-general-selection means empty session
   * list, not every session. */
  filter = $derived<api.SessionFilter>({
    tags: [...this.selected],
    severityTags:
      this.selectedSeverity.length > 0 ? [...this.selectedSeverity] : undefined
  });

  /** Finder/Explorer click semantics for the general tag list. Without
   * `additive` (plain click): if this id is the sole current selection
   * we clear it — toggle-off on solo re-click — otherwise we replace
   * the selection with just this id. With `additive` (shift-click):
   * toggle this id inside the current selection (add if absent, remove
   * if present). Either way the caller doesn't have to think about
   * previous state. */
  selectGeneral(id: number, opts: { additive?: boolean } = {}): void {
    if (opts.additive) {
      this.selected = this.selected.includes(id)
        ? this.selected.filter((x) => x !== id)
        : [...this.selected, id];
      return;
    }
    const solo = this.selected.length === 1 && this.selected[0] === id;
    this.selected = solo ? [] : [id];
  }

  /** Same Finder rules for the severity list — regular click is a
   * single-select, shift-click is additive. Kept as a separate method
   * from `selectGeneral` so the two axes stay independent (clicking a
   * severity must not touch the general selection and vice versa). */
  selectSeverity(id: number, opts: { additive?: boolean } = {}): void {
    if (opts.additive) {
      this.selectedSeverity = this.selectedSeverity.includes(id)
        ? this.selectedSeverity.filter((x) => x !== id)
        : [...this.selectedSeverity, id];
      return;
    }
    const solo =
      this.selectedSeverity.length === 1 && this.selectedSeverity[0] === id;
    this.selectedSeverity = solo ? [] : [id];
  }

  clearSelection(): void {
    this.selected = [];
  }

  clearSeveritySelection(): void {
    this.selectedSeverity = [];
  }

  /** Select every general-group tag id. Wired to the "All" button in
   * the v0.7.4 TagFilterPanel header. With OR semantics, selecting
   * every general tag is equivalent to "show every session that has
   * any tag" — which, after migration 0021's default-severity
   * backfill, is every session. */
  selectAllGeneral(): void {
    this.selected = this.generalList.map((t) => t.id);
  }

  /** Toggle the collapsed state of the whole panel and persist it. */
  togglePanel(): void {
    this.panelCollapsed = !this.panelCollapsed;
    writeCollapsed(this.panelCollapsed);
  }

  async refresh(): Promise<void> {
    this.loading = true;
    this.error = null;
    try {
      // v0.7.4: pass the current general-tag selection as scope so
      // severity counts narrow to sessions matching the sidebar's
      // current filter. Empty selection → every severity count is
      // rendered as 0, matching the empty session list the user sees
      // on the right. General counts stay absolute regardless.
      this.list = await api.listTags({ scopeTagIds: [...this.selected] });
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
      // Drop any lingering filter selection for the deleted tag in
      // both axes — otherwise the sidebar would keep a phantom id in
      // the filter payload and the server would silently ignore it.
      this.selected = this.selected.filter((x) => x !== id);
      this.selectedSeverity = this.selectedSeverity.filter((x) => x !== id);
      return true;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      return false;
    }
  }

  /** Bump the cached session_count on a tag, used after a local
   * attach/detach so the sidebar chip updates without a full refresh.
   * `openDelta` defaults to `delta` because the callsites that bump
   * on a freshly created session (always open) want both to move
   * together; SessionEdit passes 0 when operating on a closed session.
   * Clamps at 0 — never negative. */
  bumpCount(id: number, delta: number, openDelta: number = delta): void {
    this.list = this.list.map((t) =>
      t.id === id
        ? {
            ...t,
            session_count: Math.max(0, t.session_count + delta),
            open_session_count: Math.max(0, t.open_session_count + openDelta)
          }
        : t
    );
  }
}

export const tags = new TagStore();
