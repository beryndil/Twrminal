<script lang="ts">
  /**
   * Deterministic "Test against message" dialog (spec §10).
   *
   * Per spec §10 ("Modified: Routing rule editor"):
   *
   *   "Test against message" is a deterministic dialog — it evaluates
   *   the rule's match condition against pasted text and shows the
   *   resulting routing decision. No LLM call. Test inputs are not
   *   stored.
   *
   * Implementation choices:
   *
   * - Evaluation runs client-side via :func:`evaluateRuleMatch` in
   *   ``api/routingRules.ts``, which mirrors the backend match
   *   semantics in :func:`bearings.agent.routing._matches` (item 1.8).
   *   No fetch, no LLM, no DB write — the dialog is pure in.
   * - The dialog shows a single rule's verdict, not the full
   *   evaluation chain. The spec §3 evaluation order ("first match
   *   wins across tag rules, then system rules") is the new-session
   *   dialog's RoutingPreview surface (item 2.4); this dialog is the
   *   per-rule test action exposed in the editor's row context-menu.
   * - The dialog is a controlled overlay — the parent owns the
   *   open/close state and the active rule. ``onClose`` is fired on
   *   the close button + Escape + clicking the backdrop.
   *
   * Behavior anchors:
   *
   * - Spec §10 (verbatim quoted above) is the FULLY GOVERNING source
   *   for this surface. ``docs/behavior/chat.md`` and
   *   ``docs/behavior/context-menus.md`` are silent on the rule
   *   editor's UX (decided-and-documented as a "behavioral gap" in
   *   the executor's self-verification block per plan §"Behavioral
   *   gap escalation").
   */
  import {
    NEW_SESSION_STRINGS,
    ROUTING_EDITOR_STRINGS,
    type RoutingMatchType,
    KNOWN_ROUTING_MATCH_TYPES,
  } from "../../config";
  import { evaluateRuleMatch, type RuleEvaluationResult } from "../../api/routingRules";

  /**
   * Rule-shape subset the dialog needs. Both ``RoutingRuleOut`` and
   * ``SystemRoutingRuleOut`` satisfy this — the editor passes either
   * shape via structural typing.
   */
  interface RuleLike {
    id: number;
    match_type: string;
    match_value: string | null;
    executor_model: string;
    advisor_model: string | null;
    advisor_max_uses: number;
    effort_level: string;
    reason: string;
  }

  interface Props {
    rule: RuleLike;
    onClose: () => void;
  }

  const { rule, onClose }: Props = $props();

  let messageText = $state("");
  let result: RuleEvaluationResult | null = $state(null);

  /**
   * Project the wire ``match_type`` string onto the typed alphabet.
   * Backend ``CHECK`` constraint guarantees the column is one of the
   * five values, so the cast is safe — the fallback path (no
   * matching alphabet entry) returns ``null`` and the dialog falls
   * back to the literal column value for display.
   */
  const matchTypeNarrow = $derived(narrowMatchType(rule.match_type));

  function narrowMatchType(value: string): RoutingMatchType | null {
    return KNOWN_ROUTING_MATCH_TYPES.includes(value as RoutingMatchType)
      ? (value as RoutingMatchType)
      : null;
  }

  function evaluate(): void {
    if (matchTypeNarrow === null) {
      result = { matched: false, invalidRegex: false };
      return;
    }
    result = evaluateRuleMatch(matchTypeNarrow, rule.match_value, messageText);
  }

  function executorDisplay(model: string): string {
    return (
      NEW_SESSION_STRINGS.executorLabels[
        model as keyof typeof NEW_SESSION_STRINGS.executorLabels
      ] ?? model
    );
  }

  function advisorDisplay(model: string | null): string {
    if (model === null) {
      return NEW_SESSION_STRINGS.advisorLabels[""];
    }
    return (
      NEW_SESSION_STRINGS.advisorLabels[model as keyof typeof NEW_SESSION_STRINGS.advisorLabels] ??
      model
    );
  }

  function effortDisplay(level: string): string {
    return (
      NEW_SESSION_STRINGS.effortLabels[level as keyof typeof NEW_SESSION_STRINGS.effortLabels] ??
      level
    );
  }

  function onBackdropClick(event: MouseEvent): void {
    if (event.target === event.currentTarget) {
      onClose();
    }
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div
  class="test-dialog__backdrop"
  data-testid="test-dialog-backdrop"
  role="presentation"
  onclick={onBackdropClick}
>
  <div
    class="test-dialog"
    role="dialog"
    aria-modal="true"
    aria-label={ROUTING_EDITOR_STRINGS.testDialogAriaLabel}
    data-testid="test-dialog"
    data-rule-id={rule.id}
  >
    <header class="test-dialog__header">
      <h2 class="test-dialog__title" data-testid="test-dialog-title">
        {ROUTING_EDITOR_STRINGS.testDialogTitle}
      </h2>
      <button
        type="button"
        class="test-dialog__close"
        data-testid="test-dialog-close"
        aria-label={ROUTING_EDITOR_STRINGS.testDialogCloseLabel}
        onclick={onClose}
      >
        ×
      </button>
    </header>

    <p class="test-dialog__intro" data-testid="test-dialog-intro">
      {ROUTING_EDITOR_STRINGS.testDialogIntro}
    </p>

    <label class="test-dialog__field">
      <span class="test-dialog__label">{ROUTING_EDITOR_STRINGS.testDialogMessageLabel}</span>
      <textarea
        class="test-dialog__textarea"
        data-testid="test-dialog-message"
        placeholder={ROUTING_EDITOR_STRINGS.testDialogMessagePlaceholder}
        bind:value={messageText}
      ></textarea>
    </label>

    <div class="test-dialog__actions">
      <button
        type="button"
        class="test-dialog__evaluate"
        data-testid="test-dialog-evaluate"
        onclick={evaluate}
      >
        {ROUTING_EDITOR_STRINGS.testDialogEvaluateLabel}
      </button>
    </div>

    {#if result !== null}
      <section
        class="test-dialog__result"
        data-testid="test-dialog-result"
        data-matched={result.matched ? "true" : "false"}
        data-invalid-regex={result.invalidRegex ? "true" : "false"}
      >
        {#if result.invalidRegex}
          <p class="test-dialog__invalid" data-testid="test-dialog-invalid-regex">
            {ROUTING_EDITOR_STRINGS.testDialogInvalidRegex}
          </p>
        {:else if result.matched}
          <p class="test-dialog__verdict-matched" data-testid="test-dialog-matched">
            {ROUTING_EDITOR_STRINGS.testDialogResultMatched}
          </p>
          <dl class="test-dialog__decision">
            <dt>{ROUTING_EDITOR_STRINGS.testDialogResultExecutorLabel}</dt>
            <dd data-testid="test-dialog-executor">{executorDisplay(rule.executor_model)}</dd>

            <dt>{ROUTING_EDITOR_STRINGS.testDialogResultAdvisorLabel}</dt>
            <dd data-testid="test-dialog-advisor">{advisorDisplay(rule.advisor_model)}</dd>

            <dt>{ROUTING_EDITOR_STRINGS.testDialogResultEffortLabel}</dt>
            <dd data-testid="test-dialog-effort">{effortDisplay(rule.effort_level)}</dd>

            <dt>{ROUTING_EDITOR_STRINGS.testDialogResultReasonLabel}</dt>
            <dd data-testid="test-dialog-reason">{rule.reason}</dd>
          </dl>
        {:else}
          <p class="test-dialog__verdict-missed" data-testid="test-dialog-missed">
            {ROUTING_EDITOR_STRINGS.testDialogResultMissed}
          </p>
        {/if}
      </section>
    {/if}
  </div>
</div>

<style>
  .test-dialog__backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 30;
    padding: 1rem;
  }
  .test-dialog {
    background: rgb(var(--bearings-surface-1));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.5rem;
    padding: 1rem 1.25rem;
    width: min(560px, 100%);
    max-height: calc(100vh - 4rem);
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    color: rgb(var(--bearings-fg));
  }
  .test-dialog__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .test-dialog__title {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
  }
  .test-dialog__close {
    background: transparent;
    border: none;
    color: inherit;
    font-size: 1.25rem;
    line-height: 1;
    cursor: pointer;
    padding: 0.25rem 0.5rem;
  }
  .test-dialog__intro {
    margin: 0;
    font-size: 0.8125rem;
    color: rgb(var(--bearings-fg-muted));
  }
  .test-dialog__field {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  .test-dialog__label {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: rgb(var(--bearings-fg-muted));
  }
  .test-dialog__textarea {
    min-height: 6rem;
    padding: 0.5rem;
    border-radius: 0.25rem;
    background: rgb(var(--bearings-surface-2));
    border: 1px solid rgb(var(--bearings-border));
    color: inherit;
    font: inherit;
    resize: vertical;
  }
  .test-dialog__actions {
    display: flex;
    justify-content: flex-end;
  }
  .test-dialog__evaluate {
    background: rgb(var(--bearings-accent));
    color: rgb(var(--bearings-surface-0));
    border: none;
    border-radius: 0.25rem;
    padding: 0.375rem 0.75rem;
    cursor: pointer;
    font: inherit;
  }
  .test-dialog__result {
    border-top: 1px solid rgb(var(--bearings-border));
    padding-top: 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .test-dialog__verdict-matched {
    margin: 0;
    color: #4ade80;
    font-weight: 600;
  }
  .test-dialog__verdict-missed {
    margin: 0;
    color: rgb(var(--bearings-fg-muted));
  }
  .test-dialog__invalid {
    margin: 0;
    color: #f87171;
  }
  .test-dialog__decision {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 0.25rem 0.75rem;
    margin: 0;
    font-size: 0.8125rem;
  }
  .test-dialog__decision dt {
    color: rgb(var(--bearings-fg-muted));
  }
  .test-dialog__decision dd {
    margin: 0;
    font-family: var(--font-mono, ui-monospace, monospace);
  }
</style>
