<script lang="ts">
  /**
   * ``/sessions/[id]`` route — sole responsibility is to sync the
   * inspector store's ``activeSessionId`` with the URL parameter so the
   * existing layout chrome (sidebar selection highlight, conversation
   * pane, inspector pane) renders against the right row.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/chat.md`` §"opens an existing chat" — selecting a
   *   sidebar row reconnects the conversation pane. With this route in
   *   place the same selection survives reload + browser back/forward
   *   (sign-off decision 2026-05-01: SvelteKit client-nav, no chrome
   *   flash).
   * - The route file renders nothing of its own; the layout owns the
   *   visible chrome and the conversation+composer surfaces. Rendering
   *   nothing here keeps the active-row read off the URL while leaving
   *   the layout free to render whatever it wants in the empty
   *   children slot when no row is selected.
   */
  import { page } from "$app/state";

  import { setActiveSession } from "$lib/stores/inspector.svelte";

  // The route param is reactively read from `$app/state.page`. Whenever
  // SvelteKit pushes a new id (sidebar-anchor click, browser
  // back/forward, direct URL load) the effect re-fires and the
  // inspector store re-syncs. ``page.params.id`` is always defined on
  // this route — SvelteKit guarantees it from the file path.
  $effect(() => {
    setActiveSession(page.params.id ?? null);
  });
</script>
