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
    exportSessionJson,
    patchSessionPinned,
    patchSessionTitle,
    reopenSession,
  } from "../../api/sessions";
  import type { SessionOut } from "../../api/sessions";
  import { listTags } from "../../api/tags";
  import type { TagOut } from "../../api/tags";
  import { createTemplate } from "../../api/templates";
  import { contextMenu } from "../../actions/contextMenu";
  import {
    MENU_ACTION_SESSION_ARCHIVE,
    MENU_ACTION_SESSION_COPY_ID,
    MENU_ACTION_SESSION_COPY_TITLE,
    MENU_ACTION_SESSION_DELETE,
    MENU_ACTION_SESSION_DUPLICATE,
    MENU_ACTION_SESSION_EDIT_TAGS,
    MENU_ACTION_SESSION_EXPORT_JSON,
    MENU_ACTION_SESSION_OPEN_IN_NEW_TAB,
    MENU_ACTION_SESSION_OPEN_IN_TERMINAL,
    MENU_ACTION_SESSION_PIN,
    MENU_ACTION_SESSION_RENAME,
    MENU_ACTION_SESSION_REOPEN,
    MENU_ACTION_SESSION_SAVE_AS_TEMPLATE,
    MENU_ACTION_SESSION_UNPIN,
    MENU_TARGET_MULTI_SELECT,
    MENU_TARGET_SESSION,
    SESSION_KIND_CHAT,
    SIDEBAR_STRINGS,
  } from "../../config";
  import { shellOpenInTerminal } from "../../api/shell";
  import { showShellOpError } from "../../stores/shellOpNotification.svelte";
  import { refreshSessions } from "../../stores/sessions.svelte";
  import { currentFilter } from "../../stores/tags.svelte";
  import {
    clearSelection,
    multiSelectionStore,
    toggleId,
  } from "../../stores/multiSelection.svelte";
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
    /**
     * Tag-chip click — finder-click integration; toggles the tag in
     * its class section's filter set. The class is sourced from
     * ``TagOut.class_`` at the click site so the parent doesn't need
     * to look it up.
     */
    onToggleTag: (tagId: number, klass: TagOut["class_"]) => void;
    /**
     * Reopen-button click on a closed row. Optional because
     * non-sidebar callers (e.g. the conversation header) may render
     * a row without offering reopen. When omitted the button is
     * hidden so the row stays presentational.
     */
    onReopen?: (sessionId: string) => void;
    /**
     * Shift-click callback — called when the user shift-clicks this
     * row to trigger a range-select. Provided by :class:`SessionList`.
     * When omitted shift-click falls through to plain navigation.
     */
    onShiftClick?: (sessionId: string) => void;
    /**
     * Handlers for the ``MENU_TARGET_MULTI_SELECT`` context menu.
     * Provided by :class:`SessionList` so all selected-row menus
     * share the same wired actions.
     */
    multiSelectHandlers?: Readonly<Record<string, () => void>>;
    /**
     * Called on plain click and ctrl/cmd-click so :class:`SessionList`
     * can track the last non-shift click as the anchor for the next
     * shift-click range-select. Optional — omitting it disables anchor
     * tracking on this row (harmless for callers that don't use the
     * multi-select feature).
     */
    onUpdateAnchor?: (sessionId: string) => void;
  }

  const {
    session,
    tags,
    selectedTagIds,
    isSelected,
    onSelect,
    onToggleTag,
    onReopen,
    onShiftClick,
    multiSelectHandlers = {},
    onUpdateAnchor,
  }: Props = $props();

  /** Whether this row is part of the current multi-select set. */
  const isInSelection = $derived(multiSelectionStore.ids.has(session.id));

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
      await refreshSessions(currentFilter());
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
    await refreshSessions(currentFilter());
  }

  // ---- confirm delete state ----------------------------------------------

  let showDeleteConfirm = $state(false);

  async function handleDeleteConfirm(): Promise<void> {
    showDeleteConfirm = false;
    try {
      await deleteSession(session.id);
      // The sessions broadcaster will remove the row; also force a
      // refresh so the tag-by-session map stays consistent.
      await refreshSessions(currentFilter());
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
      void duplicateSession(session).then(() => refreshSessions(currentFilter()));
    },
    [MENU_ACTION_SESSION_SAVE_AS_TEMPLATE]: () => {
      const name = window.prompt("Save as template — enter a name:", session.title);
      if (!name || name.trim() === "") return;
      void createTemplate({
        name: name.trim(),
        model: session.model,
        permission_profile: session.permission_mode ?? "standard",
        working_dir_default: session.working_dir,
      }).catch(() => {
        // Non-fatal — the user sees no feedback in v1 beyond the lack of
        // template appearing in the picker; a 409 collision is the most
        // common failure (duplicate name).
      });
    },
    ...(session.pinned
      ? {
          [MENU_ACTION_SESSION_UNPIN]: () => {
            void patchSessionPinned(session.id, false).then(() => refreshSessions(currentFilter()));
          },
        }
      : {
          [MENU_ACTION_SESSION_PIN]: () => {
            void patchSessionPinned(session.id, true).then(() => refreshSessions(currentFilter()));
          },
        }),
    ...(isClosed
      ? {
          [MENU_ACTION_SESSION_REOPEN]: () => {
            void reopenSession(session.id).then(() => refreshSessions(currentFilter()));
          },
        }
      : {
          [MENU_ACTION_SESSION_ARCHIVE]: () => {
            void closeSession(session.id).then(() => refreshSessions(currentFilter()));
          },
        }),
    [MENU_ACTION_SESSION_COPY_ID]: () => {
      void navigator.clipboard.writeText(session.id);
    },
    [MENU_ACTION_SESSION_COPY_TITLE]: () => {
      void navigator.clipboard.writeText(session.title);
    },
    [MENU_ACTION_SESSION_EXPORT_JSON]: () => {
      void exportSessionJson(session);
    },
    [MENU_ACTION_SESSION_DELETE]: () => {
      showDeleteConfirm = true;
    },
    // Open in terminal — advanced; only wired when working_dir is set.
    ...(session.working_dir !== null &&
    session.working_dir !== undefined &&
    session.working_dir !== ""
      ? {
          [MENU_ACTION_SESSION_OPEN_IN_TERMINAL]: () => {
            void shellOpenInTerminal(session.working_dir as string).catch(
              (err: unknown) => {
                const detail = err instanceof Error ? err.message : "unknown error";
                showShellOpError(detail);
              },
            );
          },
        }
      : {}),
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
    class:session-row--in-selection={isInSelection}
    class:bg-surface-2={isSelected}
    class:opacity-70={isClosed}
    data-testid="session-row"
    data-session-id={session.id}
    data-sveltekit-preload-data="hover"
    aria-current={isSelected ? "true" : undefined}
    title={isClosed && session.closing_summary !== null ? session.closing_summary : undefined}
    onclick={(event) => {
      if (event.ctrlKey || event.metaKey) {
        // Ctrl/Cmd-click: toggle this row in the multi-select set.
        event.preventDefault();
        toggleId(session.id);
        onUpdateAnchor?.(session.id);
        return;
      }
      if (event.shiftKey) {
        // Shift-click: range-select from the last anchor to this row.
        event.preventDefault();
        onShiftClick?.(session.id);
        // Anchor is NOT updated on shift-click (Finder semantics).
        return;
      }
      // Plain click: clear any active selection, then navigate.
      if (multiSelectionStore.ids.size > 0) {
        clearSelection();
      }
      onUpdateAnchor?.(session.id);
      onSelect(session.id);
    }}
    use:contextMenu={{
      target: isInSelection ? MENU_TARGET_MULTI_SELECT : MENU_TARGET_SESSION,
      handlers: isInSelection ? multiSelectHandlers : menuHandlers,
      data: { sessionId: session.id },
    }}
  >
    <span class="flex items-center gap-2">
      <!--
        Multi-select checkbox — visible when the row is in the selection
        or when the user hovers (CSS group-hover). Clicking the checkbox
        toggles the row without navigating, so stopPropagation is required
        to prevent the anchor's onclick from also firing.
      -->
      <span
        role="checkbox"
        tabindex="0"
        aria-checked={isInSelection}
        aria-label={SIDEBAR_STRINGS.multiSelectBarAriaLabel}
        class="session-row__checkbox"
        class:session-row__checkbox--checked={isInSelection}
        data-testid="session-row-checkbox"
        onclick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          toggleId(session.id);
        }}
        onkeydown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            event.stopPropagation();
            toggleId(session.id);
          }
        }}
      ></span>
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
              onToggleTag(tag.id, tag.class_);
            }}
            onkeydown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                event.stopPropagation();
                onToggleTag(tag.id, tag.class_);
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

  /* Multi-select highlight — row tinted when it is part of the selection set. */
  .session-row--in-selection {
    background: rgba(var(--bearings-accent), 0.12);
  }

  /*
   * Checkbox — hidden by default; revealed on hover (group-hover via the
   * parent's ``group`` class) or when the row is checked. The element is
   * a styled span with role="checkbox" to avoid breaking the anchor's
   * click semantics.
   */
  .session-row__checkbox {
    display: inline-block;
    width: 0.875rem;
    height: 0.875rem;
    border-radius: 0.1875rem;
    border: 1.5px solid rgb(var(--bearings-border));
    background: rgb(var(--bearings-surface-1));
    flex-shrink: 0;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.1s;
  }

  /* Show on hover of the parent session-row (group-hover pattern). */
  .session-row:hover .session-row__checkbox,
  .session-row__checkbox--checked {
    opacity: 1;
  }

  /* Checked state — filled with accent colour. */
  .session-row__checkbox--checked {
    background: rgb(var(--bearings-accent));
    border-color: rgb(var(--bearings-accent));
  }

  /* Focus ring for keyboard accessibility. */
  .session-row__checkbox:focus-visible {
    outline: 2px solid rgb(var(--bearings-accent));
    outline-offset: 1px;
  }
</style>
