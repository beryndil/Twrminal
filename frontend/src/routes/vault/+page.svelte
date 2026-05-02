<script lang="ts">
  /**
   * Vault page — read-only browser over plans + TODO.md files
   * (``docs/behavior/vault.md``).
   *
   * Reachable at ``/vault``. Renders into the center column of the
   * app shell (``+layout.svelte``'s ``children`` slot) when no
   * session is selected. The pane reads the active session id off
   * the inspector store so the paste-into-composer affordances
   * target the right chat (vault.md §"Tag association" — "Open
   * against this session").
   */
  import VaultPanel from "$lib/components/vault/VaultPanel.svelte";
  import { inspectorStore } from "$lib/stores/inspector.svelte";
</script>

<VaultPanel activeSessionId={inspectorStore.activeSessionId} />
