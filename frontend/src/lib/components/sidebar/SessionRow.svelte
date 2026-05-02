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
   *
   * The component is presentational: props in, events out via
   * callback props. ``onSelect`` is retained for the few callers that
   * still want to react to a row activation (e.g. the integration
   * tests that pre-date URL routing); the anchor's ``href`` is what
   * actually drives navigation.
   */
  import { SESSION_KIND_CHAT, SIDEBAR_STRINGS } from "../../config";
  import type { SessionOut } from "../../api/sessions";
  import type { TagOut } from "../../api/tags";

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
</script>

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
        class="text-xs text-red-400"
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
</a>

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
