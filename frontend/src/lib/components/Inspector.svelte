<script lang="ts">
  /**
   * Right-sidebar Inspector — Phase 3 of the v1.0.0 dashboard
   * redesign. Pre-Phase-3 this was one big component with two
   * `<details>` disclosures (Context + Agent). The redesign turned
   * the sidebar into a 4-tab surface (Context / Files / Changes /
   * Metrics); this file is now just the orchestrator that owns the
   * tab nav + active-tab persistence and renders the matching tab
   * component.
   *
   * Active tab is per-device sticky (`localStorage`). Defaults to
   * Context — the only tab that has live data today; Files/Changes/
   * Metrics ship as empty-state placeholders waiting on Phase 5–6
   * surfaces. The single source of truth for the choice is this
   * component's `activeTab` state; the nav reads it and writes back
   * via the `onSelect` callback. localStorage roundtrip happens here
   * on every change so a reload paints the same tab the user left.
   */
  import InspectorTabNav, {
    type InspectorTab,
  } from '$lib/components/inspector/InspectorTabNav.svelte';
  import ContextTab from '$lib/components/inspector/ContextTab.svelte';
  import FilesTab from '$lib/components/inspector/FilesTab.svelte';
  import ChangesTab from '$lib/components/inspector/ChangesTab.svelte';
  import MetricsTab from '$lib/components/inspector/MetricsTab.svelte';

  const STORAGE_KEY = 'bearings:inspector-tab';
  const VALID: readonly InspectorTab[] = ['context', 'files', 'changes', 'metrics'];

  function loadInitial(): InspectorTab {
    if (typeof localStorage === 'undefined') return 'context';
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw && (VALID as readonly string[]).includes(raw)) return raw as InspectorTab;
    } catch {
      // localStorage may be unavailable (private mode / quota); fall
      // back to the Context default.
    }
    return 'context';
  }

  let activeTab = $state<InspectorTab>(loadInitial());

  function selectTab(tab: InspectorTab) {
    activeTab = tab;
    try {
      localStorage.setItem(STORAGE_KEY, tab);
    } catch {
      // Persistence is best-effort; the tab still flips in-memory.
    }
  }
</script>

<aside class="flex h-full flex-col overflow-hidden border-l border-slate-800 bg-slate-900">
  <InspectorTabNav {activeTab} onSelect={selectTab} />
  <div class="flex-1 overflow-y-auto" data-testid="inspector-tab-content">
    <!--
      All four tabs stay mounted; inactive ones hide via the `hidden`
      attribute. This preserves transient state (Session Instructions
      draft, expanded system-prompt layers, scroll positions) across
      tab switches — silent data loss was the v1.0.0 audit's headline
      regression here.
    -->
    <div hidden={activeTab !== 'context'}>
      <ContextTab />
    </div>
    <div hidden={activeTab !== 'files'}>
      <FilesTab />
    </div>
    <div hidden={activeTab !== 'changes'}>
      <ChangesTab />
    </div>
    <div hidden={activeTab !== 'metrics'}>
      <MetricsTab />
    </div>
  </div>
</aside>
