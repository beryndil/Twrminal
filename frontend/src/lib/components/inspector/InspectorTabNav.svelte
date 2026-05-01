<script lang="ts">
  /**
   * Inspector tab nav — Phase 3 of the v1.0.0 dashboard redesign.
   * Top strip of the right sidebar with four tabs:
   *
   *   Context · Files · Changes · Metrics
   *
   * Tab choice is per-device sticky (localStorage), defaulting to
   * Context — the one tab that actually has content today. Files /
   * Changes / Metrics ship as empty-state placeholders waiting on
   * their respective backing surfaces (Phases 5–6).
   *
   * Single source of truth for the active tab is the `activeTab`
   * binding the parent owns; this component renders the visual rail
   * and bumps the binding on click. Both directions of the bind keep
   * the localStorage persistence honest — the parent reads from
   * storage on mount, writes back on every change.
   */
  export type InspectorTab = 'context' | 'files' | 'changes' | 'metrics';

  interface Props {
    activeTab: InspectorTab;
    onSelect: (tab: InspectorTab) => void;
  }

  const { activeTab, onSelect }: Props = $props();

  const TABS: { id: InspectorTab; label: string }[] = [
    { id: 'context', label: 'Context' },
    { id: 'files', label: 'Files' },
    { id: 'changes', label: 'Changes' },
    { id: 'metrics', label: 'Metrics' },
  ];
</script>

<div
  class="flex shrink-0 items-center gap-1 border-b border-slate-800 px-1 pb-0"
  aria-label="Inspector tabs"
  data-testid="inspector-tab-nav"
  role="tablist"
>
  {#each TABS as tab (tab.id)}
    <button
      type="button"
      role="tab"
      aria-selected={activeTab === tab.id}
      data-testid="inspector-tab-{tab.id}"
      class="border-b-2 px-3 py-2 text-xs font-medium uppercase tracking-wider
        transition-colors focus:outline-none focus:ring-2 focus:ring-sky-500
        {activeTab === tab.id
        ? 'border-accent-brand text-accent-brand'
        : 'border-transparent text-slate-500 hover:text-slate-300'}"
      onclick={() => onSelect(tab.id)}
    >
      {tab.label}
    </button>
  {/each}
</div>
