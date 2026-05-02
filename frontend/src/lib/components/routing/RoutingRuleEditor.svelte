<script lang="ts">
  /**
   * Routing rule editor (spec §3 + §10).
   *
   * Top-level component for editing both the per-tag rule set and the
   * system-wide rule set. The same component covers both surfaces by
   * branching on a ``kind`` prop: ``"tag"`` lights up the
   * ``GET/POST /api/tags/{id}/routing`` + reorder endpoints (spec §9),
   * ``"system"`` lights up ``/api/routing/system``.
   *
   * Surfaces (spec §10 "Modified: Routing rule editor"):
   *
   * - List of rules in priority order.
   * - Drag-and-drop reorder.
   *   - Tag rules use the documented
   *     ``PATCH /api/tags/{id}/routing/reorder`` endpoint (spec §9).
   *   - System rules have no documented reorder endpoint, so the
   *     editor re-stamps each rule's ``priority`` via per-rule
   *     PATCHes (decided-and-documented per item 1.8: spec §3 says
   *     "priorities are sparse" + "User-added system rules slot in
   *     between the seeded ones at any priority", so the editor
   *     issues a PATCH per rule with the new sparse priority).
   * - Per-row enable/disable toggle (PATCH the rule with
   *   ``enabled = !enabled``).
   * - Per-row duplicate (POST a fresh rule cloned from the source).
   * - Per-row delete (DELETE the rule).
   * - Per-row "Test against message" — opens a deterministic dialog
   *   that evaluates the rule's match clause client-side (no LLM,
   *   per spec §10).
   *
   * Override-rate "Review:" highlighting (spec §8 + §10):
   *
   * - The editor fetches ``GET /api/usage/override_rates?days=14``
   *   on mount (item 1.8 aggregator).
   * - Rows whose ``rate > OVERRIDE_RATE_REVIEW_THRESHOLD`` (0.30)
   *   get a "Review:" prefix on the reason text + a coloured border
   *   so the user can see at-a-glance which rules need attention.
   * - The editor passes the rate down via ``RuleRow.overrideRate``;
   *   the row re-checks the threshold locally so a future widening
   *   of the surface (a slider for the threshold, e.g.) doesn't
   *   require the editor + the row to re-decide together.
   */
  import { onDestroy } from "svelte";

  import {
    OVERRIDE_RATE_WINDOW_DAYS,
    ROUTING_EDITOR_STRINGS,
    ROUTING_MATCH_TYPE_KEYWORD,
    ROUTING_RULE_DEFAULT_ADVISOR_MAX_USES,
    ROUTING_RULE_DEFAULT_PRIORITY_SYSTEM,
    ROUTING_RULE_DEFAULT_PRIORITY_TAG,
    ROUTING_RULE_KIND_TAG,
    EFFORT_LEVEL_AUTO,
    EXECUTOR_MODEL_SONNET,
    ADVISOR_MODEL_OPUS,
  } from "../../config";
  import {
    createSystemRule,
    createTagRule,
    deleteSystemRule,
    deleteTagRule,
    listSystemRules,
    listTagRules,
    reorderTagRules,
    systemRuleToInput,
    tagRuleToInput,
    updateSystemRule,
    updateTagRule,
    type RoutingRuleIn,
    type RoutingRuleOut,
    type SystemRoutingRuleOut,
  } from "../../api/routingRules";
  import { getOverrideRates, type OverrideRateOut } from "../../api/usage";

  import RuleRow from "./RuleRow.svelte";
  import TestAgainstMessageDialog from "./TestAgainstMessageDialog.svelte";

  /**
   * Test-seam shape so unit tests can swap the API surface for an
   * in-memory implementation. Production callers fall through to the
   * real typed clients in ``api/routingRules.ts`` + ``api/usage.ts``.
   *
   * Local, not exported — Svelte 5 instance-script ``export`` is the
   * legacy prop-binding surface; static type aliases stay file-local.
   * Tests construct the shape inline against the same property names
   * (the names are stable: they mirror the API client surface).
   */
  interface RoutingRuleEditorAdapters {
    listTagRules?: typeof listTagRules;
    createTagRule?: typeof createTagRule;
    updateTagRule?: typeof updateTagRule;
    deleteTagRule?: typeof deleteTagRule;
    reorderTagRules?: typeof reorderTagRules;
    listSystemRules?: typeof listSystemRules;
    createSystemRule?: typeof createSystemRule;
    updateSystemRule?: typeof updateSystemRule;
    deleteSystemRule?: typeof deleteSystemRule;
    getOverrideRates?: typeof getOverrideRates;
  }

  type Props =
    | {
        kind: "tag";
        tagId: number;
        adapters?: RoutingRuleEditorAdapters;
      }
    | {
        kind: "system";
        tagId?: undefined;
        adapters?: RoutingRuleEditorAdapters;
      };

  // The discriminated ``Props`` union forces a single non-destructured
  // ``$props()`` binding so the ``props.kind`` narrow propagates into
  // the script body (Svelte 5's destructuring collapses the discriminant
  // back to the broad union and loses ``tagId`` narrowing). This
  // component is never registered as a custom element — the SvelteKit
  // shell consumes it directly — so the custom-element-property
  // inference the rule guards against doesn't apply.
  /* eslint-disable-next-line svelte/valid-compile */
  const props: Props = $props();

  /**
   * Adapter map is ``$derived`` so a parent that swaps the
   * ``adapters`` prop mid-life (no current consumer does, but the
   * shape is reactive-safe) re-resolves. Using ``$derived`` also
   * silences the ``state_referenced_locally`` warning the svelte
   * compiler emits for plain-const reads of ``$props`` fields.
   */
  const adapters = $derived<Required<RoutingRuleEditorAdapters>>({
    listTagRules: props.adapters?.listTagRules ?? listTagRules,
    createTagRule: props.adapters?.createTagRule ?? createTagRule,
    updateTagRule: props.adapters?.updateTagRule ?? updateTagRule,
    deleteTagRule: props.adapters?.deleteTagRule ?? deleteTagRule,
    reorderTagRules: props.adapters?.reorderTagRules ?? reorderTagRules,
    listSystemRules: props.adapters?.listSystemRules ?? listSystemRules,
    createSystemRule: props.adapters?.createSystemRule ?? createSystemRule,
    updateSystemRule: props.adapters?.updateSystemRule ?? updateSystemRule,
    deleteSystemRule: props.adapters?.deleteSystemRule ?? deleteSystemRule,
    getOverrideRates: props.adapters?.getOverrideRates ?? getOverrideRates,
  });

  type LoadState = "idle" | "loading" | "ready" | "error";

  /**
   * Internal rule shape — RuleRow accepts a discriminated union, so
   * we tag each loaded row with its kind on entry. Tag rules carry
   * ``tag_id`` from the API; system rules carry ``seeded``. The
   * union lets one ``each`` block render either kind without a
   * second branch in the template.
   */
  type EditorRule =
    | (RoutingRuleOut & { kind: "tag" })
    | (SystemRoutingRuleOut & { kind: "system" });

  let rules: EditorRule[] = $state([]);
  let overrideRates: OverrideRateOut[] = $state([]);
  let loadState: LoadState = $state("idle");
  let saveError: string | null = $state(null);
  let testingRule: EditorRule | null = $state(null);

  /** Map (kind, ruleId) → rate so the row lookup is O(1). */
  const rateByRule = $derived(buildRateMap(overrideRates));

  function buildRateMap(rows: OverrideRateOut[]): Map<string, number> {
    const map = new Map<string, number>();
    for (const row of rows) {
      map.set(rateMapKey(row.rule_kind, row.rule_id), row.rate);
    }
    return map;
  }

  function rateMapKey(kind: string, id: number): string {
    return `${kind}:${id}`;
  }

  function rateFor(rule: EditorRule): number | null {
    return rateByRule.get(rateMapKey(rule.kind, rule.id)) ?? null;
  }

  /** Drag bookkeeping. Index of the row currently being dragged. */
  let dragIndex: number | null = $state(null);

  let activeAbort: AbortController | null = null;

  /**
   * Cancel any in-flight load on prop change (kind / tagId pivot)
   * and re-fetch. ``loadState !== 'idle'`` guard avoids a redundant
   * second fetch on the very first mount when ``$effect`` runs after
   * the initial state assignment.
   */
  $effect(() => {
    const _kind = props.kind;
    const _tagId = props.kind === "tag" ? props.tagId : null;
    void _kind;
    void _tagId;
    loadFromApi();
  });

  onDestroy(() => {
    if (activeAbort !== null) {
      activeAbort.abort();
      activeAbort = null;
    }
  });

  async function loadFromApi(): Promise<void> {
    if (activeAbort !== null) {
      activeAbort.abort();
    }
    const controller = new AbortController();
    activeAbort = controller;
    loadState = "loading";
    saveError = null;
    try {
      const [rawRules, rawOverrides] = await Promise.all([
        loadRulesFor(controller.signal),
        loadOverridesFor(controller.signal),
      ]);
      if (controller.signal.aborted) {
        return;
      }
      rules = rawRules;
      overrideRates = rawOverrides;
      loadState = "ready";
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }
      loadState = "error";
      void error;
    }
  }

  async function loadRulesFor(signal: AbortSignal): Promise<EditorRule[]> {
    if (props.kind === "tag") {
      const rows = await adapters.listTagRules(props.tagId, { signal });
      return rows.map((row) => ({ ...row, kind: "tag" as const }));
    }
    const rows = await adapters.listSystemRules({ signal });
    return rows.map((row) => ({ ...row, kind: "system" as const }));
  }

  async function loadOverridesFor(signal: AbortSignal): Promise<OverrideRateOut[]> {
    return await adapters.getOverrideRates({ days: OVERRIDE_RATE_WINDOW_DAYS, signal });
  }

  // ---- Mutations: enable/disable, edit, duplicate, delete -----------------

  async function patchRule(rule: EditorRule, body: RoutingRuleIn): Promise<void> {
    saveError = null;
    try {
      if (rule.kind === "tag") {
        const next = await adapters.updateTagRule(rule.id, body);
        replaceRule({ ...next, kind: "tag" as const });
        return;
      }
      const next = await adapters.updateSystemRule(rule.id, body);
      replaceRule({ ...next, kind: "system" as const });
    } catch (error) {
      saveError = ROUTING_EDITOR_STRINGS.saveFailed;
      void error;
    }
  }

  function replaceRule(next: EditorRule): void {
    rules = rules.map((row) => (row.kind === next.kind && row.id === next.id ? next : row));
  }

  async function duplicateRule(source: EditorRule): Promise<void> {
    saveError = null;
    const body: RoutingRuleIn =
      source.kind === "tag"
        ? { ...tagRuleToInput(source), priority: source.priority + 1 }
        : { ...systemRuleToInput(source), priority: source.priority + 1 };
    try {
      if (source.kind === "tag" && props.kind === "tag") {
        const created = await adapters.createTagRule(props.tagId, body);
        rules = [...rules, { ...created, kind: "tag" as const }].sort(byPriority);
        return;
      }
      if (source.kind === "system" && props.kind === "system") {
        const created = await adapters.createSystemRule(body);
        rules = [...rules, { ...created, kind: "system" as const }].sort(byPriority);
      }
    } catch (error) {
      saveError = ROUTING_EDITOR_STRINGS.saveFailed;
      void error;
    }
  }

  async function deleteRule(rule: EditorRule): Promise<void> {
    saveError = null;
    try {
      if (rule.kind === "tag") {
        await adapters.deleteTagRule(rule.id);
      } else {
        await adapters.deleteSystemRule(rule.id);
      }
      rules = rules.filter((row) => !(row.kind === rule.kind && row.id === rule.id));
    } catch (error) {
      saveError = ROUTING_EDITOR_STRINGS.saveFailed;
      void error;
    }
  }

  function byPriority(a: EditorRule, b: EditorRule): number {
    return a.priority - b.priority;
  }

  // ---- Add new rule -------------------------------------------------------

  async function addRule(): Promise<void> {
    saveError = null;
    // Defaults match spec §2 default-policy table for the Sonnet
    // executor + Opus advisor + auto effort + match_type=keyword
    // (the most common starting point per the seeded rule table in
    // spec §3).
    const baseBody: RoutingRuleIn = {
      priority:
        props.kind === "tag"
          ? ROUTING_RULE_DEFAULT_PRIORITY_TAG
          : ROUTING_RULE_DEFAULT_PRIORITY_SYSTEM,
      enabled: true,
      match_type: ROUTING_MATCH_TYPE_KEYWORD,
      match_value: "",
      executor_model: EXECUTOR_MODEL_SONNET,
      advisor_model: ADVISOR_MODEL_OPUS,
      advisor_max_uses: ROUTING_RULE_DEFAULT_ADVISOR_MAX_USES,
      effort_level: EFFORT_LEVEL_AUTO,
      reason: "",
    };
    try {
      if (props.kind === "tag") {
        const created = await adapters.createTagRule(props.tagId, baseBody);
        rules = [...rules, { ...created, kind: "tag" as const }].sort(byPriority);
        return;
      }
      const created = await adapters.createSystemRule(baseBody);
      rules = [...rules, { ...created, kind: "system" as const }].sort(byPriority);
    } catch (error) {
      saveError = ROUTING_EDITOR_STRINGS.saveFailed;
      void error;
    }
  }

  // ---- Drag-reorder -------------------------------------------------------

  function onDragStart(event: DragEvent, index: number): void {
    dragIndex = index;
    if (event.dataTransfer !== null) {
      event.dataTransfer.effectAllowed = "move";
      // Some browsers refuse to begin a drag without setData payload.
      event.dataTransfer.setData("text/plain", `${index}`);
    }
  }

  function onDragOver(event: DragEvent): void {
    event.preventDefault();
    if (event.dataTransfer !== null) {
      event.dataTransfer.dropEffect = "move";
    }
  }

  async function onDrop(event: DragEvent, targetIndex: number): Promise<void> {
    event.preventDefault();
    if (dragIndex === null || dragIndex === targetIndex) {
      dragIndex = null;
      return;
    }
    const reordered = reorderArray(rules, dragIndex, targetIndex);
    dragIndex = null;
    // Optimistic UI: paint the new order, then PATCH the priorities.
    // On failure we re-fetch to recover the canonical order.
    rules = reordered;
    await persistOrder(reordered);
  }

  function reorderArray<T>(items: readonly T[], from: number, to: number): T[] {
    const next = [...items];
    const [removed] = next.splice(from, 1);
    next.splice(to, 0, removed);
    return next;
  }

  async function persistOrder(ordered: EditorRule[]): Promise<void> {
    saveError = null;
    try {
      if (props.kind === "tag") {
        const ids = ordered.map((row) => row.id);
        const refreshed = await adapters.reorderTagRules(props.tagId, ids);
        rules = refreshed.map((row) => ({ ...row, kind: "tag" as const }));
        return;
      }
      // System rules: PATCH each with a sparse priority. Stride 10
      // matches the spec §3 seeded-rule layout (10/20/30/40/50/60).
      const stride = 10;
      const updated: EditorRule[] = [];
      for (let i = 0; i < ordered.length; i += 1) {
        const row = ordered[i];
        if (row.kind !== "system") continue;
        const nextPriority = (i + 1) * stride;
        if (row.priority === nextPriority) {
          updated.push(row);
          continue;
        }
        const body: RoutingRuleIn = {
          ...systemRuleToInput(row),
          priority: nextPriority,
        };
        const next = await adapters.updateSystemRule(row.id, body);
        updated.push({ ...next, kind: "system" as const });
      }
      rules = updated;
    } catch (error) {
      saveError = ROUTING_EDITOR_STRINGS.reorderFailed;
      // Re-fetch to recover the canonical server order.
      void loadFromApi();
      void error;
    }
  }

  // ---- Test dialog --------------------------------------------------------

  function openTestDialog(rule: EditorRule): void {
    testingRule = rule;
  }

  function closeTestDialog(): void {
    testingRule = null;
  }

  // ---- Display helpers ----------------------------------------------------

  const heading = $derived(
    props.kind === ROUTING_RULE_KIND_TAG
      ? ROUTING_EDITOR_STRINGS.headingTag
      : ROUTING_EDITOR_STRINGS.headingSystem,
  );

  const paneAriaLabel = $derived(
    props.kind === ROUTING_RULE_KIND_TAG
      ? ROUTING_EDITOR_STRINGS.paneAriaLabelTag
      : ROUTING_EDITOR_STRINGS.paneAriaLabelSystem,
  );

  const emptyCopy = $derived(
    props.kind === ROUTING_RULE_KIND_TAG
      ? ROUTING_EDITOR_STRINGS.emptyTag
      : ROUTING_EDITOR_STRINGS.emptySystem,
  );

  // Tests import :data:`ROUTING_RULE_KIND_TAG` etc. from
  // ``../../config`` directly — no re-exports needed off the
  // component surface.
</script>

<section
  class="routing-editor"
  data-testid="routing-editor"
  data-routing-rule-kind={props.kind}
  aria-label={paneAriaLabel}
>
  <header class="routing-editor__header">
    <h3 class="routing-editor__heading" data-testid="routing-editor-heading">
      {heading}
    </h3>
    <button
      type="button"
      class="routing-editor__add"
      data-testid="routing-editor-add"
      onclick={addRule}
    >
      {ROUTING_EDITOR_STRINGS.addRuleLabel}
    </button>
  </header>

  {#if saveError !== null}
    <p class="routing-editor__error" role="alert" data-testid="routing-editor-error">
      {saveError}
    </p>
  {/if}

  {#if loadState === "loading" || loadState === "idle"}
    <p class="routing-editor__placeholder" data-testid="routing-editor-loading">
      {ROUTING_EDITOR_STRINGS.loading}
    </p>
  {:else if loadState === "error"}
    <p class="routing-editor__placeholder" data-testid="routing-editor-load-failed">
      {ROUTING_EDITOR_STRINGS.loadFailed}
    </p>
  {:else if rules.length === 0}
    <p class="routing-editor__placeholder" data-testid="routing-editor-empty">
      {emptyCopy}
    </p>
  {:else}
    <ol class="routing-editor__list" data-testid="routing-editor-list" role="list">
      {#each rules as rule, index (`${rule.kind}-${rule.id}`)}
        <RuleRow
          {rule}
          overrideRate={rateFor(rule)}
          onPatch={(body: RoutingRuleIn) => void patchRule(rule, body)}
          onDuplicate={() => void duplicateRule(rule)}
          onDelete={() => void deleteRule(rule)}
          onTest={() => openTestDialog(rule)}
          onDragStart={(event: DragEvent) => onDragStart(event, index)}
          {onDragOver}
          onDrop={(event: DragEvent) => void onDrop(event, index)}
        />
      {/each}
    </ol>
  {/if}

  {#if testingRule !== null}
    <TestAgainstMessageDialog rule={testingRule} onClose={closeTestDialog} />
  {/if}
</section>

<style>
  .routing-editor {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 0.75rem;
  }
  .routing-editor__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .routing-editor__heading {
    margin: 0;
    font-size: 0.875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: rgb(var(--bearings-fg-muted));
  }
  .routing-editor__add {
    background: rgb(var(--bearings-accent));
    color: rgb(var(--bearings-surface-0));
    border: none;
    border-radius: 0.25rem;
    padding: 0.375rem 0.75rem;
    cursor: pointer;
    font: inherit;
    font-size: 0.8125rem;
  }
  .routing-editor__error {
    margin: 0;
    color: #f87171;
    font-size: 0.8125rem;
  }
  .routing-editor__list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin: 0;
    padding: 0;
  }
  .routing-editor__placeholder {
    margin: 0;
    color: rgb(var(--bearings-fg-muted));
    font-size: 0.8125rem;
  }
</style>
