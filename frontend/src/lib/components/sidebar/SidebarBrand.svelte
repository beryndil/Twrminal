<script lang="ts">
  /**
   * Sidebar brand block — Phase 2c of the v1.0.0 dashboard redesign.
   *
   * Top-of-sidebar identity: the permanent BearingsMark (compass-rings
   * design — the project IS named "Bearings", the compass is the
   * identity) sat alongside the wordmark. Tinted to the evergreen
   * brand emerald so the brand reads as forest-green over the deep
   * blue-black sidebar surface; under other themes the inherited
   * `currentColor` falls back to that theme's brand hue (sky/violet
   * for midnight-glass, sky for default, etc.) so the same component
   * is theme-correct everywhere.
   *
   * Pure presentation — no state, no event handlers. SessionList
   * mounts this once at the top.
   */
  import BearingsMark from '$lib/components/icons/BearingsMark.svelte';
</script>

<div class="flex items-center gap-2 px-2 py-2 text-accent-brand" data-testid="sidebar-brand">
  <BearingsMark size={22} />
  <span class="text-base font-semibold tracking-tight">Bearings</span>
</div>
