<script lang="ts">
  /**
   * Memories page — global index + per-tag editor over user-authored
   * system-prompt fragments (arch §1.1.3; gap-cycle-13-007).
   * Different from the vault: memories ARE editable; vault is read-only.
   *
   * Reachable at ``/memories``. Default view is the global flat list
   * (``MemoriesIndex``). Clicking a row in the index switches into the
   * per-tag editor (``MemoriesEditor``) with the selected memory
   * pre-opened for editing. A "← All memories" back button returns to
   * the index.
   */
  import type { AllMemoriesRow } from "$lib/api/memories";
  import MemoriesEditor from "$lib/components/memories/MemoriesEditor.svelte";
  import MemoriesIndex from "$lib/components/memories/MemoriesIndex.svelte";

  const BACK_LABEL = "All memories";

  type View = "index" | "editor";

  let view = $state<View>("index");
  let editorTagId = $state<number | null>(null);
  let editorMemoryId = $state<number | null>(null);

  function openEditor(row: AllMemoriesRow): void {
    editorTagId = row.tag_id;
    editorMemoryId = row.memory_id;
    view = "editor";
  }

  function backToIndex(): void {
    view = "index";
    editorTagId = null;
    editorMemoryId = null;
  }
</script>

{#if view === "index"}
  <MemoriesIndex onRowClick={openEditor} />
{:else}
  <div class="memories-page__editor-shell flex h-full flex-col" data-testid="memories-editor-shell">
    <div class="memories-page__back border-b border-border px-3 py-1">
      <button
        type="button"
        class="text-xs text-fg-muted hover:text-fg"
        data-testid="memories-back-button"
        onclick={backToIndex}
      >
        ← {BACK_LABEL}
      </button>
    </div>
    <div class="flex-1 overflow-hidden">
      <MemoriesEditor initialTagId={editorTagId} initialMemoryId={editorMemoryId} />
    </div>
  </div>
{/if}
