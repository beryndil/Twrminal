<script lang="ts">
  /**
   * Dialog for importing a session from an export JSON blob.
   *
   * Accepts two input methods:
   *
   * 1. **Paste** — the user pastes raw JSON into the textarea.
   * 2. **File pick** — the user selects a ``.json`` file; its text
   *    is read client-side and placed into the textarea.
   *
   * On submit the textarea content is parsed as JSON and POSTed to
   * ``POST /api/sessions/import``.  A 201 response closes the dialog
   * and invokes ``onImported`` with the new :class:`SessionOut` row so
   * the caller can navigate to it.  A 409 or other error is surfaced
   * inline inside the dialog.
   *
   * Per ``docs/behavior/sessions.md`` §"Import contract".
   */
  import { importSessionJson } from "$lib/api/sessions";
  import { ApiError } from "$lib/api/client";
  import type { SessionOut } from "$lib/api/sessions";

  interface Props {
    /** Called with the newly created session row on successful import. */
    onImported: (session: SessionOut) => void;
    onCancel: () => void;
  }

  const { onImported, onCancel }: Props = $props();

  let pasteText = $state("");
  let errorMessage = $state<string | null>(null);
  let isSubmitting = $state(false);
  let fileInput = $state<HTMLInputElement | null>(null);

  function handleKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      onCancel();
    }
  }

  async function handleFileChange(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    try {
      pasteText = await file.text();
      errorMessage = null;
    } catch {
      errorMessage = "Could not read the selected file.";
    }
  }

  async function handleSubmit(): Promise<void> {
    errorMessage = null;
    const raw = pasteText.trim();
    if (!raw) {
      errorMessage = "Paste or upload an export JSON first.";
      return;
    }
    let parsed: object;
    try {
      const value: unknown = JSON.parse(raw);
      if (typeof value !== "object" || value === null || Array.isArray(value)) {
        throw new SyntaxError("Expected a JSON object");
      }
      parsed = value as object;
    } catch {
      errorMessage = "Invalid JSON — check that you pasted a complete export file.";
      return;
    }
    isSubmitting = true;
    try {
      const session = await importSessionJson(parsed);
      onImported(session);
    } catch (err) {
      if (err instanceof ApiError) {
        const detail =
          typeof err.body === "object" && err.body !== null && "detail" in err.body
            ? String((err.body as Record<string, unknown>).detail)
            : `HTTP ${err.status}`;
        errorMessage = detail;
      } else {
        errorMessage = "Import failed — unexpected error.";
      }
    } finally {
      isSubmitting = false;
    }
  }
</script>

<div
  class="import-dialog-backdrop"
  role="presentation"
  data-testid="session-import-dialog-backdrop"
  onclick={onCancel}
  onkeydown={handleKeyDown}
>
  <div
    class="import-dialog"
    role="dialog"
    aria-modal="true"
    aria-label="Import session"
    tabindex="-1"
    data-testid="session-import-dialog"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCancel();
      } else {
        e.stopPropagation();
      }
    }}
  >
    <h2 class="import-dialog__title">Import session</h2>

    <p class="import-dialog__hint">
      Paste the contents of a session export file, or upload the
      <code>.json</code> file directly.
    </p>

    <!-- File picker -->
    <div class="import-dialog__file-row">
      <button
        type="button"
        class="import-dialog__file-btn"
        data-testid="session-import-file-btn"
        onclick={() => fileInput?.click()}
      >
        Choose file…
      </button>
      <input
        bind:this={fileInput}
        type="file"
        accept=".json,application/json"
        class="sr-only"
        data-testid="session-import-file-input"
        onchange={handleFileChange}
      />
    </div>

    <!-- Paste area -->
    <textarea
      class="import-dialog__textarea"
      data-testid="session-import-textarea"
      placeholder="Paste export JSON here…"
      rows={8}
      bind:value={pasteText}
    ></textarea>

    <!-- Inline error -->
    {#if errorMessage !== null}
      <p class="import-dialog__error" role="alert" data-testid="session-import-error">
        {errorMessage}
      </p>
    {/if}

    <div class="import-dialog__actions">
      <button
        type="button"
        class="import-dialog__btn import-dialog__btn--cancel"
        data-testid="session-import-cancel"
        onclick={onCancel}
      >
        Cancel
      </button>
      <button
        type="button"
        class="import-dialog__btn import-dialog__btn--submit"
        data-testid="session-import-submit"
        disabled={isSubmitting}
        onclick={handleSubmit}
      >
        {#if isSubmitting}
          Importing…
        {:else}
          Import
        {/if}
      </button>
    </div>
  </div>
</div>

<style>
  .import-dialog-backdrop {
    position: fixed;
    inset: 0;
    z-index: 200;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .import-dialog {
    background: rgb(var(--bearings-surface-1));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.5rem;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    min-width: 22rem;
    max-width: 32rem;
    width: 100%;
    padding: 1.25rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .import-dialog__title {
    font-size: 0.9375rem;
    font-weight: 600;
    color: rgb(var(--bearings-fg-strong));
    margin: 0;
  }

  .import-dialog__hint {
    font-size: 0.8125rem;
    color: rgb(var(--bearings-fg-muted));
    margin: 0;
  }

  .import-dialog__file-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .import-dialog__file-btn {
    padding: 0.25rem 0.75rem;
    border-radius: 0.25rem;
    font-size: 0.8125rem;
    cursor: pointer;
    border: 1px solid rgb(var(--bearings-border));
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg));
  }

  .import-dialog__file-btn:hover {
    background: rgb(var(--bearings-surface-1));
  }

  .import-dialog__textarea {
    width: 100%;
    resize: vertical;
    font-family: monospace;
    font-size: 0.75rem;
    padding: 0.5rem;
    border-radius: 0.25rem;
    border: 1px solid rgb(var(--bearings-border));
    background: rgb(var(--bearings-surface-0));
    color: rgb(var(--bearings-fg));
    box-sizing: border-box;
  }

  .import-dialog__error {
    font-size: 0.8125rem;
    color: #ef4444;
    margin: 0;
  }

  .import-dialog__actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
  }

  .import-dialog__btn {
    padding: 0.25rem 0.75rem;
    border-radius: 0.25rem;
    font-size: 0.875rem;
    cursor: pointer;
    border: 1px solid rgb(var(--bearings-border));
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg));
  }

  .import-dialog__btn:hover {
    background: rgb(var(--bearings-surface-1));
  }

  .import-dialog__btn--submit {
    background: rgb(var(--bearings-accent));
    color: #fff;
    border-color: rgb(var(--bearings-accent));
  }

  .import-dialog__btn--submit:hover:not(:disabled) {
    background: rgb(var(--bearings-accent-muted));
    border-color: rgb(var(--bearings-accent-muted));
  }

  .import-dialog__btn--submit:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border-width: 0;
  }
</style>
