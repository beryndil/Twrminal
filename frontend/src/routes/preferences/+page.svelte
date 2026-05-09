<script lang="ts">
  /**
   * ``/preferences`` route — canonical alias for ``/settings``.
   *
   * The preferences subsystem is exposed at ``/settings`` (see
   * ``docs/behavior/preferences.md`` and
   * ``frontend/src/routes/settings/+page.svelte``). This route performs
   * a client-side replace-redirect so any deep-link or external
   * navigation to ``/preferences`` lands on the correct settings shell
   * without polluting the browser history stack.
   */
  import { goto } from "$app/navigation";
  import { onMount } from "svelte";

  onMount(() => {
    void goto("/settings", { replaceState: true });
  });
</script>
