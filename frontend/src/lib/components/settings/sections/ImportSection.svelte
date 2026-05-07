<script lang="ts">
  /**
   * Data import section — copies sessions / messages / tags from Bearings v0.17.x.
   * Extracted from ``+page.svelte`` as part of gap-cycle-07-007.
   */
  import type { SaveStatus } from "../sections.js";
  import { importFromBearings, type ImportResultOut } from "$lib/api/import";

  interface Props {
    onsaveStatus?: (status: SaveStatus) => void;
  }

  // Import shows its own inline status rather than the shared footer.
  const { onsaveStatus: _onsaveStatus }: Props = $props();

  let importing = $state(false);
  let importResult = $state<ImportResultOut | null>(null);
  let importError = $state<string | null>(null);

  async function runImport(): Promise<void> {
    importing = true;
    importError = null;
    importResult = null;
    try {
      const result = await importFromBearings();
      importResult = result;
      if (result.errors.length > 0) {
        importError = result.errors.join("; ");
      }
    } catch (err) {
      importError = err instanceof Error ? err.message : String(err);
    } finally {
      importing = false;
    }
  }
</script>

<section class="settings-page__group" aria-label="Data import">
  <h2 class="settings-page__heading">Import from Bearings</h2>
  <p class="settings-page__lede">
    Copy all sessions, messages, and tags from the main Bearings database into this instance.
    Existing records are preserved — duplicates are skipped.
  </p>
  <div class="settings-import__actions">
    <button
      class="settings-defaults__save"
      onclick={runImport}
      disabled={importing}
      data-testid="import-button"
    >
      {importing ? "Importing…" : "Import now"}
    </button>
    {#if importResult}
      <span class="settings-import__result" role="status" data-testid="import-result">
        {importResult.sessions_imported} sessions, {importResult.messages_imported} messages,
        {importResult.tags_imported} tags imported.
        {#if importResult.sessions_skipped > 0}({importResult.sessions_skipped} skipped){/if}
      </span>
    {/if}
    {#if importError}
      <span class="settings-page__error" role="alert" data-testid="import-error">
        {importError}
      </span>
    {/if}
  </div>
</section>

<style>
  .settings-import__actions {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-top: 0.25rem;
  }
  .settings-import__result {
    font-size: 0.8125rem;
    color: #4ade80;
  }
</style>
