<script lang="ts">
  /**
   * Big "+ New Session" pill — Phase 2c of the v1.0.0 dashboard
   * redesign. Replaces the small `+ New` toolbar button that lived
   * in `SessionListHeader.svelte`. The mockup gave this a much
   * larger visual weight — full-width emerald pill, sitting just
   * under the brand block — because creating a new session is the
   * primary action in the sidebar; the rest of the surface is
   * navigation and browsing.
   *
   * State stays in the existing `uiActions` store
   * (`newSessionOpen`); the actual NewSessionForm modal still lives
   * where it always has, this is just the affordance that toggles it.
   */
  import { uiActions } from '$lib/stores/ui_actions.svelte';
</script>

<button
  type="button"
  class="flex w-full items-center justify-center gap-2 rounded-md bg-accent-brand
    px-3 py-2 text-sm font-medium text-white shadow-sm transition-colors
    hover:bg-accent-brand/90 focus:outline-none focus:ring-2 focus:ring-accent-brand/70"
  onclick={() => uiActions.toggleNewSession()}
  data-testid="new-session-pill"
  aria-label={uiActions.newSessionOpen ? 'Cancel new session' : 'Start a new session'}
>
  <span aria-hidden="true">{uiActions.newSessionOpen ? '×' : '+'}</span>
  <span>{uiActions.newSessionOpen ? 'Cancel' : 'New Session'}</span>
</button>
