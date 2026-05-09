<script lang="ts">
  /**
   * ``/paired`` route — informational stub for the paired-chats feature.
   *
   * Paired chats (see ``docs/behavior/paired-chats.md``) are chat sessions
   * linked 1:1 to a checklist leaf item. The pairing affordance lives on
   * the checklist item row and the chat conversation header — not on a
   * standalone list page. This stub satisfies SvelteKit router
   * registration so direct navigation to ``/paired`` does not 404 in-app.
   */
</script>

<svelte:head>
  <title>Paired Chats — Bearings</title>
</svelte:head>

<div
  class="flex h-full flex-col items-center justify-center gap-2 p-8 text-center"
  data-testid="paired-page"
>
  <h1 class="text-lg font-semibold text-fg-strong">Paired Chats</h1>
  <p class="max-w-md text-sm text-fg-muted">
    A paired chat is a 1:1 link between a checklist leaf item and a chat session. Open a checklist
    and press <strong>💬 Work on this</strong> on any leaf item to spawn or continue its paired chat.
  </p>
</div>
