<script lang="ts">
  /**
   * Tag-edit modal — opened by the ``tag.edit`` context-menu action on
   * a tag chip in the sidebar filter panel.
   *
   * Exposes:
   *
   * - A class selector (project / severity / general).
   * - A ``default_model`` text field — disabled and cleared when
   *   ``severity`` is selected, because the backend returns 422 on
   *   non-null inheritance for severity rows.
   * - A ``working_dir`` text field — same severity constraint.
   *
   * On successful PATCH the ``onSaved`` callback fires with the updated
   * :class:`TagOut` so callers can refresh their tag chip surfaces
   * without a global refetch. Backend 422 errors are surfaced inline
   * beneath the form.
   *
   * Behavior anchor: ``docs/behavior/context-menus.md`` §Tag —
   * ``tag.edit`` action.
   */
  import { untrack } from "svelte";
  import { ApiError } from "../../api/client";
  import {
    TAG_CLASS_SEVERITY,
    type TagClass,
    type TagOut,
    updateTag,
  } from "../../api/tags";
  import {
    EXECUTOR_MODEL_HAIKU,
    EXECUTOR_MODEL_OPUS,
    EXECUTOR_MODEL_SONNET,
    NEW_SESSION_STRINGS,
    TAG_EDIT_STRINGS,
  } from "../../config";

  interface Props {
    tag: TagOut;
    onClose: () => void;
    onSaved: (updated: TagOut) => void;
  }

  const { tag, onClose, onSaved }: Props = $props();

  // Local edit state — seeded from the received tag prop at mount time.
  // ``untrack()`` is the Svelte 5 idiom for reading a reactive value
  // once without creating a reactive dependency — the modal's lifetime
  // is tied to the tag row it was opened for, so re-seeding on prop
  // change is explicitly not desired (the parent closes and re-mounts
  // for a different tag).  Pattern mirrors SessionTagPicker.svelte.
  let editClass = $state<TagClass>(untrack(() => tag.class_));
  let editModel = $state(untrack(() => tag.default_model ?? ""));
  let editWd = $state(untrack(() => tag.working_dir ?? ""));
  let errorMsg = $state<string | null>(null);
  let saving = $state(false);

  // Mirror the /tags page constraint: severity rejects inheritance at
  // the backend boundary — clear + disable the fields proactively so
  // the user never hits a 422 for a predictable reason.
  $effect(() => {
    if (editClass === TAG_CLASS_SEVERITY) {
      editModel = "";
      editWd = "";
    }
  });

  const isSeverity = $derived(editClass === TAG_CLASS_SEVERITY);

  /** Human-readable label for a known executor model wire name. */
  function modelLabel(wire: string): string {
    const known = [EXECUTOR_MODEL_SONNET, EXECUTOR_MODEL_HAIKU, EXECUTOR_MODEL_OPUS] as const;
    for (const k of known) {
      if (k === wire) {
        return NEW_SESSION_STRINGS.executorLabels[k];
      }
    }
    return wire;
  }

  async function handleSubmit(): Promise<void> {
    saving = true;
    errorMsg = null;
    try {
      const updated = await updateTag(tag.id, {
        name: tag.name,
        color: tag.color,
        class_: editClass,
        default_model: editModel.trim() === "" ? null : editModel.trim(),
        working_dir: editWd.trim() === "" ? null : editWd.trim(),
        sort_order: tag.sort_order,
      });
      onSaved(updated);
      onClose();
    } catch (err) {
      if (err instanceof ApiError) {
        const detail = (err.body as { detail?: unknown } | null)?.detail;
        errorMsg = typeof detail === "string" ? detail : err.message;
      } else {
        errorMsg = err instanceof Error ? err.message : String(err);
      }
    } finally {
      saving = false;
    }
  }

  function handleBackdropKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
    }
  }
</script>

<!-- Backdrop -->
<div
  class="tag-edit-backdrop fixed inset-0 z-50 flex items-center justify-center bg-black/50"
  role="presentation"
  data-testid="tag-edit-backdrop"
  onclick={onClose}
  onkeydown={handleBackdropKeyDown}
>
  <!-- Panel -->
  <div
    class="tag-edit-panel w-full max-w-sm rounded-lg bg-surface-1 shadow-xl"
    role="dialog"
    aria-modal="true"
    aria-label={TAG_EDIT_STRINGS.dialogAriaLabel}
    data-testid="tag-edit-dialog"
    tabindex="-1"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
  >
    <!-- Header -->
    <div class="border-b border-border px-4 py-3">
      <h2 class="text-sm font-semibold text-fg-strong" data-testid="tag-edit-title">
        {TAG_EDIT_STRINGS.title}: <span class="font-normal text-fg-muted">{tag.name}</span>
      </h2>
    </div>

    <!-- Body -->
    <form
      class="flex flex-col gap-3 px-4 py-3"
      onsubmit={(e) => {
        e.preventDefault();
        void handleSubmit();
      }}
      data-testid="tag-edit-form"
    >
      <!-- Class selector -->
      <label class="flex flex-col gap-1">
        <span class="text-xs font-medium text-fg-muted">{TAG_EDIT_STRINGS.classLabel}</span>
        <select
          class="rounded border border-border bg-surface-2 px-2 py-1.5 text-sm text-fg-strong"
          bind:value={editClass}
          data-testid="tag-edit-class"
        >
          <option value="project">{TAG_EDIT_STRINGS.classOptions.project}</option>
          <option value="severity">{TAG_EDIT_STRINGS.classOptions.severity}</option>
          <option value="general">{TAG_EDIT_STRINGS.classOptions.general}</option>
        </select>
      </label>

      <!-- Default model — text field with datalist for known models -->
      <label class="flex flex-col gap-1" class:opacity-50={isSeverity}>
        <span class="text-xs font-medium text-fg-muted">{TAG_EDIT_STRINGS.defaultModelLabel}</span>
        <input
          list="tag-edit-model-list"
          type="text"
          class="rounded border border-border bg-surface-2 px-2 py-1.5 text-sm text-fg-strong
                 disabled:cursor-not-allowed"
          placeholder={TAG_EDIT_STRINGS.defaultModelPlaceholder}
          disabled={isSeverity}
          bind:value={editModel}
          data-testid="tag-edit-model"
        />
        <datalist id="tag-edit-model-list">
          <option value={EXECUTOR_MODEL_SONNET}>{modelLabel(EXECUTOR_MODEL_SONNET)}</option>
          <option value={EXECUTOR_MODEL_HAIKU}>{modelLabel(EXECUTOR_MODEL_HAIKU)}</option>
          <option value={EXECUTOR_MODEL_OPUS}>{modelLabel(EXECUTOR_MODEL_OPUS)}</option>
        </datalist>
        {#if isSeverity}
          <span class="text-xs text-fg-muted" data-testid="tag-edit-severity-hint">
            {TAG_EDIT_STRINGS.severityInheritanceHint}
          </span>
        {/if}
      </label>

      <!-- Working dir -->
      <label class="flex flex-col gap-1" class:opacity-50={isSeverity}>
        <span class="text-xs font-medium text-fg-muted">{TAG_EDIT_STRINGS.workingDirLabel}</span>
        <input
          type="text"
          class="rounded border border-border bg-surface-2 px-2 py-1.5 text-sm text-fg-strong
                 disabled:cursor-not-allowed"
          placeholder={TAG_EDIT_STRINGS.workingDirPlaceholder}
          disabled={isSeverity}
          bind:value={editWd}
          data-testid="tag-edit-wd"
        />
      </label>

      <!-- Inline error -->
      {#if errorMsg !== null}
        <p class="text-xs text-red-400" role="alert" data-testid="tag-edit-error">{errorMsg}</p>
      {/if}

      <!-- Footer actions -->
      <div class="flex justify-end gap-2 border-t border-border pt-3">
        <button
          type="button"
          class="rounded border border-border bg-surface-2 px-4 py-1.5 text-sm font-medium
                 text-fg-strong hover:bg-surface-1 disabled:opacity-50"
          disabled={saving}
          data-testid="tag-edit-cancel"
          onclick={onClose}
        >
          {TAG_EDIT_STRINGS.cancelLabel}
        </button>
        <button
          type="submit"
          class="rounded bg-accent px-4 py-1.5 text-sm font-medium text-white
                 hover:bg-accent/90 disabled:opacity-50"
          disabled={saving}
          data-testid="tag-edit-save"
        >
          {saving ? TAG_EDIT_STRINGS.savingLabel : TAG_EDIT_STRINGS.saveLabel}
        </button>
      </div>
    </form>
  </div>
</div>
