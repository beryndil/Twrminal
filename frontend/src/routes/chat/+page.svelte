<script lang="ts">
  /**
   * ``/chat`` route — placeholder pending a dedicated chat landing.
   *
   * Individual sessions live at ``/sessions/<id>``; the new-session form
   * lives at ``/sessions/new``. This stub satisfies SvelteKit router
   * registration so direct navigation to ``/chat`` does not 404 in-app.
   */
</script>

<svelte:head>
  <title>Chat — Bearings</title>
</svelte:head>

<div
  class="flex h-full flex-col items-center justify-center gap-2 p-8 text-center"
  data-testid="chat-page"
>
  <h1 class="text-lg font-semibold text-fg-strong">Chat</h1>
  <p class="max-w-md text-sm text-fg-muted">
    Select a session from the sidebar, or press
    <kbd class="rounded border border-border bg-surface-2 px-1 font-mono text-xs">c</kbd>
    to start a new one.
  </p>
</div>
