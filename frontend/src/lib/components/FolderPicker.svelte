<script lang="ts">
  import { pickDirectory } from '$lib/api/fs';

  let {
    value = $bindable(''),
    placeholder = 'click to choose…'
  }: { value?: string; placeholder?: string } = $props();

  let picking = $state(false);
  let error = $state<string | null>(null);

  /** Pop the host's native directory picker via the backend bridge.
   * Bearings is localhost/single-user, so deferring to the user's own
   * zenity/kdialog instance is both the cheapest implementation and
   * the most familiar UX. The prior in-browser walker still exists in
   * git history if we ever need a headless fallback. */
  async function openPicker() {
    if (picking) return;
    picking = true;
    error = null;
    try {
      const result = await pickDirectory({
        start: value.trim() || null,
        title: 'Select working directory'
      });
      if (result.cancelled) return;
      if (result.path) value = result.path;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      picking = false;
    }
  }
</script>

<div class="flex flex-col gap-1">
  <button
    type="button"
    class="w-full text-left rounded bg-slate-950 border border-slate-800 hover:border-slate-600
      px-2 py-2 text-sm font-mono truncate disabled:opacity-60"
    class:text-slate-200={value}
    class:text-slate-500={!value}
    onclick={openPicker}
    disabled={picking}
    aria-label="Folder path"
    title={value || placeholder}
  >
    {picking ? 'Picking…' : value || placeholder}
  </button>
  {#if error}
    <p class="text-xs text-rose-400" data-testid="folder-picker-error">{error}</p>
  {/if}
</div>
