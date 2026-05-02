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
   *
   * Per arch §1.2 the canonical filename is ``SessionList.svelte``;
   * the master item refers to "Sidebar" generically — same surface,
   * arch-prescribed name. Closed-group, search, and bulk-action-bar
   * pieces (also arch §1.2) are scoped to later items (the done-when
   * for #537 covers list / row / filter only).
   */
  import { onMount } from "svelte";

  import { reopenSession as reopenSessionDefault, type SessionOut } from "../../api/sessions";
  import { SIDEBAR_STRINGS } from "../../config";
  import type { TagOut } from "../../api/tags";
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
  import TagFilterPanel from "../menus/TagFilterPanel.svelte";
  import SessionRow from "./SessionRow.svelte";

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

  /**
   * Fetch on mount + on every filter-set change. ``$effect`` re-runs
   * when ``tagsStore.selectedIds`` updates (Svelte 5 tracks the
   * proxy reads inside the effect's body).
   */
  onMount(() => {
    void refreshTags();
  });

  $effect(() => {
    void refreshSessions(tagsStore.selectedIds);
  });
</script>

<div class="session-list flex h-full flex-col" data-testid="session-list">
  <TagFilterPanel
    tags={tagsStore.all}
    selectedIds={tagsStore.selectedIds}
    onToggle={toggleTag}
    onClear={clearTagFilter}
  />

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
