<script lang="ts">
  /**
   * New-session dialog (item 2.4 / spec §6).
   *
   * Composes:
   *
   * * the two-axis routing selector — executor (sonnet / haiku /
   *   opus) + advisor (none / opus + ``max_uses``) + effort (auto /
   *   low / medium / high / xhigh), per spec §3 alphabet;
   * * the reactive routing preview — every keystroke / tag change
   *   schedules a single :data:`ROUTING_PREVIEW_DEBOUNCE_MS` (300 ms)
   *   POST against ``/api/routing/preview``. Spec §6: "re-evaluates
   *   rules in real time (debounced ~300 ms)";
   * * QuotaBars (spec §4 + §6 + §8 + §10) reading
   *   ``/api/quota/current`` once on mount and again after each
   *   preview that carries a fresh ``quota_state``;
   * * RecostDialog (the downgrade banner with "Use <model> anyway"
   *   override per spec §4) rendered when
   *   ``preview.quota_downgrade_applied`` is true and the user has
   *   not already overridden.
   *
   * The component owns no stores — it is a self-contained dialog.
   * The parent (``+layout.svelte`` / a future
   * ``NewSessionDialog.svelte`` shell) supplies tags + working dir
   * + the ``onSubmit`` callback that wires the actual session
   * creation. Per the master-item carve-out, the create endpoint
   * (``POST /api/sessions``) lands in a later item; this component
   * exposes a sufficient submission payload (``ManualRouting``) for
   * that item to consume.
   *
   * Manual override semantics (spec §6):
   *
   * * Touching any of the executor / advisor / effort selectors
   *   flips the routed-from line to "Manual override" and STOPS the
   *   preview from overwriting selector values. The preview itself
   *   keeps running so the downgrade banner remains correct.
   * * Clicking "Use <model> anyway" restores the executor (and re-
   *   enables the advisor when applicable), records the override,
   *   and sets the routed-from line to "Manual override".
   */
  import { onMount, untrack } from "svelte";

  import {
    ADVISOR_MODEL_NONE,
    ADVISOR_MODEL_OPUS,
    DEFAULT_ADVISOR_MAX_USES_HAIKU,
    DEFAULT_ADVISOR_MAX_USES_SONNET,
    EFFORT_LEVEL_AUTO,
    EXECUTOR_MODEL_HAIKU,
    EXECUTOR_MODEL_OPUS,
    EXECUTOR_MODEL_SONNET,
    KNOWN_ADVISOR_MODELS,
    KNOWN_EFFORT_LEVELS,
    KNOWN_EXECUTOR_MODELS,
    NEW_SESSION_STRINGS,
    ROUTING_PREVIEW_DEBOUNCE_MS,
    ROUTING_SOURCE_QUOTA_DOWNGRADE,
    SESSION_KIND_CHAT,
    SESSION_KIND_CHECKLIST,
    type AdvisorModelChoice,
    type EffortLevel,
    type ExecutorModel,
    type SessionKind,
  } from "../../config";
  import { previewRouting as previewRoutingDefault, type RoutingPreview } from "../../api/routing";
  import { getCurrentQuota as getCurrentQuotaDefault } from "../../api/quota";
  import { listTemplates, type TemplateOut } from "../../api/templates";
  import { ApiError } from "../../api/client";
  import QuotaBars, { type QuotaBarsSnapshot } from "./QuotaBars.svelte";
  import RoutingPreviewLine, { type RoutingPreviewState } from "./RoutingPreview.svelte";
  import RecostDialog from "./RecostDialog.svelte";

  /**
   * Manual routing state captured by the selectors. The ``override``
   * flag flips ``true`` once the user has touched any of the three
   * axes (or used the "Use anyway" override), per spec §6.
   */
  export interface ManualRouting {
    executor: ExecutorModel;
    advisor: AdvisorModelChoice;
    advisorMaxUses: number;
    effort: EffortLevel;
    override: boolean;
  }

  /**
   * Submission payload — the parent that lives outside this dialog
   * is responsible for the actual ``POST /api/sessions`` call (a
   * later item). The shape carries everything the create endpoint
   * needs from this dialog.
   *
   * ``kind`` mirrors the segmented-control selection: ``"chat"`` for a
   * normal agent session, ``"checklist"`` for a structured-list session.
   * When ``kind`` is ``"checklist"``, ``routing`` carries default values
   * (the checklist never runs an agent) and ``firstMessage`` is ``""``.
   */
  export interface NewSessionSubmission {
    kind: SessionKind;
    tagIds: number[];
    workingDir: string;
    firstMessage: string;
    routing: ManualRouting;
  }

  interface Props {
    /** Tag ids the parent has resolved for the session. */
    tagIds?: readonly number[];
    /** Working directory path. */
    workingDir?: string;
    /** Submit handler — fires on Start Session. */
    onSubmit?: (payload: NewSessionSubmission) => void;
    /** Cancel handler — fires on Cancel button. */
    onCancel?: () => void;
    /**
     * Injected api fns / debounce override so unit tests can
     * substitute fakes without monkey-patching the module cache —
     * mirrors the prop-injection pattern in
     * :file:`SessionList.svelte`. ``debounceMs`` is exposed
     * primarily for tests that want a 0 ms passthrough; production
     * callers omit it and pick up the spec-mandated 300 ms.
     */
    previewRouting?: typeof previewRoutingDefault;
    getCurrentQuota?: typeof getCurrentQuotaDefault;
    debounceMs?: number;
    /**
     * Preselected executor model injected by the host (item 3.2).
     * Used to auto-fill from ``/api/preferences``; falls back to
     * ``EXECUTOR_MODEL_SONNET`` when omitted.  The user can still
     * override via the executor selector.
     */
    initialExecutor?: ExecutorModel;
  }

  const {
    tagIds = [],
    workingDir = "",
    onSubmit = () => {},
    onCancel = () => {},
    previewRouting = previewRoutingDefault,
    getCurrentQuota = getCurrentQuotaDefault,
    debounceMs = ROUTING_PREVIEW_DEBOUNCE_MS,
    initialExecutor = EXECUTOR_MODEL_SONNET,
  }: Props = $props();

  // ---- Template picker state ---------------------------------------------

  let templates = $state<TemplateOut[]>([]);
  let selectedTemplateId = $state<number | null>(null);

  async function loadTemplates(): Promise<void> {
    try {
      templates = await listTemplates();
    } catch {
      // Non-fatal — picker just stays empty.
      templates = [];
    }
  }

  function onTemplateChange(event: Event): void {
    const target = event.currentTarget as HTMLSelectElement;
    const parsed = Number.parseInt(target.value, 10);
    if (Number.isNaN(parsed)) {
      selectedTemplateId = null;
      return;
    }
    selectedTemplateId = parsed;
    const tpl = templates.find((t) => t.id === parsed);
    if (tpl === undefined) return;
    // Pre-fill routing axes from the template; mark manual override so the
    // routing preview does not overwrite the user's explicit template choice.
    if (isKnownExecutor(tpl.model)) {
      executor = tpl.model;
    }
    if (tpl.advisor_model === ADVISOR_MODEL_OPUS) {
      advisor = ADVISOR_MODEL_OPUS;
      advisorMaxUses = tpl.advisor_max_uses;
    } else {
      advisor = ADVISOR_MODEL_NONE;
    }
    if (isKnownEffort(tpl.effort_level)) {
      effort = tpl.effort_level;
    }
    manualOverride = true;
  }

  // ---- Kind toggle -------------------------------------------------------

  /**
   * Whether the user is creating a chat or checklist session. Defaults to
   * ``"chat"``; the segmented control at the top of the form switches it.
   * When ``"checklist"``, the routing fieldset, quota bars, and first-message
   * textarea are hidden (checklists run no agent and burn no tokens).
   */
  let kind = $state<SessionKind>(SESSION_KIND_CHAT);

  // ---- Form state --------------------------------------------------------

  let firstMessage = $state("");

  // Routing axes — defaulted per spec §1 / §2 (Sonnet executor, Opus
  // advisor, max=5, auto effort) and updated by the preview unless the
  // user has overridden.
  // untrack: we only want the initial prop value as a seed; reactive
  // updates to initialExecutor after mount should NOT re-set executor
  // (the routing preview owns executor once the form is live).
  let executor = $state<ExecutorModel>(untrack(() => initialExecutor));
  let advisor = $state<AdvisorModelChoice>(ADVISOR_MODEL_OPUS);
  let advisorMaxUses = $state<number>(DEFAULT_ADVISOR_MAX_USES_SONNET);
  let effort = $state<EffortLevel>(EFFORT_LEVEL_AUTO);
  let manualOverride = $state(false);

  // ---- Async state --------------------------------------------------------

  let preview = $state<RoutingPreview | null>(null);
  let previewLoading = $state(false);
  let previewError = $state(false);
  let quota = $state<QuotaBarsSnapshot | null>(null);

  // ---- Debounce wiring ----------------------------------------------------

  let debounceHandle: ReturnType<typeof setTimeout> | null = null;
  let activeAbort: AbortController | null = null;

  /**
   * Schedule a single preview fetch ``debounceMs`` from now, cancelling
   * any pending timer + in-flight request. The reset-on-input pattern
   * is what produces the spec §6 "exactly one POST per ~300 ms quiet
   * period" behavior.
   */
  function schedulePreview(): void {
    if (debounceHandle !== null) {
      clearTimeout(debounceHandle);
    }
    if (activeAbort !== null) {
      activeAbort.abort();
      activeAbort = null;
    }
    previewLoading = true;
    previewError = false;
    const delay = debounceMs;
    debounceHandle = setTimeout(() => {
      debounceHandle = null;
      void runPreview();
    }, delay);
  }

  async function runPreview(): Promise<void> {
    const controller = new AbortController();
    activeAbort = controller;
    try {
      const result = await previewRouting(
        { tags: [...tagIds], message: firstMessage },
        { signal: controller.signal },
      );
      // The user may have toggled the override while the request was
      // in flight; capture the result for the banner / quota bars
      // either way, but only project executor / advisor / effort onto
      // the selectors when no override is active.
      preview = result;
      previewLoading = false;
      previewError = false;
      if (!manualOverride) {
        applyPreviewToSelectors(result);
      }
      // Refresh the in-dialog quota bars from the preview's
      // ``quota_state`` — saves a redundant /api/quota/current poll
      // when the preview already carries the same data.
      const overall = result.quota_state["overall_used_pct"];
      const sonnet = result.quota_state["sonnet_used_pct"];
      if (overall !== undefined || sonnet !== undefined) {
        quota = {
          overallUsedPct: overall ?? quota?.overallUsedPct ?? null,
          sonnetUsedPct: sonnet ?? quota?.sonnetUsedPct ?? null,
          overallResetsAt: quota?.overallResetsAt ?? null,
          sonnetResetsAt: quota?.sonnetResetsAt ?? null,
        };
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      previewLoading = false;
      previewError = true;
    } finally {
      if (activeAbort === controller) {
        activeAbort = null;
      }
    }
  }

  function applyPreviewToSelectors(result: RoutingPreview): void {
    if (isKnownExecutor(result.executor)) {
      executor = result.executor;
    }
    advisor = result.advisor === ADVISOR_MODEL_OPUS ? ADVISOR_MODEL_OPUS : ADVISOR_MODEL_NONE;
    advisorMaxUses = result.advisor_max_uses;
    if (isKnownEffort(result.effort)) {
      effort = result.effort;
    }
  }

  function isKnownExecutor(value: string): value is ExecutorModel {
    return (KNOWN_EXECUTOR_MODELS as readonly string[]).includes(value);
  }

  function isKnownEffort(value: string): value is EffortLevel {
    return (KNOWN_EFFORT_LEVELS as readonly string[]).includes(value);
  }

  // ---- Reactive triggers --------------------------------------------------

  // Re-schedule when the first message OR the tag list changes (spec §6
  // "Typing in the first-message field re-evaluates rules in real time
  // … Changing tags re-evaluates rules"). ``untrack`` around the
  // schedule call so the effect itself doesn't re-subscribe to anything
  // beyond the two listed inputs.
  // Checklist sessions run no agent — skip the preview entirely.
  $effect(() => {
    // Subscribe to both inputs.
    void firstMessage;
    void tagIds.length;
    for (const id of tagIds) {
      void id;
    }
    untrack(() => {
      if (kind === SESSION_KIND_CHAT) {
        schedulePreview();
      }
    });
  });

  onMount(() => {
    // Initial quota fetch — falls back gracefully on every error path
    // (404 = no snapshot yet; 503 = no poller; 502 = upstream blip).
    void hydrateQuotaOnMount();
    // Template picker — non-fatal; picker shows empty when unavailable.
    void loadTemplates();
    return () => {
      if (debounceHandle !== null) {
        clearTimeout(debounceHandle);
      }
      if (activeAbort !== null) {
        activeAbort.abort();
      }
    };
  });

  async function hydrateQuotaOnMount(): Promise<void> {
    try {
      const snapshot = await getCurrentQuota();
      quota = {
        overallUsedPct: snapshot.overall_used_pct,
        sonnetUsedPct: snapshot.sonnet_used_pct,
        overallResetsAt: snapshot.overall_resets_at,
        sonnetResetsAt: snapshot.sonnet_resets_at,
      };
    } catch (error) {
      // 404 / 502 / 503 → leave quota null; the preview's
      // ``quota_state`` will hydrate the bars on the first preview.
      if (!(error instanceof ApiError)) {
        // Re-raise unexpected errors so a real bug isn't swallowed.
        throw error;
      }
    }
  }

  // ---- Selector handlers (mark as overridden) ----------------------------

  function onExecutorChange(event: Event): void {
    const target = event.currentTarget as HTMLSelectElement;
    if (isKnownExecutor(target.value)) {
      executor = target.value;
      manualOverride = true;
      // Spec §2 — Opus executor disables the advisor (advisor row
      // collapses to a hint). Match that semantics on manual change.
      if (executor === EXECUTOR_MODEL_OPUS) {
        advisor = ADVISOR_MODEL_NONE;
      } else if (advisor === ADVISOR_MODEL_NONE) {
        advisor = ADVISOR_MODEL_OPUS;
        advisorMaxUses =
          executor === EXECUTOR_MODEL_HAIKU
            ? DEFAULT_ADVISOR_MAX_USES_HAIKU
            : DEFAULT_ADVISOR_MAX_USES_SONNET;
      }
    }
  }

  function onAdvisorChange(event: Event): void {
    const target = event.currentTarget as HTMLSelectElement;
    if ((KNOWN_ADVISOR_MODELS as readonly string[]).includes(target.value)) {
      advisor = target.value as AdvisorModelChoice;
      manualOverride = true;
    }
  }

  function onAdvisorMaxUsesChange(event: Event): void {
    const target = event.currentTarget as HTMLInputElement;
    const parsed = Number.parseInt(target.value, 10);
    if (!Number.isNaN(parsed) && parsed >= 0) {
      advisorMaxUses = parsed;
      manualOverride = true;
    }
  }

  function onEffortChange(event: Event): void {
    const target = event.currentTarget as HTMLSelectElement;
    if (isKnownEffort(target.value)) {
      effort = target.value;
      manualOverride = true;
    }
  }

  function onFirstMessageInput(event: Event): void {
    const target = event.currentTarget as HTMLTextAreaElement;
    firstMessage = target.value;
  }

  // ---- Downgrade banner --------------------------------------------------

  /**
   * Returns the banner inputs when the latest preview applied a
   * quota-driven downgrade AND the user hasn't already overridden.
   * Spec §4: Opus → Sonnet on overall ≥ 80 %; Sonnet → Haiku on
   * sonnet ≥ 80 %.
   */
  function downgradeBanner(): {
    downgradedTo: string;
    originalModel: ExecutorModel;
    bucket: "overall" | "sonnet";
    usedPct: number;
  } | null {
    if (preview === null || manualOverride) return null;
    if (!preview.quota_downgrade_applied) return null;
    if (preview.source !== ROUTING_SOURCE_QUOTA_DOWNGRADE) return null;
    // Spec §4 ladder: overall trips first, then sonnet.
    const overall = preview.quota_state["overall_used_pct"] ?? 0;
    const sonnet = preview.quota_state["sonnet_used_pct"] ?? 0;
    if (preview.executor === EXECUTOR_MODEL_HAIKU) {
      return {
        downgradedTo: EXECUTOR_MODEL_HAIKU,
        originalModel: EXECUTOR_MODEL_SONNET,
        bucket: "sonnet",
        usedPct: sonnet,
      };
    }
    return {
      downgradedTo: EXECUTOR_MODEL_SONNET,
      originalModel: EXECUTOR_MODEL_OPUS,
      bucket: "overall",
      usedPct: overall,
    };
  }

  function onUseAnyway(): void {
    const banner = downgradeBanner();
    if (banner === null) return;
    executor = banner.originalModel;
    if (banner.originalModel === EXECUTOR_MODEL_OPUS) {
      advisor = ADVISOR_MODEL_NONE;
    } else if (advisor === ADVISOR_MODEL_NONE) {
      advisor = ADVISOR_MODEL_OPUS;
    }
    manualOverride = true;
  }

  function onSubmitClick(): void {
    onSubmit({
      kind,
      tagIds: [...tagIds],
      workingDir,
      firstMessage,
      routing: {
        executor,
        advisor,
        advisorMaxUses,
        effort,
        override: manualOverride,
      },
    });
  }

  // ---- Derived UI state --------------------------------------------------

  const previewState = $derived<RoutingPreviewState>(buildPreviewState());

  function buildPreviewState(): RoutingPreviewState {
    if (manualOverride) return { kind: "manual" };
    if (previewError) return { kind: "error" };
    if (preview === null) return { kind: "loading" };
    if (previewLoading) return { kind: "loading" };
    return { kind: "ready", reason: preview.reason };
  }

  const banner = $derived(downgradeBanner());

  // Spec §2 — when the executor is Opus, the advisor row collapses
  // to the hint "Opus is the executor — advisor not needed."
  const advisorHidden = $derived(executor === EXECUTOR_MODEL_OPUS);
</script>

<form
  class="new-session-form"
  data-testid="new-session-form"
  aria-label={NEW_SESSION_STRINGS.dialogAriaLabel}
  onsubmit={(event) => {
    event.preventDefault();
    onSubmitClick();
  }}
>
  <h2 class="new-session-form__title">{NEW_SESSION_STRINGS.dialogTitle}</h2>

  <div
    class="new-session-form__kind-toggle"
    role="group"
    aria-label={NEW_SESSION_STRINGS.kindToggleAriaLabel}
  >
    <button
      type="button"
      class="new-session-form__kind-btn"
      class:new-session-form__kind-btn--active={kind === SESSION_KIND_CHAT}
      data-testid="new-session-kind-chat"
      onclick={() => {
        kind = SESSION_KIND_CHAT;
      }}
    >
      {NEW_SESSION_STRINGS.kindChatLabel}
    </button>
    <button
      type="button"
      class="new-session-form__kind-btn"
      class:new-session-form__kind-btn--active={kind === SESSION_KIND_CHECKLIST}
      data-testid="new-session-kind-checklist"
      onclick={() => {
        kind = SESSION_KIND_CHECKLIST;
      }}
    >
      {NEW_SESSION_STRINGS.kindChecklistLabel}
    </button>
  </div>

  {#if kind === SESSION_KIND_CHAT}
    {#if templates.length > 0}
      <div class="new-session-form__row">
        <label for="new-session-template">Template</label>
        <select
          id="new-session-template"
          data-testid="new-session-template"
          value={selectedTemplateId ?? ""}
          onchange={onTemplateChange}
        >
          <option value="">— no template —</option>
          {#each templates as tpl (tpl.id)}
            <option value={tpl.id}>{tpl.name}</option>
          {/each}
        </select>
      </div>
    {/if}

    <fieldset class="new-session-form__routing">
      <legend class="new-session-form__routing-heading">
        {NEW_SESSION_STRINGS.routingHeading}
      </legend>

      <div class="new-session-form__row">
        <label for="new-session-executor">{NEW_SESSION_STRINGS.executorLabel}</label>
        <select
          id="new-session-executor"
          data-testid="new-session-executor"
          value={executor}
          onchange={onExecutorChange}
        >
          {#each KNOWN_EXECUTOR_MODELS as option (option)}
            <option value={option}>{NEW_SESSION_STRINGS.executorLabels[option]}</option>
          {/each}
        </select>
      </div>

      {#if advisorHidden}
        <p class="new-session-form__advisor-hint" data-testid="new-session-advisor-hint">
          {NEW_SESSION_STRINGS.advisorOpusExecutorHint}
        </p>
      {:else}
        <div class="new-session-form__row">
          <label for="new-session-advisor">{NEW_SESSION_STRINGS.advisorLabel}</label>
          <select
            id="new-session-advisor"
            data-testid="new-session-advisor"
            value={advisor}
            onchange={onAdvisorChange}
          >
            {#each KNOWN_ADVISOR_MODELS as option (option)}
              <option value={option}>{NEW_SESSION_STRINGS.advisorLabels[option]}</option>
            {/each}
          </select>
          <label class="new-session-form__inline" for="new-session-advisor-max">
            {NEW_SESSION_STRINGS.advisorMaxUsesLabel}
          </label>
          <input
            id="new-session-advisor-max"
            data-testid="new-session-advisor-max"
            type="number"
            min="0"
            max="99"
            value={advisorMaxUses}
            disabled={advisor === ADVISOR_MODEL_NONE}
            onchange={onAdvisorMaxUsesChange}
          />
        </div>
      {/if}

      <div class="new-session-form__row">
        <label for="new-session-effort">{NEW_SESSION_STRINGS.effortLabel}</label>
        <select
          id="new-session-effort"
          data-testid="new-session-effort"
          value={effort}
          onchange={onEffortChange}
        >
          {#each KNOWN_EFFORT_LEVELS as option (option)}
            <option value={option}>{NEW_SESSION_STRINGS.effortLabels[option]}</option>
          {/each}
        </select>
      </div>

      <RoutingPreviewLine state={previewState} />
    </fieldset>

    <QuotaBars snapshot={quota} />

    {#if banner !== null}
      <RecostDialog
        downgradedTo={banner.downgradedTo}
        originalModel={banner.originalModel}
        bucket={banner.bucket}
        usedPct={banner.usedPct}
        {onUseAnyway}
      />
    {/if}

    <div class="new-session-form__row new-session-form__row--message">
      <label for="new-session-first-message">{NEW_SESSION_STRINGS.firstMessageLabel}</label>
      <textarea
        id="new-session-first-message"
        data-testid="new-session-first-message"
        rows="6"
        placeholder={NEW_SESSION_STRINGS.firstMessagePlaceholder}
        value={firstMessage}
        oninput={onFirstMessageInput}
      ></textarea>
    </div>
  {/if}

  <div class="new-session-form__actions">
    <button
      type="button"
      class="new-session-form__cancel"
      data-testid="new-session-cancel"
      onclick={onCancel}
    >
      {NEW_SESSION_STRINGS.cancelLabel}
    </button>
    <button type="submit" class="new-session-form__submit" data-testid="new-session-submit">
      {NEW_SESSION_STRINGS.submitLabel}
    </button>
  </div>
</form>

<style>
  .new-session-form {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 1rem;
    min-width: 30rem;
    max-width: 40rem;
    background: rgb(var(--bearings-surface-1));
    border-radius: 0.5rem;
    color: rgb(var(--bearings-fg));
  }
  .new-session-form__kind-toggle {
    display: flex;
    align-self: flex-start;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.375rem;
    overflow: hidden;
  }
  .new-session-form__kind-btn {
    padding: 0.3125rem 1rem;
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
    background: rgb(var(--bearings-surface-2));
    color: inherit;
    border: none;
    border-right: 1px solid rgb(var(--bearings-border));
  }
  .new-session-form__kind-btn:last-child {
    border-right: none;
  }
  .new-session-form__kind-btn--active {
    background: rgb(var(--bearings-accent));
    color: white;
  }
  .new-session-form__title {
    font-size: 1.125rem;
    font-weight: 600;
    margin: 0;
  }
  .new-session-form__routing {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.375rem;
    padding: 0.75rem;
  }
  .new-session-form__routing-heading {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: rgb(var(--bearings-fg-muted));
    padding: 0 0.25rem;
  }
  .new-session-form__row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
    font-size: 0.8125rem;
  }
  .new-session-form__row--message {
    flex-direction: column;
    align-items: stretch;
  }
  .new-session-form__row label {
    color: rgb(var(--bearings-fg-muted));
  }
  .new-session-form__inline {
    margin-left: 0.5rem;
  }
  .new-session-form__advisor-hint {
    font-size: 0.75rem;
    color: rgb(var(--bearings-fg-muted));
    margin: 0;
  }
  .new-session-form__row textarea,
  .new-session-form__row select,
  .new-session-form__row input {
    background: rgb(var(--bearings-surface-2));
    color: inherit;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.25rem 0.5rem;
    font: inherit;
  }
  .new-session-form__row textarea {
    resize: vertical;
    min-height: 6rem;
  }
  .new-session-form__actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
  }
  .new-session-form__actions button {
    border: 1px solid rgb(var(--bearings-border));
    background: rgb(var(--bearings-surface-2));
    color: inherit;
    border-radius: 0.25rem;
    padding: 0.375rem 0.75rem;
    cursor: pointer;
  }
  .new-session-form__actions button[type="submit"] {
    background: rgb(var(--bearings-accent));
    border-color: transparent;
    color: white;
  }
</style>
