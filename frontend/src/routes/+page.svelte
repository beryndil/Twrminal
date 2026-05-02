<script lang="ts">
  /**
   * Default landing route — renders inside the app shell's center
   * column (`+layout.svelte` →  `<section class="app-shell__main-body">`)
   * when no session row is selected.
   *
   * Clicking a sidebar row navigates to ``/sessions/<id>``; that
   * route's ``+page.svelte`` syncs the inspector store and the layout
   * swaps in the conversation pane. This page renders only the empty
   * state — sidebar selection, settings, memories, and vault each own
   * their own routes.
   */
</script>

<div class="flex h-full flex-col items-center justify-center gap-2 text-center">
  <h2 class="text-lg font-medium text-fg-strong">No session open</h2>
  <p class="max-w-md text-sm text-fg-muted">
    Pick a session from the sidebar, or start a new one with <kbd
      class="rounded border border-border bg-surface-2 px-1 font-mono text-xs">c</kbd
    >.
  </p>
</div>
