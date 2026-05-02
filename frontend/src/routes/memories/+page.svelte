<script lang="ts">
  /**
   * Memories page — per-tag editor over user-authored system-prompt
   * fragments (arch §1.1.3). Different from the vault: memories ARE
   * editable; vault is read-only.
   *
   * Reachable at ``/memories``. Renders into the center column of
   * the app shell when no session is selected.
   */
  import MemoriesEditor from "$lib/components/memories/MemoriesEditor.svelte";
</script>

<MemoriesEditor />
