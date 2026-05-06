<script lang="ts">
  /**
   * Template Picker dropdown — opened by the ``t`` chord per
   * ``docs/behavior/keyboard-shortcuts.md`` §"Create".
   *
   * Behavior:
   *
   * - Fetches the saved template list on open (newest-first via the
   *   :func:`refreshTemplates` store helper).
   * - Each row shows the template name + an × delete affordance.
   * - Clicking a row calls :func:`instantiate`, navigates to the new
   *   session, and closes the picker.
   * - The × button shows a per-row confirmation inline; confirming calls
   *   :func:`removeTemplate` and refreshes the list without closing
   *   the picker.
   * - Any error from :func:`instantiate` is displayed inline below the
   *   list rather than blocking the picker.
   * - ``Esc`` closes the picker via the Esc cascade.
   */
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";

  import { TEMPLATE_PICKER_STRINGS } from "../../config";
  import { ESC_PRIORITY_OVERLAY, registerEscEntry } from "../../keyboard/escCascade";
  import {
    instantiate,
    refreshTemplates,
    removeTemplate,
    templatesStore,
  } from "../../stores/templates.svelte";

  interface Props {
    /** Open / closed flag driven by :class:`KeybindingsProvider`. */
    open: boolean;
    /** Close callback — invoked from the cascade + the close button. */
    onClose: () => void;
  }

  const { open, onClose }: Props = $props();

  // ---- inline instantiation error -----------------------------------------

  let instantiateError = $state<string | null>(null);

  // ---- per-row delete confirm state ----------------------------------------

  let confirmDeleteId = $state<number | null>(null);
  let deleteError = $state<string | null>(null);

  // ---- fetch on open -------------------------------------------------------

  $effect(() => {
    if (open) {
      instantiateError = null;
      deleteError = null;
      confirmDeleteId = null;
      void refreshTemplates();
    }
  });

  // ---- Esc cascade ---------------------------------------------------------

  onMount(() => {
    return registerEscEntry({
      priority: ESC_PRIORITY_OVERLAY,
      isOpen: () => open,
      close: onClose,
    });
  });

  // ---- instantiate ---------------------------------------------------------

  async function handleInstantiate(templateId: number): Promise<void> {
    instantiateError = null;
    try {
      const sessionId = await instantiate(templateId);
      onClose();
      await goto(`/sessions/${encodeURIComponent(sessionId)}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      instantiateError = `${TEMPLATE_PICKER_STRINGS.instantiateErrorPrefix} ${msg}`;
    }
  }

  // ---- delete confirm flow -------------------------------------------------

  function requestDelete(templateId: number): void {
    // Stop the click from bubbling up to the row's instantiate handler.
    confirmDeleteId = templateId;
    deleteError = null;
  }

  async function handleDeleteConfirm(): Promise<void> {
    const id = confirmDeleteId;
    confirmDeleteId = null;
    if (id === null) return;
    deleteError = null;
    try {
      await removeTemplate(id);
    } catch (err) {
      deleteError = err instanceof Error ? err.message : String(err);
    }
  }

  function handleDeleteCancel(): void {
    confirmDeleteId = null;
    deleteError = null;
  }

  // ---- keyboard trap inside the panel -------------------------------------

  function handlePanelKeyDown(event: KeyboardEvent): void {
    // Stop Esc from escaping the cascade — the cascade entry handles it.
    event.stopPropagation();
  }
</script>

{#if open}
  <!-- Backdrop — click outside closes the picker. -->
  <div
    class="tp-backdrop"
    role="presentation"
    data-testid="template-picker-backdrop"
    onclick={onClose}
    onkeydown={(e) => {
      if (e.key === "Escape") onClose();
    }}
  >
    <div
      class="tp-panel"
      role="dialog"
      tabindex="-1"
      aria-label={TEMPLATE_PICKER_STRINGS.ariaLabel}
      data-testid="template-picker"
      onclick={(e) => e.stopPropagation()}
      onkeydown={handlePanelKeyDown}
    >
      <!-- Header -->
      <div class="tp-header">
        <span class="tp-heading" data-testid="template-picker-heading">
          {TEMPLATE_PICKER_STRINGS.heading}
        </span>
        <button
          type="button"
          class="tp-close"
          aria-label={TEMPLATE_PICKER_STRINGS.closeLabel}
          data-testid="template-picker-close"
          onclick={onClose}
        >
          ×
        </button>
      </div>

      <!-- Template list -->
      <div class="tp-body">
        {#if templatesStore.loading}
          <p class="tp-status" data-testid="template-picker-loading">
            {TEMPLATE_PICKER_STRINGS.loadingLabel}
          </p>
        {:else if templatesStore.error !== null}
          <p class="tp-status tp-status--error" data-testid="template-picker-load-error">
            {TEMPLATE_PICKER_STRINGS.loadErrorLabel}
          </p>
        {:else if templatesStore.templates.length === 0}
          <p class="tp-status" data-testid="template-picker-empty">
            {TEMPLATE_PICKER_STRINGS.emptyLabel}
          </p>
        {:else}
          <ul class="tp-list" role="listbox" data-testid="template-picker-list">
            {#each templatesStore.templates as template (template.id)}
              {#if confirmDeleteId === template.id}
                <!-- Per-row inline confirm -->
                <li class="tp-row tp-row--confirm" data-testid="template-picker-confirm-row">
                  <span class="tp-confirm-msg" data-testid="template-picker-confirm-msg">
                    {TEMPLATE_PICKER_STRINGS.deleteConfirmMessage(template.name)}
                  </span>
                  <div class="tp-confirm-actions">
                    <button
                      type="button"
                      class="tp-btn tp-btn--cancel"
                      data-testid="template-picker-delete-cancel"
                      onclick={handleDeleteCancel}
                    >
                      {TEMPLATE_PICKER_STRINGS.deleteCancelLabel}
                    </button>
                    <button
                      type="button"
                      class="tp-btn tp-btn--danger"
                      data-testid="template-picker-delete-confirm"
                      onclick={() => void handleDeleteConfirm()}
                    >
                      {TEMPLATE_PICKER_STRINGS.deleteConfirmLabel}
                    </button>
                  </div>
                </li>
              {:else}
                <li class="tp-row" data-testid="template-picker-row" data-template-id={template.id}>
                  <button
                    type="button"
                    class="tp-row__name"
                    role="option"
                    aria-selected="false"
                    data-testid="template-picker-row-name"
                    onclick={() => void handleInstantiate(template.id)}
                  >
                    {template.name}
                  </button>
                  <button
                    type="button"
                    class="tp-row__delete"
                    aria-label={TEMPLATE_PICKER_STRINGS.deleteLabel}
                    data-testid="template-picker-row-delete"
                    onclick={(e) => {
                      e.stopPropagation();
                      requestDelete(template.id);
                    }}
                  >
                    ×
                  </button>
                </li>
              {/if}
            {/each}
          </ul>
        {/if}

        <!-- Delete error (non-blocking) -->
        {#if deleteError !== null}
          <p class="tp-error" data-testid="template-picker-delete-error">{deleteError}</p>
        {/if}

        <!-- Instantiate error (non-blocking) -->
        {#if instantiateError !== null}
          <p class="tp-error" data-testid="template-picker-instantiate-error">
            {instantiateError}
          </p>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  /* Backdrop sits above the sidebar (z-index matches CheatSheet / ContextMenu layer). */
  .tp-backdrop {
    position: fixed;
    inset: 0;
    z-index: 90;
    background: rgba(0, 0, 0, 0.35);
    display: flex;
    align-items: flex-start;
    justify-content: flex-start;
    /* Align the panel to the left edge of the viewport so it anchors
       visually at the sidebar header area. */
    padding: 3rem 0 0 0;
  }

  .tp-panel {
    background: rgb(var(--bearings-surface-1));
    color: rgb(var(--bearings-fg));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.375rem;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    width: 20rem;
    max-height: calc(100vh - 6rem);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    margin-left: 0.5rem;
  }

  .tp-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid rgb(var(--bearings-border));
    flex-shrink: 0;
  }

  .tp-heading {
    font-size: 0.8rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: rgb(var(--bearings-fg-muted));
  }

  .tp-close {
    background: transparent;
    border: none;
    color: rgb(var(--bearings-fg-muted));
    font-size: 1rem;
    cursor: pointer;
    padding: 0.1rem 0.3rem;
    border-radius: 0.25rem;
  }

  .tp-close:hover {
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg));
  }

  .tp-body {
    overflow-y: auto;
    flex: 1;
    padding: 0.25rem 0;
  }

  .tp-status {
    padding: 0.5rem 0.75rem;
    font-size: 0.8rem;
    color: rgb(var(--bearings-fg-muted));
    margin: 0;
  }

  .tp-status--error {
    color: #f87171;
  }

  .tp-list {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .tp-row {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.15rem 0.5rem;
  }

  .tp-row--confirm {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    background: rgba(var(--bearings-surface-2), 0.5);
  }

  .tp-row__name {
    flex: 1;
    text-align: left;
    background: transparent;
    border: none;
    color: rgb(var(--bearings-fg));
    font-size: 0.875rem;
    padding: 0.3rem 0.25rem;
    border-radius: 0.25rem;
    cursor: pointer;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .tp-row__name:hover {
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg-strong));
  }

  .tp-row__delete {
    background: transparent;
    border: none;
    color: rgb(var(--bearings-fg-muted));
    font-size: 0.9rem;
    padding: 0.2rem 0.4rem;
    border-radius: 0.25rem;
    cursor: pointer;
    flex-shrink: 0;
    opacity: 0.6;
  }

  .tp-row__delete:hover {
    background: rgb(var(--bearings-surface-2));
    color: #f87171;
    opacity: 1;
  }

  .tp-confirm-msg {
    font-size: 0.8rem;
    color: rgb(var(--bearings-fg));
  }

  .tp-confirm-actions {
    display: flex;
    gap: 0.5rem;
  }

  .tp-btn {
    padding: 0.2rem 0.6rem;
    border-radius: 0.25rem;
    font-size: 0.8rem;
    cursor: pointer;
    border: 1px solid rgb(var(--bearings-border));
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg));
  }

  .tp-btn:hover {
    background: rgb(var(--bearings-surface-1));
  }

  .tp-btn--cancel {
    color: rgb(var(--bearings-fg-muted));
  }

  .tp-btn--danger {
    background: #ef4444;
    color: #fff;
    border-color: #ef4444;
  }

  .tp-btn--danger:hover {
    background: #dc2626;
    border-color: #dc2626;
  }

  .tp-error {
    padding: 0.4rem 0.75rem;
    font-size: 0.75rem;
    color: #f87171;
    margin: 0;
    border-top: 1px solid rgb(var(--bearings-border));
  }
</style>
