<script lang="ts">
  /**
   * One sidebar row — title, kind indicator, attached tag chips,
   * status indicators (pinned / closed / error).
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/chat.md`` §"opens an existing chat" — selecting
   *   the row reconnects the conversation pane. The row is rendered
   *   as an ``<a href="/sessions/{id}">`` so SvelteKit client-nav
   *   handles the URL change; the route file at
   *   ``routes/sessions/[id]/+page.svelte`` syncs the inspector store
   *   from the URL on mount. (Sign-off decision 2026-05-01:
   *   SvelteKit client-nav, no chrome flash.)
   * - §"creates a chat" — clicking a tag chip on a session row toggles
   *   that tag in the global filter set (the "finder-click" behavior).
   * - §"Error states" — the red flashing pip is the
   *   ``error_pending`` indicator; the row class also reflects the
   *   ``closed_at`` state (closed rows render in the muted/closed
   *   style).
   * - ``docs/behavior/context-menus.md`` §"Session row" — right-click
   *   opens a target-specific context menu via ``use:contextMenu``.
   *
   * The component is presentational: props in, events out via
   * callback props. ``onSelect`` is retained for the few callers that
   * still want to react to a row activation (e.g. the integration
   * tests that pre-date URL routing); the anchor's ``href`` is what
   * actually drives navigation.
   */
  import {
    closeSession,
    deleteSession,
    duplicateSession,
    patchSessionPinned,
    patchSessionTitle,
    reopenSession,
  } from "../../api/sessions";
  import type { SessionOut } from "../../api/sessions";
  import { listTags } from "../../api/tags";
  import type { TagOut } from "../../api/tags";
  import { contextMenu } from "../../actions/contextMenu";
  import {
    MENU_ACTION_SESSION_ARCHIVE,
    MENU_ACTION_SESSION_COPY_ID,
    MENU_ACTION_SESSION_COPY_TITLE,
    MENU_ACTION_SESSION_DELETE,
    MENU_ACTION_SESSION_DUPLICATE,
    MENU_ACTION_SESSION_EDIT_TAGS,
    MENU_ACTION_SESSION_OPEN_IN_NEW_TAB,
    MENU_ACTION_SESSION_PIN,
    MENU_ACTION_SESSION_RENAME,
    MENU_ACTION_SESSION_REOPEN,
    MENU_ACTION_SESSION_UNPIN,
    MENU_TARGET_SESSION,
    SESSION_KIND_CHAT,
    SIDEBAR_STRINGS,
  } from "../../config";
  import { refreshSessions } from "../../stores/sessions.svelte";
  import { tagsStore } from "../../stores/tags.svelte";
  import ConfirmDialog from "./ConfirmDialog.svelte";
  import SessionTagPicker from "./SessionTagPicker.svelte";

  interface Props {
    session: SessionOut;
    /** Tags attached to this session (cached in the sessions store). */
    tags: readonly TagOut[];
    /** Tag ids currently in the filter set — used to mark active chips. */
    selectedTagIds: ReadonlySet<number>;
    /** Selected-row highlight (the conversation pane is pointing at this row). */
    isSelected: boolean;
    /**
     * Row activation callback — fires alongside the anchor navigation
     * so callers that observed selection through this prop (existing
     * integration tests, future keyboard-nav surfaces) keep working.
     * The actual URL change is owned by the anchor's ``href``.
     */
    onSelect: (sessionId: string) => void;
    /** Tag-chip click — finder-click integration; toggles tag in filter set. */
    onToggleTag: (tagId: number) => void;
    /**
     * Reopen-button click on a closed row. Optional because
     * non-sidebar callers (e.g. the conversation header) may render
     * a row without offering reopen. When omitted the button is
     * hidden so the row stays presentational.
     */
    onReopen?: (sessionId: string) => void;
  }

  const { session, tags, selectedTagIds, isSelected, onSelect, onToggleTag, onReopen }: Props =
    $props();

  const sessionHref = $derived(`/sessions/${encodeURIComponent(session.id)}`);

  const isClosed = $derived(session.closed_at !== null);

  const kindLabel = $derived(
    SIDEBAR_STRINGS.kindIndicatorAriaLabels[
      session.kind as keyof typeof SIDEBAR_STRINGS.kindIndicatorAriaLabels
    ] ?? session.kind,
  );

  // ---- inline rename state -----------------------------------------------

  let renaming = $state(false);
  let renameValue = $state("");
  let renameError = $state<string | null>(null);

  function startRename(): void {
    renameValue = session.title;
    renameError = null;
    renaming = true;
  }

  async function commitRename(): Promise<void> {
    const trimmed = renameValue.trim();
    if (!trimmed) {
      renameError = "Title cannot be empty";
      return;
    }
    try {
      await patchSessionTitle(session.id, trimmed);
      await refreshSessions(tagsStore.selectedIds);
      renaming = false;
    } catch (err) {
      renameError = err instanceof Error ? err.message : String(err);
    }
  }

  function cancelRename(): void {
    renaming = false;
    renameError = null;
  }

  // ---- tag picker state --------------------------------------------------

  let showTagPicker = $state(false);
  let allTagsForPicker = $state<TagOut[]>([]);

  async function openTagPicker(): Promise<void> {
    try {
      allTagsForPicker = await listTags();
    } catch {
      allTagsForPicker = [];
    }
    showTagPicker = true;
  }

  async function handleTagPickerSave(): Promise<void> {
    showTagPicker = false;
    await refreshSessions(tagsStore.selectedIds);
  }

  // ---- confirm delete state ----------------------------------------------

  let showDeleteConfirm = $state(false);

  async function handleDeleteConfirm(): Promise<void> {
    showDeleteConfirm = false;
    try {
      await deleteSession(session.id);
      // The sessions broadcaster will remove the row; also force a
      // refresh so the tag-by-session map stays consistent.
      await refreshSessions(tagsStore.selectedIds);
    } catch {
      // Failure is surfaced by leaving the row in place; the next
      // refresh will show the real state.
    }
  }

  // ---- context-menu handlers ---------------------------------------------

  const menuHandlers = $derived({
    [MENU_ACTION_SESSION_OPEN_IN_NEW_TAB]: () => {
      window.open(sessionHref, "_blank", "noopener");
    },
    [MENU_ACTION_SESSION_RENAME]: startRename,
    [MENU_ACTION_SESSION_EDIT_TAGS]: () => {
      void openTagPicker();
    },
    [MENU_ACTION_SESSION_DUPLICATE]: () => {
      void duplicateSession(session).then(() => refreshSessions(tagsStore.selectedIds));
    },
    ...(session.pinned
      ? {
          [MENU_ACTION_SESSION_UNPIN]: () => {
            void patchSessionPinned(session.id, false).then(() =>
              refreshSessions(tagsStore.selectedIds),
            );
          },
        }
      : {
          [MENU_ACTION_SESSION_PIN]: () => {
            void patchSessionPinned(session.id, true).then(() =>
              refreshSessions(tagsStore.selectedIds),
            );
          },
        }),
    ...(isClosed
      ? {
          [MENU_ACTION_SESSION_REOPEN]: () => {
            void reopenSession(session.id).then(() => refreshSessions(tagsStore.selectedIds));
          },
        }
      : {
          [MENU_ACTION_SESSION_ARCHIVE]: () => {
            void closeSession(session.id).then(() => refreshSessions(tagsStore.selectedIds));
          },
        }),
    [MENU_ACTION_SESSION_COPY_ID]: () => {
      void navigator.clipboard.writeText(session.id);
    },
    [MENU_ACTION_SESSION_COPY_TITLE]: () => {
      void navigator.clipboard.writeText(session.title);
    },
    [MENU_ACTION_SESSION_DELETE]: () => {
      showDeleteConfirm = true;
    },
  });
</script>

{#if showTagPicker}
  <SessionTagPicker
    sessionId={session.id}
    currentTags={tags}
    allTags={allTagsForPicker}
    onSave={() => void handleTagPickerSave()}
    onCancel={() => {
      showTagPicker = false;
    }}
  />
{/if}

{#if showDeleteConfirm}
  <ConfirmDialog
    message={`Delete "${session.title}"? This cannot be undone.`}
    confirmLabel="Delete"
    onConfirm={() => void handleDeleteConfirm()}
    onCancel={() => {
      showDeleteConfirm = false;
    }}
  />
{/if}

{#if renaming}
  <!--
    Inline rename input. Rendered instead of the anchor when the user
    triggers the Rename context-menu action. On Enter → commit; on Esc
    → cancel. stopPropagation on keydown keeps the global Esc cascade
    from intercepting before this handler fires.
  -->
  <div
    class="session-row flex w-full flex-col gap-1 border-b border-border px-3 py-2"
    data-testid="session-row-rename"
    data-session-id={session.id}
  >
    <input
      type="text"
      class="w-full rounded border border-border bg-surface-2 px-2 py-0.5 text-sm text-fg-strong focus:outline-none focus:ring-1 focus:ring-accent"
      bind:value={renameValue}
      data-testid="session-row-rename-input"
      onkeydown={(event) => {
        event.stopPropagation();
        if (event.key === "Enter") {
          event.preventDefault();
          void commitRename();
        } else if (event.key === "Escape") {
          event.preventDefault();
          cancelRename();
        }
      }}
      onblur={() => {
        void commitRename();
      }}
    />
    {#if renameError !== null}
      <p class="text-xs text-red-400" data-testid="session-row-rename-error">{renameError}</p>
    {/if}
  </div>
{:else}
  <a
    href={sessionHref}
    class="session-row group flex w-full flex-col gap-1 border-b border-border px-3 py-2 text-left no-underline transition-colors hover:bg-surface-2"
    class:session-row--selected={isSelected}
    class:bg-surface-2={isSelected}
    class:opacity-70={isClosed}
    data-testid="session-row"
    data-session-id={session.id}
    data-sveltekit-preload-data="hover"
    aria-current={isSelected ? "true" : undefined}
    title={isClosed && session.closing_summary !== null ? session.closing_summary : undefined}
    onclick={() => onSelect(session.id)}
    use:contextMenu={{
      target: MENU_TARGET_SESSION,
      handlers: menuHandlers,
      data: { sessionId: session.id },
    }}
  >
    <span class="flex items-center gap-2">
      <span
        class="inline-block h-2 w-2 rounded-full"
        class:bg-accent={session.kind === SESSION_KIND_CHAT}
        class:bg-fg-muted={session.kind !== SESSION_KIND_CHAT}
        aria-label={kindLabel}
        data-testid="session-kind-indicator"
      ></span>
      <span class="flex-1 truncate text-sm text-fg-strong" data-testid="session-title">
        {session.title}
      </span>
      {#if session.pinned}
        <span
          class="text-xs text-accent"
          aria-label={SIDEBAR_STRINGS.pinnedIndicatorAriaLabel}
          data-testid="session-pinned-indicator"
        >
          ★
        </span>
      {/if}
      {#if session.error_pending}
        <span
          class="animate-pulse text-xs text-red-400"
          aria-label={SIDEBAR_STRINGS.errorPendingIndicatorAriaLabel}
          data-testid="session-error-indicator"
        >
          !
        </span>
      {/if}
      {#if isClosed}
        <span
          class="text-xs text-fg-muted"
          aria-label={SIDEBAR_STRINGS.closedIndicatorAriaLabel}
          data-testid="session-closed-indicator"
        >
          ◌
        </span>
        {#if onReopen !== undefined}
          <!--
            Reopen button on closed rows. ``stopPropagation`` is required
            because the row is wrapped in an anchor: a bare click would
            otherwise navigate to ``/sessions/{id}`` before the reopen
            callback fires. The button is keyboard-reachable via the
            natural tab order; the row's own ``onclick`` does not
            intercept Enter on a focused button.
          -->
          <button
            type="button"
            class="rounded border border-border bg-surface-1 px-1.5 py-0.5 text-xs text-fg hover:bg-surface-2"
            aria-label={SIDEBAR_STRINGS.reopenButtonAriaLabelTemplate(session.title)}
            data-testid="session-reopen-button"
            onclick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onReopen(session.id);
            }}
          >
            {SIDEBAR_STRINGS.reopenButtonLabel}
          </button>
        {/if}
      {/if}
    </span>

    {#if tags.length > 0}
      <span class="flex flex-wrap gap-1" data-testid="session-row-tags">
        {#each tags as tag (tag.id)}
          <!--
            The chip is rendered as a span with role="button" + a
            stopPropagation handler so clicking the chip toggles the
            tag-filter without also navigating the row's anchor href.
            (The composer-row pattern in chat.md drives the same tradeoff
            for the clickable chip on the conversation header.) Tabindex
            keeps the chip keyboard-reachable when the user tabs through
            the row.
          -->
          <span
            role="button"
            tabindex="0"
            class="rounded px-1.5 py-0.5 text-xs"
            class:bg-accent={selectedTagIds.has(tag.id)}
            class:text-fg-strong={selectedTagIds.has(tag.id)}
            class:bg-surface-2={!selectedTagIds.has(tag.id)}
            class:text-fg-muted={!selectedTagIds.has(tag.id)}
            aria-pressed={selectedTagIds.has(tag.id)}
            data-testid="session-tag-chip"
            data-tag-id={tag.id}
            onclick={(event) => {
              event.stopPropagation();
              onToggleTag(tag.id);
            }}
            onkeydown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                event.stopPropagation();
                onToggleTag(tag.id);
              }
            }}
          >
            {tag.name}
          </span>
        {/each}
      </span>
    {/if}

    <!-- Paired-chat annotation (↳ parent checklist title) -->
    {#if session.paired_parent_title}
      <span class="text-xs text-fg-muted" data-testid="session-paired-parent">
        ↳ {session.paired_parent_title}
      </span>
    {/if}
  </a>
{/if}

<style>
  /*
   * Selected-row accent — Tailwind handles bg + text via utility
   * classes; this rule supplies the inset focus ring the keyboard-nav
   * `j`/`k` selection (item 2.9) will rely on. Theme-aware via the
   * --bearings-accent CSS variable.
   */
  .session-row--selected {
    box-shadow: inset 2px 0 0 0 rgb(var(--bearings-accent));
  }
</style>
