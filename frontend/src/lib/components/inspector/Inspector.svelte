<script lang="ts">
  /**
   * Inspector shell — right-column container with a tab strip that
   * switches between subsection components.
   *
   * Behavior anchors:
   *
   * - ``docs/architecture-v1.md`` §1.2 lists the canonical inspector
   *   decomposition: ``Inspector.svelte`` shell + per-subsection
   *   components (`InspectorAgent`, `InspectorContext`,
   *   `InspectorInstructions`, plus the routing/usage pair that lands
   *   in item 2.6).
   * - ``docs/behavior/chat.md`` §"opens an existing chat" lists the
   *   inspector as one of the three top-level panes; §"What the user
   *   does NOT see in chat" enumerates the Routing + Usage subsections
   *   item 2.6 will plug in here.
   *
   * Item 2.5 shipped the shell + the first three subsections. Item 2.6
   * lit up Routing + Usage by:
   *
   * 1. Extending :data:`KNOWN_INSPECTOR_TABS` in ``config.ts``;
   * 2. Adding :class:`InspectorRouting` + :class:`InspectorUsage` in
   *    ``components/inspector/``;
   * 3. Appending two cases to the body switch below.
   *
   * The shell has no per-tab logic outside the body switch — the tab
   * strip itself iterates :data:`KNOWN_INSPECTOR_TABS` so each new tab
   * appears the moment the constants tuple grows.
   *
   * The store-prop seam mirrors :class:`SessionList` — production
   * callers pass nothing, tests inject a fake ``inspectorStore`` /
   * ``setInspectorTab`` pair so each test owns its state without
   * monkey-patching the module cache.
   */
  import {
    INSPECTOR_STRINGS,
    INSPECTOR_TAB_AGENT,
    INSPECTOR_TAB_CHANGES,
    INSPECTOR_TAB_CONTEXT,
    INSPECTOR_TAB_FILES,
    INSPECTOR_TAB_INSTRUCTIONS,
    INSPECTOR_TAB_METRICS,
    INSPECTOR_TAB_ROUTING,
    INSPECTOR_TAB_USAGE,
    KNOWN_INSPECTOR_TABS,
    type InspectorTabId,
  } from "../../config";
  import type { SessionOut } from "../../api/sessions";
  import { listMessages } from "../../api/messages";
  import { getQuotaHistory } from "../../api/quota";
  import { getOverrideRates, getUsageByModel } from "../../api/usage";
  import {
    inspectorStore as inspectorStoreDefault,
    setInspectorTab as setInspectorTabDefault,
  } from "../../stores/inspector.svelte";
  import InspectorAgent from "./InspectorAgent.svelte";
  import InspectorChanges from "./InspectorChanges.svelte";
  import InspectorContext from "./InspectorContext.svelte";
  import InspectorFiles from "./InspectorFiles.svelte";
  import InspectorInstructions from "./InspectorInstructions.svelte";
  import InspectorMetrics from "./InspectorMetrics.svelte";
  import InspectorRouting from "./InspectorRouting.svelte";
  import InspectorUsage from "./InspectorUsage.svelte";

  interface Props {
    /**
     * Active session row. ``null`` when no session is selected (boot,
     * tag filter empties the list, etc.); ``undefined`` when the
     * sidebar has a selection but the row is not in the cached list
     * yet (transient — the empty-state copy renders until the row
     * loads).
     */
    session?: SessionOut | null;
    /**
     * Test-injectable fakes. Production callers pass nothing and pick
     * up the module-singleton store + helper.
     */
    inspectorStore?: typeof inspectorStoreDefault;
    setInspectorTab?: typeof setInspectorTabDefault;
    /**
     * Test seams — passed through to :class:`InspectorRouting`.
     * Production callers omit; the subsection falls through to its own
     * default (the typed API client).
     */
    fetchMessages?: typeof listMessages;
    /**
     * Test seams — passed through to :class:`InspectorUsage`.
     * Production callers omit; the subsection falls through to its own
     * defaults.
     */
    fetchHistory?: typeof getQuotaHistory;
    fetchByModel?: typeof getUsageByModel;
    fetchOverrideRates?: typeof getOverrideRates;
  }

  const {
    session = null,
    inspectorStore = inspectorStoreDefault,
    setInspectorTab = setInspectorTabDefault,
    fetchMessages,
    fetchHistory,
    fetchByModel,
    fetchOverrideRates,
  }: Props = $props();

  const activeTabId = $derived(inspectorStore.activeTabId);

  function handleTabClick(id: InspectorTabId): void {
    setInspectorTab(id);
  }
</script>

<div class="inspector flex h-full flex-col" data-testid="inspector">
  <div
    class="inspector__tabs flex flex-row gap-1 border-b border-border bg-surface-1 px-2 py-1"
    aria-label={INSPECTOR_STRINGS.tabStripAriaLabel}
    data-testid="inspector-tabs"
    role="tablist"
  >
    {#each KNOWN_INSPECTOR_TABS as tabId (tabId)}
      <button
        type="button"
        class="inspector__tab rounded px-2 py-1 text-xs font-medium"
        class:inspector__tab--active={activeTabId === tabId}
        data-testid="inspector-tab"
        data-tab-id={tabId}
        role="tab"
        aria-selected={activeTabId === tabId}
        onclick={() => handleTabClick(tabId)}
      >
        {INSPECTOR_STRINGS.tabLabels[tabId]}
      </button>
    {/each}
  </div>

  <div
    class="inspector__body flex-1 overflow-y-auto p-3 text-sm"
    data-testid="inspector-body"
    role="tabpanel"
    aria-labelledby={`inspector-tab-${activeTabId}`}
  >
    {#if session === null || session === undefined}
      <p class="text-fg-muted" data-testid="inspector-empty">
        {INSPECTOR_STRINGS.emptySession}
      </p>
    {:else}
      <!--
        All eight tabs stay mounted; inactive ones hide via the `hidden`
        attribute. This preserves transient state (expandedReasons set,
        scroll positions, already-loaded fetch data) across tab switches —
        silent data loss was the cycle-09 audit's headline regression here.
        Screen-readers skip hidden subtrees, so only the active tab is
        announced.
      -->
      <div hidden={activeTabId !== INSPECTOR_TAB_AGENT}>
        <InspectorAgent {session} />
      </div>
      <div hidden={activeTabId !== INSPECTOR_TAB_CONTEXT}>
        <InspectorContext {session} />
      </div>
      <div hidden={activeTabId !== INSPECTOR_TAB_INSTRUCTIONS}>
        <InspectorInstructions {session} />
      </div>
      <div hidden={activeTabId !== INSPECTOR_TAB_FILES}>
        <InspectorFiles {session} />
      </div>
      <div hidden={activeTabId !== INSPECTOR_TAB_CHANGES}>
        <InspectorChanges {session} />
      </div>
      <div hidden={activeTabId !== INSPECTOR_TAB_METRICS}>
        <InspectorMetrics {session} />
      </div>
      <div hidden={activeTabId !== INSPECTOR_TAB_ROUTING}>
        <InspectorRouting {session} {fetchMessages} />
      </div>
      <div hidden={activeTabId !== INSPECTOR_TAB_USAGE}>
        <InspectorUsage {session} {fetchHistory} {fetchByModel} {fetchOverrideRates} />
      </div>
    {/if}
  </div>
</div>

<style>
  /*
   * Active-tab accent uses theme tokens so item 2.9's theme provider
   * picks the right colour without re-painting this stylesheet. The
   * non-active state is intentionally bare — the tab strip is dense
   * and a heavy default would compete with the sidebar's group
   * headings for visual weight.
   */
  .inspector__tab {
    color: var(--bearings-fg-muted, currentColor);
    background-color: transparent;
  }

  .inspector__tab:hover {
    background-color: var(--bearings-surface-2, rgba(255, 255, 255, 0.04));
  }

  .inspector__tab--active {
    color: rgb(var(--bearings-accent));
    background-color: transparent;
    box-shadow: inset 0 -2px 0 rgb(var(--bearings-accent));
  }
</style>
