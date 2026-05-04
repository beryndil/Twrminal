<script lang="ts">
  /**
   * Confirmation dialog for mid-session model switching (spec §7).
   *
   * Shown when the user picks a different executor in the conversation
   * header's :component:`ModelSelector` dropdown.  Displays:
   *
   * - Title: "Switch executor: Sonnet 4.6 → Opus 4.7"
   * - Recost body: "This will re-cost ~N input tokens of conversation
   *   history at Opus 4.7 rates."  Falls back to an "unknown" copy
   *   when ``contextTokens`` is null (session has not yet completed a
   *   turn so ``last_context_tokens`` is unpopulated).
   * - Estimated cost line: "Estimated additional cost: ~$X.XX"
   *   (tokens × new model's input rate; omitted when tokens unknown).
   *
   * Per spec §13 risk 4 all numbers are approximate and the copy
   * uses "estimated" honestly.
   *
   * Behavior anchor: ``docs/behavior/chat.md`` §"Manual mid-session
   * model switch".
   */
  import {
    EXECUTOR_MODEL_OPUS,
    EXECUTOR_MODEL_SONNET,
    MODEL_INPUT_RATES_USD_PER_MILLION,
    MODEL_SWITCH_DIALOG_STRINGS,
    NEW_SESSION_STRINGS,
    type ExecutorModel,
  } from "../../config";

  interface Props {
    fromModel: string;
    toModel: string;
    /** ``SessionOut.last_context_tokens`` — null when no turn completed. */
    contextTokens: number | null;
    switching: boolean;
    errorMsg: string | null;
    onConfirm: () => void;
    onCancel: () => void;
  }

  const { fromModel, toModel, contextTokens, switching, errorMsg, onConfirm, onCancel }: Props =
    $props();

  /**
   * Resolve a wire model name to its display label using the same table
   * the new-session dialog uses.  Falls back to the wire name when the
   * value is not in the known set (forward-compat).
   */
  function modelLabel(model: string): string {
    const known: ExecutorModel[] = [EXECUTOR_MODEL_SONNET, EXECUTOR_MODEL_OPUS, "haiku"];
    if (known.includes(model as ExecutorModel)) {
      return NEW_SESSION_STRINGS.executorLabels[model as ExecutorModel];
    }
    return model;
  }

  const fromLabel = $derived(modelLabel(fromModel));
  const toLabel = $derived(modelLabel(toModel));

  const title = $derived(
    MODEL_SWITCH_DIALOG_STRINGS.titleTemplate.replace("{from}", fromLabel).replace("{to}", toLabel),
  );

  const recostBody = $derived(
    contextTokens === null
      ? MODEL_SWITCH_DIALOG_STRINGS.recostBodyUnknown
      : MODEL_SWITCH_DIALOG_STRINGS.recostBodyTemplate
          .replace("{tokens}", contextTokens.toLocaleString())
          .replace("{to}", toLabel),
  );

  /**
   * Estimated cost of re-contextualising the current window at the
   * new model's input rate.  Null when token count is unknown or the
   * model wire name isn't in the pricing table.
   */
  const estimatedCostUsd = $derived((): number | null => {
    if (contextTokens === null) return null;
    const rate = MODEL_INPUT_RATES_USD_PER_MILLION[toModel as ExecutorModel];
    if (rate === undefined) return null;
    return (contextTokens * rate) / 1_000_000;
  });

  const estimatedCostLine = $derived((): string | null => {
    const cost = estimatedCostUsd();
    if (cost === null) return null;
    return MODEL_SWITCH_DIALOG_STRINGS.estimatedCostTemplate.replace("{cost}", cost.toFixed(2));
  });
</script>

<!-- Backdrop -->
<div
  class="model-switch-dialog__backdrop fixed inset-0 z-40 flex items-center justify-center bg-black/50"
  aria-modal="true"
  role="dialog"
  aria-label={MODEL_SWITCH_DIALOG_STRINGS.ariaLabel}
  data-testid="model-switch-dialog"
>
  <div class="model-switch-dialog__panel w-full max-w-md rounded-lg bg-surface-1 shadow-xl">
    <!-- Header -->
    <div class="border-b border-border px-4 py-3">
      <h2 class="text-sm font-semibold text-fg-strong" data-testid="model-switch-title">
        {title}
      </h2>
    </div>

    <!-- Body -->
    <div class="px-4 py-3 text-sm">
      <p class="text-fg-strong" data-testid="model-switch-recost-body">
        {recostBody}
      </p>
      {#if estimatedCostLine() !== null}
        <p class="mt-1 text-fg-muted" data-testid="model-switch-estimated-cost">
          {estimatedCostLine()}
        </p>
      {/if}
      {#if errorMsg !== null}
        <p class="mt-2 text-xs text-red-400" role="alert" data-testid="model-switch-error">
          {errorMsg}
        </p>
      {/if}
    </div>

    <!-- Footer -->
    <div class="flex justify-end gap-2 border-t border-border px-4 py-3">
      <button
        type="button"
        class="rounded border border-border bg-surface-2 px-4 py-1.5 text-sm
               font-medium text-fg-strong hover:bg-surface-1 disabled:opacity-50"
        disabled={switching}
        data-testid="model-switch-cancel"
        onclick={onCancel}
      >
        {MODEL_SWITCH_DIALOG_STRINGS.cancelLabel}
      </button>
      <button
        type="button"
        class="rounded bg-accent px-4 py-1.5 text-sm font-medium text-white
               hover:bg-accent/90 disabled:opacity-50"
        disabled={switching}
        data-testid="model-switch-confirm"
        onclick={onConfirm}
      >
        {switching
          ? MODEL_SWITCH_DIALOG_STRINGS.switchingLabel
          : MODEL_SWITCH_DIALOG_STRINGS.switchLabel}
      </button>
    </div>
  </div>
</div>
