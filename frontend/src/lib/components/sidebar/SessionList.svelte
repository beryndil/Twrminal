<script lang="ts" module>
  import { splitTagName } from "../../config";

  /**
   * Display the leaf portion of a slash-namespaced tag name as the
   * group header. ``"bearings/architect"`` → ``"architect"`` —
   * compact but still unambiguous because the section header itself
   * sits inside the sidebar's tag-rooted layout. A non-grouped tag
   * (no separator) renders unchanged. Hoisted to the module script
   * so the template body can reference it without a per-render
   * closure allocation.
   */
  export function displayLeaf(tagName: string): string {
    const [, leaf] = splitTagName(tagName);
    return leaf;
  }
</script>

<script lang="ts">
  /**
   * Sidebar container — the left-column panel that lists sessions
   * grouped by tag, with the global tag-filter at the top.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/chat.md`` §"creates a chat" — "The sidebar adds
   *   a row for the chat under each of its tags." Sessions are
   *   grouped by tag; a multi-tagged session renders once per tag
   *   group it belongs to.
   * - Master item #537 done-when — "Sidebar, tag filter, session
   *   row. Finder-click filter + OR semantics across tags." The
   *   filter set is OR semantics (a session matches when it carries
   *   ANY of the selected tags); finder-click is wired by passing
   *   :func:`toggleTag` as the row's tag-chip handler.
   * - G8 — multi-select: shift-click range-select, ctrl/cmd-click
   *   toggle, checkbox click toggle; selection bar with cancel;
   *   right-click on selected row opens ``MENU_TARGET_MULTI_SELECT``
   *   menu with add-tag, remove-tag (submenus), close, export, delete.
   *
   * Per arch §1.2 the canonical filename is ``SessionList.svelte``;
   * the master item refers to "Sidebar" generically — same surface,
   * arch-prescribed name.
   */
  import { onMount } from "svelte";

  import {
    closeSession,
    deleteSession,
    reopenSession as reopenSessionDefault,
    type SessionOut,
  } from "../../api/sessions";
  import { listMessages } from "../../api/messages";
  import {
    MENU_ACTION_MULTI_SELECT_CLEAR,
    MENU_ACTION_MULTI_SELECT_CLOSE,
    MENU_ACTION_MULTI_SELECT_DELETE,
    MENU_ACTION_MULTI_SELECT_EXPORT,
    MENU_ACTION_MULTI_SELECT_TAG,
    MENU_ACTION_MULTI_SELECT_UNTAG,
    SIDEBAR_STRINGS,
  } from "../../config";
  import { listTags, type TagOut } from "../../api/tags";
  import {
    refreshSessions as refreshSessionsDefault,
    sessionsStore as sessionsStoreDefault,
  } from "../../stores/sessions.svelte";
  import {
    clearTagFilter as clearTagFilterDefault,
    refreshTags as refreshTagsDefault,
    tagsStore as tagsStoreDefault,
    toggleTag as toggleTagDefault,
  } from "../../stores/tags.svelte";
  import { clearSelection, multiSelectionStore, setIds } from "../../stores/multiSelection.svelte";
  import { ESC_PRIORITY_MULTI_SELECT, registerEscEntry } from "../../keyboard/escCascade";
  import TagFilterPanel from "../menus/TagFilterPanel.svelte";
  import SessionRow from "./SessionRow.svelte";
  import ConfirmDialog from "./ConfirmDialog.svelte";
  import MultiSelectTagPicker from "./MultiSelectTagPicker.svelte";

  /**
   * The store/refresher dependencies are injected via props so unit
   * tests can substitute fakes without monkey-patching the module
   * cache. Production callers simply omit the props and pick up the
   * default singletons. Each prop has a defaulted symbol so the
   * production path stays one line in ``+layout.svelte``.
   */
  interface Props {
    selectedSessionId?: string | null;
    onSelect?: (sessionId: string) => void;
    sessionsStore?: typeof sessionsStoreDefault;
    tagsStore?: typeof tagsStoreDefault;
    refreshSessions?: typeof refreshSessionsDefault;
    refreshTags?: typeof refreshTagsDefault;
    toggleTag?: typeof toggleTagDefault;
    clearTagFilter?: typeof clearTagFilterDefault;
    /**
     * API client for the reopen-button on closed rows. Injected so
     * unit tests can substitute a fake without touching the network.
     */
    reopenSession?: typeof reopenSessionDefault;
  }

  const {
    selectedSessionId = null,
    onSelect = () => {},
    sessionsStore = sessionsStoreDefault,
    tagsStore = tagsStoreDefault,
    refreshSessions = refreshSessionsDefault,
    refreshTags = refreshTagsDefault,
    toggleTag = toggleTagDefault,
    clearTagFilter = clearTagFilterDefault,
    reopenSession = reopenSessionDefault,
  }: Props = $props();

  /**
   * Group the visible sessions by tag (chat.md: "the sidebar adds a
   * row for the chat under each of its tags"). A session attached to
   * tags ``A`` and ``B`` appears under both groups; an untagged
   * session falls into the ungrouped pseudo-bucket.
   *
   * The OR-filter is applied upstream by the backend (the route
   * receives ``tag_ids`` and returns matching sessions); the only
   * filter-aware projection here is hiding tag groups whose tag is
   * not in the filter set when the user has narrowed (so a session
   * tagged ``A`` + ``C`` only renders under group ``A`` when the
   * filter is ``{A}``, not also under group ``C``).
   */
  type Group = { key: string; label: string; sessions: SessionOut[] };

  function groupSessions(
    sessions: readonly SessionOut[],
    tagsBySessionId: Readonly<Record<string, readonly TagOut[]>>,
    selectedTagIds: ReadonlySet<number>,
  ): Group[] {
    const groupsByKey = new Map<string, Group>();
    const filterActive = selectedTagIds.size > 0;
    for (const session of sessions) {
      const tags = tagsBySessionId[session.id] ?? [];
      const visibleTags = filterActive ? tags.filter((tag) => selectedTagIds.has(tag.id)) : tags;
      if (visibleTags.length === 0) {
        const key = "__ungrouped__";
        ensureGroup(groupsByKey, key, SIDEBAR_STRINGS.ungroupedTagsLabel);
        groupsByKey.get(key)!.sessions.push(session);
        continue;
      }
      for (const tag of visibleTags) {
        const key = `tag:${tag.id}`;
        ensureGroup(groupsByKey, key, tag.name);
        groupsByKey.get(key)!.sessions.push(session);
      }
    }
    // Stable ordering: alphabetical by group label, with the
    // ungrouped bucket last (it carries no tag identity).
    return Array.from(groupsByKey.values()).sort((a, b) => {
      if (a.key === "__ungrouped__") return 1;
      if (b.key === "__ungrouped__") return -1;
      return a.label.localeCompare(b.label);
    });
  }

  function ensureGroup(map: Map<string, Group>, key: string, label: string): void {
    if (!map.has(key)) {
      map.set(key, { key, label, sessions: [] });
    }
  }

  /**
   * The sidebar splits ``sessionsStore.sessions`` into two cohorts:
   * open rows render in their tag groups (the default surface), and
   * closed rows surface only when the operator clicks the "Closed
   * (N)" expander at the bottom of the list. This realises the
   * Slice B4 UX intent — "default filter excludes closed sessions"
   * — without dropping closed rows from the cache (so the count is
   * accurate without an extra fetch).
   */
  const openSessions = $derived(
    sessionsStore.sessions.filter((session) => session.closed_at === null),
  );
  const closedSessions = $derived(
    sessionsStore.sessions.filter((session) => session.closed_at !== null),
  );
  const groups = $derived(
    groupSessions(openSessions, sessionsStore.tagsBySessionId, tagsStore.selectedIds),
  );

  /**
   * Local UI state — whether the closed-sessions expander is open.
   * Resets on every tag-filter change so a narrow-and-broaden cycle
   * doesn't leave a stale expanded panel pointing at the wrong rows;
   * tracked through ``$effect`` against the filter set so the
   * collapsed state is the steady-state default.
   */
  let showClosed = $state(false);
  let reopenError = $state<string | null>(null);

  $effect(() => {
    void tagsStore.selectedIds;
    showClosed = false;
  });

  async function handleReopen(sessionId: string): Promise<void> {
    try {
      reopenError = null;
      await reopenSession(sessionId);
      await refreshSessions(tagsStore.selectedIds);
    } catch (error) {
      reopenError = error instanceof Error ? error.message : String(error);
    }
  }

  // ---- Multi-select state -------------------------------------------------

  /**
   * The last session ID the user clicked without a modifier key — the
   * anchor for shift-click range-select. ``null`` before any click.
   */
  let lastAnchorId = $state<string | null>(null);

  /**
   * Flat, deduplicated, ordered list of session IDs currently visible
   * in the sidebar (open groups + closed rows when expanded). Used to
   * compute the range for shift-click selection.
   *
   * A session appearing in multiple tag groups is deduplicated: we use
   * the first occurrence in group order to establish position.
   */
  const flatSessionIds = $derived.by(() => {
    const seen = new Set<string>();
    const ids: string[] = [];
    for (const group of groups) {
      for (const s of group.sessions) {
        if (!seen.has(s.id)) {
          seen.add(s.id);
          ids.push(s.id);
        }
      }
    }
    if (showClosed) {
      for (const s of closedSessions) {
        if (!seen.has(s.id)) {
          seen.add(s.id);
          ids.push(s.id);
        }
      }
    }
    return ids;
  });

  /**
   * Handle shift-click range-select: select every session between
   * ``lastAnchorId`` and ``targetId`` (inclusive).
   */
  function handleShiftClick(targetId: string): void {
    const ids = flatSessionIds;
    if (lastAnchorId === null) {
      // No anchor yet — treat the target as a plain toggle.
      const next = new Set(multiSelectionStore.ids);
      next.add(targetId);
      setIds(next);
      lastAnchorId = targetId;
      return;
    }
    const anchorIdx = ids.indexOf(lastAnchorId);
    const targetIdx = ids.indexOf(targetId);
    if (anchorIdx === -1 || targetIdx === -1) {
      // One of the rows disappeared — fall back to plain toggle.
      const next = new Set(multiSelectionStore.ids);
      next.add(targetId);
      setIds(next);
      lastAnchorId = targetId;
      return;
    }
    const lo = Math.min(anchorIdx, targetIdx);
    const hi = Math.max(anchorIdx, targetIdx);
    // Add the range to whatever is already selected (Finder semantics).
    const next = new Set(multiSelectionStore.ids);
    for (let i = lo; i <= hi; i++) {
      const id = ids[i];
      if (id !== undefined) next.add(id);
    }
    setIds(next);
    // Do not move the anchor on shift-click.
  }

  // ---- Tag picker state (add / remove submenu) ----------------------------

  let tagPickerMode = $state<"add" | "remove" | null>(null);
  let allTagsForPicker = $state<TagOut[]>([]);

  /**
   * Tags common to ALL currently selected sessions — used for the
   * "Remove tag" submenu (only shows tags that can actually be removed
   * from every selection member).
   */
  const commonTagsForRemove = $derived.by(() => {
    const ids = Array.from(multiSelectionStore.ids);
    if (ids.length === 0) return [] as TagOut[];
    // Build a Set of tag IDs for each selected session.
    const tagIdSets = ids.map(
      (sid) => new Set((sessionsStore.tagsBySessionId[sid] ?? []).map((t) => t.id)),
    );
    const [firstSet, ...restSets] = tagIdSets;
    if (firstSet === undefined) return [] as TagOut[];
    // Intersection: keep only IDs present in every set.
    const commonIds = new Set(firstSet);
    for (const s of restSets) {
      for (const tid of commonIds) {
        if (!s.has(tid)) commonIds.delete(tid);
      }
    }
    // Resolve IDs back to full TagOut objects from the global tag list.
    const byId = new Map(tagsStore.all.map((t) => [t.id, t]));
    return Array.from(commonIds).flatMap((tid) => {
      const tag = byId.get(tid);
      return tag !== undefined ? [tag] : [];
    });
  });

  async function openTagPicker(mode: "add" | "remove"): Promise<void> {
    if (mode === "add") {
      try {
        allTagsForPicker = await listTags();
      } catch {
        allTagsForPicker = [];
      }
    }
    tagPickerMode = mode;
  }

  async function handleTagPickerDone(): Promise<void> {
    tagPickerMode = null;
    await refreshSessions(tagsStore.selectedIds);
    clearSelection();
  }

  // ---- Multi-select delete confirm ----------------------------------------

  let showMultiDeleteConfirm = $state(false);

  async function handleMultiDeleteConfirm(): Promise<void> {
    showMultiDeleteConfirm = false;
    const ids = Array.from(multiSelectionStore.ids);
    await Promise.allSettled(ids.map((id) => deleteSession(id)));
    clearSelection();
    await refreshSessions(tagsStore.selectedIds);
  }

  // ---- Multi-select close -------------------------------------------------

  async function handleMultiClose(): Promise<void> {
    const ids = Array.from(multiSelectionStore.ids);
    await Promise.allSettled(ids.map((id) => closeSession(id)));
    clearSelection();
    await refreshSessions(tagsStore.selectedIds);
  }

  // ---- Multi-select export ------------------------------------------------

  /**
   * Export selected sessions as a JSON file. Each entry is a
   * ``{ session, messages }`` object. Messages are fetched with a
   * large limit (best-effort all-messages; sessions with >10 000
   * messages will be truncated at the last 10 000).
   */
  async function handleMultiExport(): Promise<void> {
    const ids = Array.from(multiSelectionStore.ids);
    const sessionMap = new Map(sessionsStore.sessions.map((s) => [s.id, s]));
    const entries = await Promise.all(
      ids.map(async (id) => {
        const session = sessionMap.get(id);
        let messages: unknown[] = [];
        try {
          const page = await listMessages(id, { limit: 10000 });
          messages = page.items;
        } catch {
          // Non-fatal — export the session metadata without messages.
        }
        return { session, messages };
      }),
    );
    const json = JSON.stringify(entries, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `bearings-export-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // ---- Multi-select context-menu handlers --------------------------------

  /**
   * Handler map for ``MENU_TARGET_MULTI_SELECT``. Passed as a prop to
   * every ``SessionRow`` so right-clicking a selected row opens the
   * correct multi-select menu rather than the per-row session menu.
   */
  const multiSelectHandlers = $derived({
    [MENU_ACTION_MULTI_SELECT_CLEAR]: clearSelection,
    [MENU_ACTION_MULTI_SELECT_TAG]: () => {
      void openTagPicker("add");
    },
    [MENU_ACTION_MULTI_SELECT_UNTAG]: () => {
      void openTagPicker("remove");
    },
    [MENU_ACTION_MULTI_SELECT_CLOSE]: () => {
      void handleMultiClose();
    },
    [MENU_ACTION_MULTI_SELECT_EXPORT]: () => {
      void handleMultiExport();
    },
    [MENU_ACTION_MULTI_SELECT_DELETE]: () => {
      showMultiDeleteConfirm = true;
    },
  });

  /**
   * Fetch on mount + on every filter-set change. ``$effect`` re-runs
   * when ``tagsStore.selectedIds`` updates (Svelte 5 tracks the
   * proxy reads inside the effect's body).
   */
  onMount(() => {
    void refreshTags();
    // Register the Esc cascade entry so pressing Esc while a selection
    // is active clears it before any input blur fires.
    return registerEscEntry({
      priority: ESC_PRIORITY_MULTI_SELECT,
      isOpen: () => multiSelectionStore.ids.size > 0,
      close: clearSelection,
    });
  });

  $effect(() => {
    void refreshSessions(tagsStore.selectedIds);
  });
</script>

<!--
  Multi-select tag picker modal — rendered outside the nav so it
  stacks above the sidebar at z-index 200 (same layer as other dialogs).
-->
{#if tagPickerMode !== null}
  <MultiSelectTagPicker
    mode={tagPickerMode}
    tags={tagPickerMode === "add" ? allTagsForPicker : commonTagsForRemove}
    selectedSessionIds={multiSelectionStore.ids}
    onDone={() => void handleTagPickerDone()}
    onCancel={() => {
      tagPickerMode = null;
    }}
  />
{/if}

{#if showMultiDeleteConfirm}
  <ConfirmDialog
    message={`Delete ${multiSelectionStore.ids.size} session${multiSelectionStore.ids.size === 1 ? "" : "s"}? This cannot be undone.`}
    confirmLabel="Delete"
    onConfirm={() => void handleMultiDeleteConfirm()}
    onCancel={() => {
      showMultiDeleteConfirm = false;
    }}
  />
{/if}

<div class="session-list flex h-full flex-col" data-testid="session-list">
  <TagFilterPanel
    tags={tagsStore.all}
    selectedIds={tagsStore.selectedIds}
    onToggle={toggleTag}
    onClear={clearTagFilter}
  />

  <!--
    Selection bar — shown when ≥1 session is in the multi-select set.
    Gives the user a clear affordance for the active selection count
    and a one-click escape hatch.
  -->
  {#if multiSelectionStore.ids.size > 0}
    <div
      class="session-list__selection-bar"
      role="status"
      aria-live="polite"
      data-testid="session-list-selection-bar"
    >
      <span class="session-list__selection-count" data-testid="session-list-selection-count">
        {SIDEBAR_STRINGS.multiSelectBarLabel(multiSelectionStore.ids.size)}
      </span>
      <button
        type="button"
        class="session-list__selection-clear"
        aria-label={SIDEBAR_STRINGS.multiSelectBarClearLabel}
        data-testid="session-list-selection-clear"
        onclick={clearSelection}
      >
        {SIDEBAR_STRINGS.multiSelectBarClearLabel}
      </button>
    </div>
  {/if}

  <nav
    class="flex-1 overflow-y-auto"
    aria-label={SIDEBAR_STRINGS.sessionsLabel}
    data-testid="session-list-body"
  >
    {#if sessionsStore.loading && sessionsStore.sessions.length === 0}
      <p class="px-3 py-2 text-xs text-fg-muted" data-testid="session-list-loading">
        {SIDEBAR_STRINGS.loadingSessions}
      </p>
    {:else if sessionsStore.error !== null}
      <p class="px-3 py-2 text-xs text-red-400" data-testid="session-list-error">
        {SIDEBAR_STRINGS.loadFailed}
      </p>
    {:else if groups.length === 0 && closedSessions.length === 0}
      <p class="px-3 py-2 text-xs text-fg-muted" data-testid="session-list-empty">
        {tagsStore.selectedIds.size > 0
          ? SIDEBAR_STRINGS.emptySessionList
          : SIDEBAR_STRINGS.emptySessionListUnfiltered}
      </p>
    {:else}
      {#each groups as group (group.key)}
        <section
          class="session-list__group"
          data-testid="session-list-group"
          data-group-key={group.key}
        >
          <header
            class="bg-surface-1 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-fg-muted"
            data-testid="session-list-group-label"
          >
            {group.key === "__ungrouped__" ? group.label : displayLeaf(group.label)}
          </header>
          {#each group.sessions as session (`${group.key}:${session.id}`)}
            <SessionRow
              {session}
              tags={sessionsStore.tagsBySessionId[session.id] ?? []}
              selectedTagIds={tagsStore.selectedIds}
              isSelected={selectedSessionId === session.id}
              {onSelect}
              onToggleTag={toggleTag}
              {multiSelectHandlers}
              onShiftClick={(id) => {
                handleShiftClick(id);
              }}
              onUpdateAnchor={(id) => {
                lastAnchorId = id;
              }}
            />
          {/each}
        </section>
      {/each}
      {#if closedSessions.length > 0}
        <section
          class="session-list__closed border-t border-border"
          data-testid="session-list-closed-section"
        >
          <button
            type="button"
            class="flex w-full items-center justify-between bg-surface-1 px-3 py-1 text-left text-xs font-semibold uppercase tracking-wider text-fg-muted hover:bg-surface-2"
            aria-expanded={showClosed}
            aria-label={showClosed
              ? SIDEBAR_STRINGS.closedToggleAriaExpanded
              : SIDEBAR_STRINGS.closedToggleAriaCollapsed}
            data-testid="session-list-closed-toggle"
            onclick={() => {
              showClosed = !showClosed;
            }}
          >
            <span>{SIDEBAR_STRINGS.closedToggleExpandLabel(closedSessions.length)}</span>
            <span aria-hidden="true">{showClosed ? "▾" : "▸"}</span>
          </button>
          {#if showClosed}
            <div data-testid="session-list-closed-rows">
              {#each closedSessions as session (`closed:${session.id}`)}
                <SessionRow
                  {session}
                  tags={sessionsStore.tagsBySessionId[session.id] ?? []}
                  selectedTagIds={tagsStore.selectedIds}
                  isSelected={selectedSessionId === session.id}
                  {onSelect}
                  onToggleTag={toggleTag}
                  {multiSelectHandlers}
                  onShiftClick={(id) => {
                    handleShiftClick(id);
                  }}
                  onUpdateAnchor={(id) => {
                    lastAnchorId = id;
                  }}
                  onReopen={(id) => {
                    void handleReopen(id);
                  }}
                />
              {/each}
              {#if reopenError !== null}
                <p class="px-3 py-1 text-xs text-red-400" data-testid="session-list-reopen-error">
                  {SIDEBAR_STRINGS.reopenFailedLabel}
                </p>
              {/if}
            </div>
          {/if}
        </section>
      {/if}
    {/if}
  </nav>
</div>

<style>
  .session-list__selection-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.375rem 0.75rem;
    background: rgba(var(--bearings-accent), 0.15);
    border-bottom: 1px solid rgb(var(--bearings-border));
    font-size: 0.75rem;
  }

  .session-list__selection-count {
    color: rgb(var(--bearings-fg-strong));
    font-weight: 500;
  }

  .session-list__selection-clear {
    padding: 0.125rem 0.5rem;
    border-radius: 0.25rem;
    font-size: 0.75rem;
    color: rgb(var(--bearings-fg-muted));
    background: transparent;
    border: 1px solid rgb(var(--bearings-border));
    cursor: pointer;
  }

  .session-list__selection-clear:hover {
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg));
  }
</style>
