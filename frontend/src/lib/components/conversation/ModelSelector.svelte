<script lang="ts">
  /**
   * Executor-model dropdown for the conversation header (spec §7).
   *
   * Displays the current session's executor model and lets the user
   * switch it mid-session.  Selecting a different model opens
   * :component:`ModelSwitchDialog` for confirmation; confirming fires
   * ``PATCH /api/sessions/{id}/model`` and the sessions-broadcast WS
   * merges the updated row into :data:`sessionsStore` automatically.
   *
   * Hidden when ``sessionId`` is null (no active session).
   *
   * Behavior anchor: ``docs/behavior/chat.md`` §"Manual mid-session
   * model switch".
   */
  import {
    KNOWN_EXECUTOR_MODELS,
    MODEL_SELECTOR_STRINGS,
    NEW_SESSION_STRINGS,
    type ExecutorModel,
  } from "../../config";
  import { patchSessionModel } from "../../api/sessions";
  import { sessionsStore } from "../../stores/sessions.svelte";
  import ModelSwitchDialog from "./ModelSwitchDialog.svelte";

  interface Props {
    sessionId: string | null;
  }

  const { sessionId }: Props = $props();

  /** Full session row for the active session — drives both the select value
   *  and the token count passed to the dialog. */
  const session = $derived(
    sessionId === null ? null : (sessionsStore.sessions.find((s) => s.id === sessionId) ?? null),
  );

  const currentModel = $derived(session?.model ?? null);

  /**
   * Select value — falls back to ``"sonnet"`` when the stored model is
   * not in the known set (forward-compat: renders without crashing).
   */
  const selectValue = $derived(
    currentModel !== null && (KNOWN_EXECUTOR_MODELS as readonly string[]).includes(currentModel)
      ? currentModel
      : KNOWN_EXECUTOR_MODELS[0],
  );

  /** Model the user clicked but hasn't confirmed yet. */
  let pendingModel = $state<string | null>(null);
  let switching = $state(false);
  let errorMsg = $state<string | null>(null);

  function handleChange(event: Event): void {
    if (sessionId === null || currentModel === null) return;
    const target = event.target as HTMLSelectElement;
    const chosen = target.value;
    if (chosen === currentModel) return;
    // Reset the select to the current model immediately — the dialog
    // will own the pending choice until the user confirms or cancels.
    target.value = currentModel;
    pendingModel = chosen;
    errorMsg = null;
  }

  async function handleConfirm(): Promise<void> {
    if (sessionId === null || pendingModel === null) return;
    switching = true;
    errorMsg = null;
    try {
      await patchSessionModel(sessionId, pendingModel);
      // The sessions-broadcast WS merges the returned row — no manual
      // store update needed.
      pendingModel = null;
    } catch {
      errorMsg = MODEL_SELECTOR_STRINGS.saveError;
    } finally {
      switching = false;
    }
  }

  function handleCancel(): void {
    pendingModel = null;
    errorMsg = null;
  }
</script>

{#if sessionId !== null && currentModel !== null}
  <div
    class="model-selector flex items-center gap-1.5 text-xs text-fg-muted"
    data-testid="model-selector"
  >
    <span class="select-none" aria-hidden="true">
      {MODEL_SELECTOR_STRINGS.labelPrefix}
    </span>
    <select
      class="rounded border border-border bg-surface-1 px-1.5 py-0.5 text-xs text-fg-strong
             hover:border-accent focus:outline-none focus:ring-1 focus:ring-accent
             disabled:opacity-50"
      aria-label={MODEL_SELECTOR_STRINGS.ariaLabel}
      data-testid="model-select"
      disabled={switching}
      value={selectValue}
      onchange={handleChange}
    >
      {#each KNOWN_EXECUTOR_MODELS as model (model)}
        <option value={model}>{NEW_SESSION_STRINGS.executorLabels[model as ExecutorModel]}</option>
      {/each}
    </select>
  </div>

  {#if pendingModel !== null}
    <ModelSwitchDialog
      fromModel={currentModel}
      toModel={pendingModel}
      contextTokens={session?.last_context_tokens ?? null}
      {switching}
      {errorMsg}
      onConfirm={handleConfirm}
      onCancel={handleCancel}
    />
  {/if}
{/if}
