<script lang="ts">
  /**
   * One row of the routing rule editor.
   *
   * Spec §3 + §10 — renders a rule's editable fields:
   *
   *   [priority] [match-type ▾] [match-value..........] →
   *   [executor ▾] +  [advisor ▾] [☑ enabled]  [effort ▾]
   *   [reason....................]   [⋮]
   *
   * Drag-handle on the left to reorder. Right-click ⋮: Test against
   * message, Duplicate, Disable, Delete.
   *
   * Behavior anchors:
   *
   * - Spec §3 "Tag routing rules" — schema fields the row exposes.
   * - Spec §10 "Modified: Routing rule editor" — row layout +
   *   action menu items.
   * - Spec §8 — "Review:" prefix on the reason text when
   *   ``override_rate > 0.30`` over the last 14 days.
   *
   * The row is presentational over a single rule. The parent
   * (:class:`RoutingRuleEditor`) owns the side-effects: the row
   * fires ``onPatch`` / ``onDuplicate`` / ``onDelete`` / ``onTest``
   * with the typed rule shape, never an API call.
   */
  import {
    KNOWN_ADVISOR_MODELS,
    KNOWN_EFFORT_LEVELS,
    KNOWN_EXECUTOR_MODELS,
    KNOWN_ROUTING_MATCH_TYPES,
    NEW_SESSION_STRINGS,
    OVERRIDE_RATE_REVIEW_THRESHOLD,
    OVERRIDE_RATE_WINDOW_DAYS,
    ROUTING_EDITOR_STRINGS,
    ROUTING_MATCH_TYPE_ALWAYS,
    ROUTING_MATCH_TYPE_KEYWORD,
    ROUTING_MATCH_TYPE_LENGTH_GT,
    ROUTING_MATCH_TYPE_LENGTH_LT,
    ROUTING_MATCH_TYPE_REGEX,
    type AdvisorModelChoice,
    type EffortLevel,
    type ExecutorModel,
    type RoutingMatchType,
  } from "../../config";
  import {
    isValidRegex,
    type RoutingRuleIn,
    type RoutingRuleOut,
    type SystemRoutingRuleOut,
  } from "../../api/routingRules";

  /**
   * Discriminated rule prop — either a tag rule (no ``seeded``) or a
   * system rule (with ``seeded``). The component reads only the
   * shared columns + the optional ``seeded`` flag, which controls the
   * "Seeded" badge presence.
   */
  type RuleRowRule =
    | (RoutingRuleOut & { kind: "tag" })
    | (SystemRoutingRuleOut & { kind: "system" });

  interface Props {
    rule: RuleRowRule;
    /**
     * Override rate for this rule over the
     * :data:`OVERRIDE_RATE_WINDOW_DAYS` window. ``null`` when the
     * aggregator hasn't reported a row for this rule (no fires yet,
     * or the rate is sub-threshold and the editor filtered it out).
     * The "Review:" prefix lights when ``rate > threshold``.
     */
    overrideRate: number | null;
    onPatch: (body: RoutingRuleIn) => void;
    onDuplicate: () => void;
    onDelete: () => void;
    onTest: () => void;
    /** Drag-reorder hooks; the parent owns the index bookkeeping. */
    onDragStart?: (event: DragEvent) => void;
    onDragOver?: (event: DragEvent) => void;
    onDrop?: (event: DragEvent) => void;
  }

  const {
    rule,
    overrideRate,
    onPatch,
    onDuplicate,
    onDelete,
    onTest,
    onDragStart,
    onDragOver,
    onDrop,
  }: Props = $props();

  /**
   * "Review:" trigger — spec §8 threshold is
   * :data:`OVERRIDE_RATE_REVIEW_THRESHOLD` (0.30) over the last
   * :data:`OVERRIDE_RATE_WINDOW_DAYS` (14). The aggregator surface
   * already filters its top-level "rules to review" list against this
   * threshold (item 1.8); the row re-checks locally so the prefix
   * appears whenever a reviewer hands the row a non-null rate over
   * the threshold, without re-deciding the threshold across two
   * surfaces.
   */
  const isReview = $derived(overrideRate !== null && overrideRate > OVERRIDE_RATE_REVIEW_THRESHOLD);

  const reviewTooltip = $derived(
    overrideRate === null
      ? ""
      : ROUTING_EDITOR_STRINGS.reviewTooltipTemplate
          .replace("{pct}", `${Math.round(overrideRate * 100)}`)
          .replace("{days}", `${OVERRIDE_RATE_WINDOW_DAYS}`),
  );

  /**
   * Match-value placeholder text per match-type. ``always`` disables
   * the input entirely (spec §3: "match_value is NULL for
   * match_type='always'").
   */
  const matchValuePlaceholder = $derived(matchValuePlaceholderFor(rule.match_type));

  function matchValuePlaceholderFor(matchType: string): string {
    switch (matchType) {
      case ROUTING_MATCH_TYPE_KEYWORD:
        return ROUTING_EDITOR_STRINGS.rowMatchValuePlaceholderKeyword;
      case ROUTING_MATCH_TYPE_REGEX:
        return ROUTING_EDITOR_STRINGS.rowMatchValuePlaceholderRegex;
      case ROUTING_MATCH_TYPE_LENGTH_GT:
      case ROUTING_MATCH_TYPE_LENGTH_LT:
        return ROUTING_EDITOR_STRINGS.rowMatchValuePlaceholderLength;
      case ROUTING_MATCH_TYPE_ALWAYS:
        return ROUTING_EDITOR_STRINGS.rowMatchValueDisabledAlways;
      default:
        return "";
    }
  }

  const isAlways = $derived(rule.match_type === ROUTING_MATCH_TYPE_ALWAYS);

  /**
   * Regex-validity check for the inline warning. Spec §3: "Invalid
   * regexes disable the rule and surface an error in the editor."
   * The check runs only when ``match_type === 'regex'`` and the
   * value is non-empty — empty regex is allowed at the row level
   * because a half-typed pattern is not yet "invalid", just
   * incomplete; the test dialog reports the same.
   */
  const regexInvalid = $derived(
    rule.match_type === ROUTING_MATCH_TYPE_REGEX &&
      rule.match_value !== null &&
      rule.match_value !== "" &&
      !isValidRegex(rule.match_value),
  );

  /**
   * The advisor max_uses input is hidden when no advisor is selected
   * — the column is meaningful only when ``advisor_model !== null``.
   */
  const showAdvisorMaxUses = $derived(rule.advisor_model !== null);

  /**
   * Fields the row binds against. We project the rule into a local
   * draft so a controlled input change can call ``onPatch`` with the
   * full ``RoutingRuleIn`` shape — the parent then issues the PATCH.
   */
  function patchWith(overrides: Partial<RoutingRuleIn>): void {
    onPatch({
      priority: rule.priority,
      enabled: rule.enabled,
      match_type: rule.match_type,
      match_value: rule.match_value,
      executor_model: rule.executor_model,
      advisor_model: rule.advisor_model,
      advisor_max_uses: rule.advisor_max_uses,
      effort_level: rule.effort_level,
      reason: rule.reason,
      ...overrides,
    });
  }

  function onPriorityChange(event: Event): void {
    const target = event.currentTarget as HTMLInputElement;
    const next = Number.parseInt(target.value, 10);
    if (!Number.isFinite(next) || next < 0) {
      return;
    }
    patchWith({ priority: next });
  }

  function onMatchTypeChange(event: Event): void {
    const target = event.currentTarget as HTMLSelectElement;
    const next = target.value;
    // ``always`` rules carry NULL match_value per the spec §3 schema
    // CHECK constraint — clear the value when the user pivots into
    // ``always`` so a stale leftover from another match-type doesn't
    // round-trip through the API.
    const matchValue = next === ROUTING_MATCH_TYPE_ALWAYS ? null : (rule.match_value ?? "");
    patchWith({ match_type: next, match_value: matchValue });
  }

  function onMatchValueChange(event: Event): void {
    const target = event.currentTarget as HTMLInputElement;
    patchWith({ match_value: target.value });
  }

  function onExecutorChange(event: Event): void {
    const target = event.currentTarget as HTMLSelectElement;
    patchWith({ executor_model: target.value });
  }

  function onAdvisorChange(event: Event): void {
    const target = event.currentTarget as HTMLSelectElement;
    // Empty-string sentinel encodes the "no advisor" choice on the
    // wire (spec §App A: ``advisor_model: str | None``).
    const next = target.value === "" ? null : target.value;
    patchWith({ advisor_model: next });
  }

  function onAdvisorMaxUsesChange(event: Event): void {
    const target = event.currentTarget as HTMLInputElement;
    const next = Number.parseInt(target.value, 10);
    if (!Number.isFinite(next) || next < 0) {
      return;
    }
    patchWith({ advisor_max_uses: next });
  }

  function onEffortChange(event: Event): void {
    const target = event.currentTarget as HTMLSelectElement;
    patchWith({ effort_level: target.value });
  }

  function onReasonChange(event: Event): void {
    const target = event.currentTarget as HTMLTextAreaElement;
    patchWith({ reason: target.value });
  }

  function onEnabledChange(event: Event): void {
    const target = event.currentTarget as HTMLInputElement;
    patchWith({ enabled: target.checked });
  }

  /**
   * Execute the delete affordance with a confirm() guard so a stray
   * click on a seeded rule (which the spec §3 default-set ships
   * with) doesn't lose the row irretrievably. Seeded rules can be
   * deleted but the editor labels them with a "Seeded" badge so the
   * user knows disabling is the safer surface.
   */
  function onDeleteClicked(): void {
    if (typeof window === "undefined") {
      onDelete();
      return;
    }
    if (window.confirm(ROUTING_EDITOR_STRINGS.actionDeleteConfirmTemplate)) {
      onDelete();
    }
  }

  /** Display labels for the dropdowns. */
  function executorLabel(value: string): string {
    return NEW_SESSION_STRINGS.executorLabels[value as ExecutorModel] ?? value;
  }

  function advisorLabel(value: AdvisorModelChoice | string): string {
    return NEW_SESSION_STRINGS.advisorLabels[value as AdvisorModelChoice] ?? value;
  }

  function effortLabel(value: string): string {
    return NEW_SESSION_STRINGS.effortLabels[value as EffortLevel] ?? value;
  }

  function matchTypeLabel(value: string): string {
    return ROUTING_EDITOR_STRINGS.matchTypeLabels[value as RoutingMatchType] ?? value;
  }

  /** ``advisor_model`` rendered as the select's bound value. */
  const advisorSelectValue = $derived(rule.advisor_model ?? "");

  const isSeeded = $derived(rule.kind === "system" && rule.seeded);
  const rowAriaLabel = $derived(
    ROUTING_EDITOR_STRINGS.rowAriaLabelTemplate.replace("{ruleId}", `${rule.id}`),
  );
</script>

<li
  class="rule-row"
  class:rule-row--disabled={!rule.enabled}
  class:rule-row--review={isReview}
  class:rule-row--seeded={isSeeded}
  data-testid="rule-row"
  data-rule-id={rule.id}
  data-rule-kind={rule.kind}
  data-enabled={rule.enabled ? "true" : "false"}
  data-review={isReview ? "true" : "false"}
  data-seeded={isSeeded ? "true" : "false"}
  aria-label={rowAriaLabel}
  draggable="true"
  ondragstart={onDragStart}
  ondragover={onDragOver}
  ondrop={onDrop}
>
  <button
    type="button"
    class="rule-row__handle"
    data-testid="rule-row-handle"
    aria-label={ROUTING_EDITOR_STRINGS.rowDragHandleAriaLabel}
    title={ROUTING_EDITOR_STRINGS.rowDragHandleAriaLabel}
  >
    ⋮⋮
  </button>

  <div class="rule-row__priority">
    <label>
      <span class="rule-row__field-label">{ROUTING_EDITOR_STRINGS.rowPriorityLabel}</span>
      <input
        type="number"
        min="0"
        class="rule-row__priority-input"
        data-testid="rule-row-priority"
        value={rule.priority}
        onchange={onPriorityChange}
      />
    </label>
  </div>

  <div class="rule-row__match">
    <label>
      <span class="rule-row__field-label">{ROUTING_EDITOR_STRINGS.rowMatchTypeLabel}</span>
      <select
        class="rule-row__match-type"
        data-testid="rule-row-match-type"
        value={rule.match_type}
        onchange={onMatchTypeChange}
      >
        {#each KNOWN_ROUTING_MATCH_TYPES as value (value)}
          <option {value}>{matchTypeLabel(value)}</option>
        {/each}
      </select>
    </label>

    <label>
      <span class="rule-row__field-label">{ROUTING_EDITOR_STRINGS.rowMatchValueLabel}</span>
      <input
        type="text"
        class="rule-row__match-value"
        data-testid="rule-row-match-value"
        value={rule.match_value ?? ""}
        placeholder={matchValuePlaceholder}
        disabled={isAlways}
        onchange={onMatchValueChange}
      />
    </label>
    {#if regexInvalid}
      <p class="rule-row__warning" data-testid="rule-row-invalid-regex" role="alert">
        {ROUTING_EDITOR_STRINGS.rowMatchValueInvalidRegex}
      </p>
    {/if}
  </div>

  <div class="rule-row__decision">
    <label>
      <span class="rule-row__field-label">{ROUTING_EDITOR_STRINGS.rowExecutorLabel}</span>
      <select
        class="rule-row__executor"
        data-testid="rule-row-executor"
        value={rule.executor_model}
        onchange={onExecutorChange}
      >
        {#each KNOWN_EXECUTOR_MODELS as value (value)}
          <option {value}>{executorLabel(value)}</option>
        {/each}
      </select>
    </label>

    <label>
      <span class="rule-row__field-label">{ROUTING_EDITOR_STRINGS.rowAdvisorLabel}</span>
      <select
        class="rule-row__advisor"
        data-testid="rule-row-advisor"
        value={advisorSelectValue}
        onchange={onAdvisorChange}
      >
        {#each KNOWN_ADVISOR_MODELS as value (value)}
          <option {value}>{advisorLabel(value)}</option>
        {/each}
      </select>
    </label>

    {#if showAdvisorMaxUses}
      <label>
        <span class="rule-row__field-label">{ROUTING_EDITOR_STRINGS.rowAdvisorMaxUsesLabel}</span>
        <input
          type="number"
          min="0"
          class="rule-row__advisor-max-uses"
          data-testid="rule-row-advisor-max-uses"
          value={rule.advisor_max_uses}
          onchange={onAdvisorMaxUsesChange}
        />
      </label>
    {/if}

    <label>
      <span class="rule-row__field-label">{ROUTING_EDITOR_STRINGS.rowEffortLabel}</span>
      <select
        class="rule-row__effort"
        data-testid="rule-row-effort"
        value={rule.effort_level}
        onchange={onEffortChange}
      >
        {#each KNOWN_EFFORT_LEVELS as value (value)}
          <option {value}>{effortLabel(value)}</option>
        {/each}
      </select>
    </label>
  </div>

  <div class="rule-row__reason">
    <label>
      <span class="rule-row__field-label">{ROUTING_EDITOR_STRINGS.rowReasonLabel}</span>
      <textarea
        class="rule-row__reason-input"
        data-testid="rule-row-reason"
        placeholder={ROUTING_EDITOR_STRINGS.rowReasonPlaceholder}
        value={rule.reason}
        onchange={onReasonChange}
      ></textarea>
    </label>
    {#if isReview}
      <p class="rule-row__review-flag" data-testid="rule-row-review-flag" title={reviewTooltip}>
        {ROUTING_EDITOR_STRINGS.reviewPrefix}
        <span data-testid="rule-row-review-reason" class="rule-row__review-reason">
          {rule.reason}
        </span>
      </p>
    {/if}
  </div>

  <div class="rule-row__controls">
    <label class="rule-row__enabled-label">
      <input
        type="checkbox"
        class="rule-row__enabled"
        data-testid="rule-row-enabled"
        checked={rule.enabled}
        onchange={onEnabledChange}
      />
      <span>{ROUTING_EDITOR_STRINGS.rowEnabledLabel}</span>
    </label>

    {#if isSeeded}
      <span
        class="rule-row__seeded-badge"
        data-testid="rule-row-seeded"
        title={ROUTING_EDITOR_STRINGS.rowSeededIndicatorTitle}
      >
        {ROUTING_EDITOR_STRINGS.rowSeededIndicatorLabel}
      </span>
    {/if}

    <div
      class="rule-row__actions"
      role="group"
      aria-label={ROUTING_EDITOR_STRINGS.actionMenuAriaLabel}
    >
      <button type="button" class="rule-row__action" data-testid="rule-row-test" onclick={onTest}>
        {ROUTING_EDITOR_STRINGS.actionTestLabel}
      </button>
      <button
        type="button"
        class="rule-row__action"
        data-testid="rule-row-duplicate"
        onclick={onDuplicate}
      >
        {ROUTING_EDITOR_STRINGS.actionDuplicateLabel}
      </button>
      <button
        type="button"
        class="rule-row__action rule-row__action--danger"
        data-testid="rule-row-delete"
        onclick={onDeleteClicked}
      >
        {ROUTING_EDITOR_STRINGS.actionDeleteLabel}
      </button>
    </div>
  </div>
</li>

<style>
  .rule-row {
    display: grid;
    grid-template-columns: auto auto 1fr 1fr 1fr auto;
    gap: 0.5rem;
    align-items: start;
    padding: 0.5rem 0.75rem;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.375rem;
    background: rgb(var(--bearings-surface-1));
  }
  .rule-row--disabled {
    opacity: 0.55;
  }
  .rule-row--review {
    border-color: #facc15;
    box-shadow: 0 0 0 1px #facc15 inset;
  }
  .rule-row--seeded {
    border-style: dashed;
  }
  .rule-row__handle {
    background: transparent;
    border: none;
    color: rgb(var(--bearings-fg-muted));
    cursor: grab;
    padding: 0.25rem;
    align-self: center;
    font: inherit;
  }
  .rule-row__field-label {
    display: block;
    font-size: 0.6875rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: rgb(var(--bearings-fg-muted));
    margin-bottom: 0.125rem;
  }
  .rule-row__priority-input {
    width: 4rem;
  }
  .rule-row__match,
  .rule-row__decision,
  .rule-row__reason,
  .rule-row__controls {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  .rule-row__decision {
    flex-direction: row;
    align-items: flex-end;
    flex-wrap: wrap;
  }
  .rule-row__reason-input {
    width: 100%;
    min-height: 2.5rem;
    resize: vertical;
  }
  .rule-row__warning,
  .rule-row__review-flag {
    margin: 0;
    font-size: 0.75rem;
  }
  .rule-row__warning {
    color: #f87171;
  }
  .rule-row__review-flag {
    color: #facc15;
    font-weight: 600;
  }
  .rule-row__controls {
    align-items: flex-start;
  }
  .rule-row__enabled-label {
    display: flex;
    gap: 0.25rem;
    align-items: center;
    font-size: 0.8125rem;
  }
  .rule-row__seeded-badge {
    font-size: 0.6875rem;
    padding: 0.125rem 0.375rem;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    color: rgb(var(--bearings-fg-muted));
  }
  .rule-row__actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
  }
  .rule-row__action {
    background: transparent;
    color: rgb(var(--bearings-fg));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.25rem 0.5rem;
    cursor: pointer;
    font: inherit;
    font-size: 0.75rem;
  }
  .rule-row__action--danger {
    color: #f87171;
  }
  input,
  select,
  textarea {
    background: rgb(var(--bearings-surface-2));
    color: inherit;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.25rem 0.375rem;
    font: inherit;
  }
</style>
