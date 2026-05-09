<script lang="ts" module>
  import type { VaultEntryOut, VaultDocOut, RedactionOut } from "../../api/vault";

  /**
   * Apply ``redactions`` to ``body`` and return a list of segments
   * suitable for inline rendering. Each segment is either:
   *
   * - kind ``"text"`` — plain markdown body that the renderer paints
   *   as-is;
   * - kind ``"redaction"`` — a slice that should render as a mask
   *   glyph + a Show/Hide toggle (vault.md §"Redaction rendering").
   *
   * Exported so the unit tests can assert the segmentation without
   * mounting the component.
   */
  export interface BodySegment {
    kind: "text" | "redaction";
    text: string;
    /** Index into the parent body's redaction list (``"redaction"`` only). */
    redactionIndex: number | null;
  }

  export function segmentBody(body: string, redactions: readonly RedactionOut[]): BodySegment[] {
    if (redactions.length === 0) {
      return [{ kind: "text", text: body, redactionIndex: null }];
    }
    const sorted = [...redactions]
      .map((r, idx) => ({ ...r, idx }))
      .sort((a, b) => a.offset - b.offset);
    const segments: BodySegment[] = [];
    let cursor = 0;
    for (const r of sorted) {
      if (r.offset > cursor) {
        segments.push({
          kind: "text",
          text: body.slice(cursor, r.offset),
          redactionIndex: null,
        });
      }
      const end = r.offset + r.length;
      segments.push({
        kind: "redaction",
        text: body.slice(r.offset, end),
        redactionIndex: r.idx,
      });
      cursor = end;
    }
    if (cursor < body.length) {
      segments.push({ kind: "text", text: body.slice(cursor), redactionIndex: null });
    }
    return segments;
  }

  /**
   * Format the empty-state copy with the configured plan roots /
   * todo globs (vault.md §"empty state" — "No plans found under
   * <configured roots>. No TODO.md files match <configured globs>").
   * Exported for the test surface.
   */
  export function formatEmptyConfigCopy(
    template: string,
    planRoots: readonly string[],
    todoGlobs: readonly string[],
  ): string {
    const planList = planRoots.length === 0 ? "(none)" : planRoots.join(", ");
    const todoList = todoGlobs.length === 0 ? "(none)" : todoGlobs.join(", ");
    return template.replace("{plan_roots}", planList).replace("{todo_globs}", todoList);
  }

  /**
   * Pick the row's display label: the doc title when present, the
   * slug otherwise (vault.md §"When the user opens the vault" — "the
   * title (or, when no `# heading` exists, the slug)").
   */
  export function entryLabel(entry: VaultEntryOut): string {
    return entry.title ?? entry.slug;
  }

  /**
   * Extract the parent directory short name from an absolute path
   * (F7-RT-00; vault.md §"When the user opens the vault" — "the parent
   * directory short name").
   *
   * ``/home/u/.claude/plans/foo.md`` → ``plans``
   * ``/home/u/Projects/my-project/TODO.md`` → ``my-project``
   *
   * Returns an empty string when the path has no discernible parent
   * (fewer than two non-empty path segments).
   */
  export function parentDirName(path: string): string {
    const parts = path.split("/").filter((p) => p.length > 0);
    return parts.length >= 2 ? (parts[parts.length - 2] ?? "") : "";
  }

  /**
   * Format a Unix timestamp in **seconds** as a human-readable
   * relative-time string (F7-RT-00; vault.md §"When the user opens the
   * vault" — "a relative mtime ('2 days ago')").
   *
   * Tiers: < 60 s → "Xs ago" · < 3600 s → "Xm ago" ·
   * < 86 400 s → "Xh ago" · otherwise → "Xd ago".
   *
   * ``nowMs`` defaults to ``Date.now()`` and is exposed as a parameter
   * so unit tests can supply a fixed clock without mocking globals.
   */
  export function formatRelativeTime(mtimeSec: number, nowMs: number = Date.now()): string {
    const diffSec = Math.max(0, Math.floor((nowMs - mtimeSec * 1000) / 1000));
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHour = Math.floor(diffMin / 60);
    if (diffHour < 24) return `${diffHour}h ago`;
    return `${Math.floor(diffHour / 24)}d ago`;
  }
</script>

<script lang="ts">
  /**
   * VaultPanel — read-only browser over the user's planning markdown
   * (item 2.10; ``docs/behavior/vault.md``).
   *
   * Renders three concerns inside one pane:
   *
   * 1. A search input (debounced, case-insensitive substring per
   *    vault.md §"Search semantics").
   * 2. A bucketed list (Plans + Todos) when the search query is
   *    empty, OR a flat hits list when a query is active.
   * 3. A reading panel for the currently-selected doc — rendered
   *    Markdown body with redaction toggles + paste-into-message
   *    affordances.
   *
   * Per vault.md §"CRUD flow" the vault is **read-only**. This
   * component intentionally exposes no Create / Update / Delete
   * affordances on entries — only the explicit "refresh" action that
   * triggers a fresh server-side rescan. Tests assert no write
   * affordances appear in the rendered DOM.
   */
  import { onMount } from "svelte";

  import {
    VAULT_KIND_PLAN,
    VAULT_KIND_TODO,
    VAULT_REDACTION_MASK_GLYPH,
    VAULT_SEARCH_DEBOUNCE_MS,
    VAULT_SEARCH_RESULT_CAP,
    VAULT_SEARCH_SNIPPET_MAX_CHARS,
    VAULT_STRINGS,
  } from "../../config";
  import {
    clearVaultSelection as clearVaultSelectionDefault,
    refreshVault as refreshVaultDefault,
    selectVaultDoc as selectVaultDocDefault,
    setVaultSearchQuery as setVaultSearchQueryDefault,
    vaultStore as vaultStoreDefault,
  } from "../../stores/vault.svelte";
  import {
    pasteIntoComposer as pasteIntoComposerDefault,
    type PendingPaste,
  } from "../../stores/composerBridge.svelte";
  import { renderMarkdownWithLinkifier as renderMarkdownDefault } from "../../render";
  import { sanitizeHtml as sanitizeHtmlDefault } from "../../sanitize";

  interface Props {
    /**
     * Active chat session id — paste-into-composer affordances
     * require one. ``null`` shows the affordances disabled with a
     * tooltip per vault.md (the user can still copy to clipboard).
     */
    activeSessionId?: string | null;
    // Test-injectable seams.
    vaultStore?: typeof vaultStoreDefault;
    refreshVault?: typeof refreshVaultDefault;
    selectVaultDoc?: typeof selectVaultDocDefault;
    clearVaultSelection?: typeof clearVaultSelectionDefault;
    setVaultSearchQuery?: typeof setVaultSearchQueryDefault;
    pasteIntoComposer?: typeof pasteIntoComposerDefault;
    renderMarkdown?: typeof renderMarkdownDefault;
    sanitizeHtml?: typeof sanitizeHtmlDefault;
    /** Clipboard write — injectable for tests + non-secure-context fallback. */
    writeClipboard?: (text: string) => Promise<void>;
  }

  const {
    activeSessionId = null,
    vaultStore = vaultStoreDefault,
    refreshVault = refreshVaultDefault,
    selectVaultDoc = selectVaultDocDefault,
    clearVaultSelection = clearVaultSelectionDefault,
    setVaultSearchQuery = setVaultSearchQueryDefault,
    pasteIntoComposer = pasteIntoComposerDefault,
    renderMarkdown = renderMarkdownDefault,
    sanitizeHtml = sanitizeHtmlDefault,
    writeClipboard = defaultWriteClipboard,
  }: Props = $props();

  let searchInput = $state("");
  let searchDebounceHandle = $state<ReturnType<typeof setTimeout> | null>(null);
  let revealedRedactions = $state<ReadonlySet<number>>(new Set<number>());
  let renderedHtml = $state("");
  let toast = $state<string | null>(null);
  /**
   * Session explicitly pinned to this vault reader via the "Open
   * against this session" affordance (F7-RT-02; vault.md §"Tag
   * association"). When set, paste operations target this id instead
   * of ``activeSessionId`` so the user can lock a session even after
   * navigating away from it.
   */
  let pinnedSessionId = $state<string | null>(null);

  /**
   * Default clipboard write — uses :data:`navigator.clipboard.writeText`
   * when available; otherwise resolves silently. Tests inject a stub.
   * Async inside ``Promise.resolve(...)`` because vitest's jsdom
   * doesn't ship a clipboard polyfill.
   */
  async function defaultWriteClipboard(text: string): Promise<void> {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    // No-op fallback — the user still sees the toast saying "copied",
    // matching vault.md §"Common behavior across every menu" → toast.
    void text;
  }

  // Render the selected doc's body whenever it changes. The
  // sanitization layer (item 2.3) is mandatory for ``{@html}``.
  $effect(() => {
    const doc = vaultStore.selected;
    if (doc === null) {
      renderedHtml = "";
      return;
    }
    void (async () => {
      const html = await renderMarkdown(buildBodyForRender(doc));
      renderedHtml = sanitizeHtml(html);
    })();
  });

  /**
   * Reset revealed-redactions whenever the selected doc changes —
   * vault.md §"Redaction rendering" — "Persists no toggle state.
   * Re-opening the doc renders it masked again."
   */
  $effect(() => {
    void vaultStore.selected;
    revealedRedactions = new Set<number>();
  });

  function buildBodyForRender(doc: VaultDocOut): string {
    if (doc.redactions.length === 0) return doc.body;
    // Replace each redaction range with the mask glyph (or the literal
    // value when revealed) before handing the body to marked, so the
    // sanitized HTML carries the masked text. The original body is
    // preserved on the wire shape; the clipboard / paste paths read
    // from ``doc.body`` directly so they always operate on the literal.
    let cursor = 0;
    const out: string[] = [];
    const sorted = [...doc.redactions]
      .map((r, idx) => ({ ...r, idx }))
      .sort((a, b) => a.offset - b.offset);
    for (const r of sorted) {
      if (r.offset > cursor) {
        out.push(doc.body.slice(cursor, r.offset));
      }
      out.push(
        revealedRedactions.has(r.idx)
          ? doc.body.slice(r.offset, r.offset + r.length)
          : VAULT_REDACTION_MASK_GLYPH,
      );
      cursor = r.offset + r.length;
    }
    if (cursor < doc.body.length) {
      out.push(doc.body.slice(cursor));
    }
    return out.join("");
  }

  function toggleRedaction(idx: number): void {
    const next = new Set(revealedRedactions);
    if (next.has(idx)) {
      next.delete(idx);
    } else {
      next.add(idx);
    }
    revealedRedactions = next;
  }

  function handleSearchInput(value: string): void {
    searchInput = value;
    if (searchDebounceHandle !== null) {
      clearTimeout(searchDebounceHandle);
    }
    searchDebounceHandle = setTimeout(() => {
      searchDebounceHandle = null;
      void setVaultSearchQuery(value);
    }, VAULT_SEARCH_DEBOUNCE_MS);
  }

  async function handleSelectEntry(entryId: number): Promise<void> {
    await selectVaultDoc(entryId);
  }

  function handleDragStartVaultRow(entry: VaultEntryOut, event: DragEvent): void {
    if (event.dataTransfer === null) return;
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setData("text/plain", entry.markdown_link);
    // Optional: set a custom drag image (simplified — just use text)
  }

  async function handleCopyMarkdownLink(entry: VaultEntryOut): Promise<void> {
    await writeClipboard(entry.markdown_link);
    showToast(VAULT_STRINGS.pasteToastClipboardLink);
  }

  async function handleCopyBody(doc: VaultDocOut): Promise<void> {
    await writeClipboard(doc.body);
    showToast(VAULT_STRINGS.pasteToastClipboardBody);
  }

  function handlePasteLinkIntoComposer(entry: VaultEntryOut): void {
    const targetSession = pinnedSessionId ?? activeSessionId;
    if (targetSession === null) {
      showToast(VAULT_STRINGS.pasteToastNoActiveSession);
      return;
    }
    const paste: PendingPaste = {
      sessionId: targetSession,
      text: entry.markdown_link,
      kind: "link",
    };
    pasteIntoComposer(paste);
    showToast(VAULT_STRINGS.pasteToastLinkPasted);
  }

  function handlePasteBodyIntoComposer(doc: VaultDocOut): void {
    const targetSession = pinnedSessionId ?? activeSessionId;
    if (targetSession === null) {
      showToast(VAULT_STRINGS.pasteToastNoActiveSession);
      return;
    }
    const paste: PendingPaste = {
      sessionId: targetSession,
      text: doc.body,
      kind: "body",
    };
    pasteIntoComposer(paste);
    showToast(VAULT_STRINGS.pasteToastBodyPasted);
  }

  /** Pin the currently-active session to this vault reader (F7-RT-02). */
  function handleOpenAgainstSession(): void {
    if (activeSessionId !== null) {
      pinnedSessionId = activeSessionId;
    }
  }

  function showToast(message: string): void {
    toast = message;
  }

  onMount(() => {
    void refreshVault();
    return () => {
      if (searchDebounceHandle !== null) {
        clearTimeout(searchDebounceHandle);
      }
      clearVaultSelection();
    };
  });

  const list = $derived(vaultStore.list);
  const searchActive = $derived(vaultStore.searchResult !== null);
  const emptyConfigCopy = $derived(
    list === null
      ? VAULT_STRINGS.emptyAll
      : formatEmptyConfigCopy(VAULT_STRINGS.emptyConfigTemplate, list.plan_roots, list.todo_globs),
  );
  const isFullyEmpty = $derived(
    list !== null && list.plans.length === 0 && list.todos.length === 0,
  );
  /**
   * Effective session id for paste-into-composer operations (F7-RT-02).
   * ``pinnedSessionId`` wins when set (user explicitly pinned a session
   * via the "Open against this session" affordance); falls back to the
   * routed ``activeSessionId`` prop.
   */
  const effectiveSessionId = $derived(pinnedSessionId ?? activeSessionId);
</script>

<section
  class="vault-panel flex h-full flex-row"
  data-testid="vault-panel"
  aria-label={VAULT_STRINGS.paneAriaLabel}
>
  <div class="vault-panel__index flex w-80 flex-col border-r border-border bg-surface-1">
    <header class="vault-panel__header border-b border-border p-3" data-testid="vault-panel-header">
      <h2 class="text-sm font-semibold text-fg-strong">{VAULT_STRINGS.paneHeading}</h2>
      <input
        type="search"
        class="vault-panel__search mt-2 w-full rounded bg-surface-2 px-2 py-1 text-sm text-fg"
        data-testid="vault-panel-search"
        aria-label={VAULT_STRINGS.searchAriaLabel}
        placeholder={VAULT_STRINGS.searchPlaceholder}
        value={searchInput}
        oninput={(event) => handleSearchInput((event.target as HTMLInputElement).value)}
      />
    </header>

    <div class="vault-panel__lists flex-1 overflow-y-auto p-2" data-testid="vault-panel-lists">
      {#if vaultStore.loading && list === null}
        <p class="text-sm text-fg-muted" data-testid="vault-panel-loading">
          {VAULT_STRINGS.loading}
        </p>
      {:else if vaultStore.error !== null && list === null}
        <p class="text-sm text-red-400" data-testid="vault-panel-error">
          {VAULT_STRINGS.loadFailed}
        </p>
      {:else if searchActive && vaultStore.searchResult !== null}
        <ul class="vault-panel__hits flex flex-col gap-1" data-testid="vault-panel-hits">
          {#if vaultStore.searchResult.hits.length === 0}
            <li class="text-sm text-fg-muted" data-testid="vault-panel-search-empty">
              {VAULT_STRINGS.searchEmptyResults}
            </li>
          {:else}
            {#each vaultStore.searchResult.hits as hit (`${hit.vault_id}-${hit.line_number}`)}
              <li class="vault-panel__hit">
                <button
                  type="button"
                  class="w-full rounded px-2 py-1 text-left text-sm hover:bg-surface-2"
                  draggable={true}
                  data-testid="vault-panel-hit"
                  data-vault-id={hit.vault_id}
                  data-line-number={hit.line_number}
                  onclick={() => handleSelectEntry(hit.vault_id)}
                  ondragstart={(event) => {
                    // Search hits don't have the full entry data, so create a minimal one for drag
                    const entry: VaultEntryOut = {
                      id: hit.vault_id,
                      path: hit.path,
                      slug: hit.path,
                      title: hit.title,
                      kind: hit.kind,
                      mtime: 0,
                      size: 0,
                      last_indexed_at: 0,
                      markdown_link: `[${hit.title ?? hit.path}](file://${hit.path})`,
                    };
                    handleDragStartVaultRow(entry, event);
                  }}
                >
                  <span class="block font-mono text-xs text-fg-muted">
                    {VAULT_STRINGS.searchHitTemplate
                      .replace("{kind}", hit.kind === VAULT_KIND_PLAN ? "Plan" : "Todo")
                      .replace("{line}", String(hit.line_number))}
                  </span>
                  <span class="block truncate text-fg">{hit.title ?? hit.path}</span>
                  <span class="block truncate text-xs text-fg-muted"
                    >{hit.snippet.length > VAULT_SEARCH_SNIPPET_MAX_CHARS
                      ? hit.snippet.slice(0, VAULT_SEARCH_SNIPPET_MAX_CHARS) + "…"
                      : hit.snippet}</span
                  >
                </button>
              </li>
            {/each}
            {#if vaultStore.searchResult.capped}
              <li class="text-xs italic text-fg-muted" data-testid="vault-panel-search-capped">
                {VAULT_STRINGS.searchCappedTemplate.replace("{n}", String(VAULT_SEARCH_RESULT_CAP))}
              </li>
            {/if}
          {/if}
        </ul>
      {:else if isFullyEmpty}
        <p class="text-sm text-fg-muted" data-testid="vault-panel-empty">
          {emptyConfigCopy}
        </p>
      {:else if list !== null}
        <section class="vault-panel__bucket" data-testid="vault-panel-bucket-plans">
          <h3 class="text-xs font-semibold uppercase tracking-wide text-fg-muted">
            {VAULT_STRINGS.plansHeading}
          </h3>
          <ul class="flex flex-col gap-0.5 py-1">
            {#each list.plans as entry (entry.id)}
              <li>
                <button
                  type="button"
                  class="w-full rounded px-2 py-1 text-left hover:bg-surface-2"
                  class:bg-surface-2={vaultStore.selected?.entry.id === entry.id}
                  draggable={true}
                  data-testid="vault-panel-row"
                  data-vault-id={entry.id}
                  data-vault-kind={VAULT_KIND_PLAN}
                  onclick={() => handleSelectEntry(entry.id)}
                  ondragstart={(event) => handleDragStartVaultRow(entry, event)}
                >
                  <span class="block truncate text-sm">{entryLabel(entry)}</span>
                  <span
                    class="flex items-baseline justify-between text-xs text-fg-muted"
                    data-testid="vault-panel-row-meta"
                  >
                    <span class="truncate">{parentDirName(entry.path)}</span>
                    <span class="ml-1 shrink-0">{formatRelativeTime(entry.mtime)}</span>
                  </span>
                </button>
              </li>
            {/each}
          </ul>
        </section>

        <section class="vault-panel__bucket pt-2" data-testid="vault-panel-bucket-todos">
          <h3 class="text-xs font-semibold uppercase tracking-wide text-fg-muted">
            {VAULT_STRINGS.todosHeading}
          </h3>
          <ul class="flex flex-col gap-0.5 py-1">
            {#each list.todos as entry (entry.id)}
              <li>
                <button
                  type="button"
                  class="w-full rounded px-2 py-1 text-left hover:bg-surface-2"
                  class:bg-surface-2={vaultStore.selected?.entry.id === entry.id}
                  draggable={true}
                  data-testid="vault-panel-row"
                  data-vault-id={entry.id}
                  data-vault-kind={VAULT_KIND_TODO}
                  onclick={() => handleSelectEntry(entry.id)}
                  ondragstart={(event) => handleDragStartVaultRow(entry, event)}
                >
                  <span class="block truncate text-sm">{entryLabel(entry)}</span>
                  <span
                    class="flex items-baseline justify-between text-xs text-fg-muted"
                    data-testid="vault-panel-row-meta"
                  >
                    <span class="truncate">{parentDirName(entry.path)}</span>
                    <span class="ml-1 shrink-0">{formatRelativeTime(entry.mtime)}</span>
                  </span>
                </button>
              </li>
            {/each}
          </ul>
        </section>
      {/if}
    </div>
  </div>

  <div
    class="vault-panel__reader flex flex-1 flex-col"
    data-testid="vault-panel-reader"
    aria-label={VAULT_STRINGS.selectedReadingPanelLabel}
  >
    {#if vaultStore.selected === null}
      <p class="p-4 text-sm text-fg-muted" data-testid="vault-panel-reader-empty">
        {VAULT_STRINGS.selectedEmpty}
      </p>
    {:else}
      <header
        class="vault-panel__reader-header flex flex-col gap-2 border-b border-border p-3"
        data-testid="vault-panel-reader-header"
      >
        <h3 class="text-sm font-semibold text-fg-strong">
          {entryLabel(vaultStore.selected.entry)}
        </h3>
        <p class="font-mono text-xs text-fg-muted">{vaultStore.selected.entry.path}</p>
        {#if vaultStore.selected.body === "" && vaultStore.selected.entry.size > 0}
          <p class="text-xs italic text-red-400" data-testid="vault-panel-read-failed">
            {VAULT_STRINGS.selectedReadFailed}
          </p>
        {/if}
        {#if vaultStore.selected.truncated}
          <p class="text-xs italic text-yellow-400" data-testid="vault-panel-truncated">
            {VAULT_STRINGS.selectedTruncated}
          </p>
        {/if}
        <div class="flex flex-row flex-wrap gap-2 pt-1">
          <button
            type="button"
            class="rounded border border-border bg-surface-2 px-2 py-1 text-xs text-fg hover:bg-surface-1"
            data-testid="vault-panel-copy-link"
            onclick={() => handleCopyMarkdownLink(vaultStore.selected!.entry)}
          >
            {VAULT_STRINGS.copyMarkdownLink}
          </button>
          <button
            type="button"
            class="rounded border border-border bg-surface-2 px-2 py-1 text-xs text-fg hover:bg-surface-1"
            data-testid="vault-panel-copy-body"
            onclick={() => handleCopyBody(vaultStore.selected!)}
          >
            {VAULT_STRINGS.copyBody}
          </button>
          <button
            type="button"
            class="rounded border border-border bg-surface-2 px-2 py-1 text-xs text-fg hover:bg-surface-1 disabled:opacity-50"
            data-testid="vault-panel-paste-link"
            disabled={effectiveSessionId === null}
            title={effectiveSessionId === null ? VAULT_STRINGS.pasteToastNoActiveSession : undefined}
            onclick={() => handlePasteLinkIntoComposer(vaultStore.selected!.entry)}
          >
            {VAULT_STRINGS.pasteMarkdownLinkIntoComposer}
          </button>
          <button
            type="button"
            class="rounded border border-border bg-surface-2 px-2 py-1 text-xs text-fg hover:bg-surface-1 disabled:opacity-50"
            data-testid="vault-panel-paste-body"
            disabled={effectiveSessionId === null}
            title={effectiveSessionId === null ? VAULT_STRINGS.pasteToastNoActiveSession : undefined}
            onclick={() => handlePasteBodyIntoComposer(vaultStore.selected!)}
          >
            {VAULT_STRINGS.pasteBodyIntoComposer}
          </button>
          {#if activeSessionId !== null}
            <button
              type="button"
              class="rounded border border-border bg-surface-2 px-2 py-1 text-xs text-fg hover:bg-surface-1"
              class:border-accent={pinnedSessionId !== null}
              data-testid="vault-panel-open-against-session"
              onclick={handleOpenAgainstSession}
            >
              {VAULT_STRINGS.openAgainstSession}
            </button>
          {/if}
        </div>
        {#if pinnedSessionId !== null}
          <p class="text-xs text-fg-muted" data-testid="vault-panel-pinned-session">
            {VAULT_STRINGS.pinnedToSession}: {pinnedSessionId}
          </p>
        {/if}
        {#if vaultStore.selected.redactions.length > 0}
          <div
            class="flex flex-row flex-wrap gap-1 pt-2"
            data-testid="vault-panel-redaction-toggles"
          >
            {#each vaultStore.selected.redactions as redaction, idx (idx)}
              <button
                type="button"
                class="rounded border border-yellow-500/50 bg-yellow-500/10 px-2 py-0.5 text-xs text-fg"
                data-testid="vault-panel-redaction-toggle"
                data-redaction-index={idx}
                aria-label={VAULT_STRINGS.redactionAriaLabel}
                onclick={() => toggleRedaction(idx)}
              >
                {revealedRedactions.has(idx)
                  ? VAULT_STRINGS.redactionHide
                  : VAULT_STRINGS.redactionShow}
                <span class="ml-1 text-fg-muted">{redaction.pattern}</span>
              </button>
            {/each}
          </div>
        {/if}
      </header>

      <article
        class="vault-panel__reader-body prose prose-invert max-w-none flex-1 overflow-y-auto p-4"
        data-testid="vault-panel-reader-body"
      >
        <!-- eslint-disable-next-line svelte/no-at-html-tags -->
        {@html renderedHtml}
      </article>
    {/if}

    {#if toast !== null}
      <div
        class="vault-panel__toast border-t border-border bg-surface-2 p-2 text-xs text-fg"
        data-testid="vault-panel-toast"
        role="status"
      >
        {toast}
      </div>
    {/if}
  </div>
</section>

<style>
  .vault-panel {
    min-height: 0;
  }
</style>
