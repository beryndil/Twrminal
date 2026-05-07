<script lang="ts">
  /**
   * AskUserQuestion modal — shown when the agent calls the built-in
   * ``AskUserQuestion`` tool to pause and wait for user input (Slice A4).
   *
   * Behavior anchor: ``docs/behavior/chat.md`` §"Approval modal".
   *
   * Three input shapes are supported:
   *
   * 1. **Structured** — ``{questions: [{header?, question, multiSelect?,
   *    options: [{label, description?}]}]}``. The current Claude Code
   *    AskUserQuestion shape. Each question renders with its header, the
   *    prompt, and a list of selectable options (radio when
   *    ``multiSelect`` is false/absent, checkbox when true). Submit is
   *    disabled until every question has at least one selection. The
   *    user's selections are encoded as labelled lines in the ``answer``
   *    string posted back to the broker — one line per question, the
   *    header (or trimmed question text) followed by the selected
   *    option labels joined by ``", "``.
   *
   * 2. **Legacy free-text** — ``{question: "..."}``. The original v1
   *    shape: render the prompt and a textarea, post the typed text.
   *
   * 3. **Unknown** — neither shape recognised. Pretty-print the raw JSON
   *    in a ``<pre>`` and fall back to the free-text textarea so the
   *    user can still answer something coherent rather than staring at
   *    a blob (read-only-fallback per the patch plan).
   *
   * In every case the wire shape submitted to the backend is the same:
   * ``POST /api/sessions/{id}/approvals/{request_id}`` with body
   * ``{approved: true, answer: <string>}``. The backend threads
   * ``answer`` back to the SDK callback as
   * ``PermissionResultAllow.updated_input`` — see
   * ``src/bearings/agent/approval.py``.
   */
  import { onMount } from "svelte";

  import { APPROVAL_STRINGS } from "../../config";
  import { postApproval } from "../../api/approvals";
  import type { PendingApproval } from "../../stores/conversation.svelte";

  interface Props {
    sessionId: string;
    approval: PendingApproval;
  }

  const { sessionId, approval }: Props = $props();

  /** One option in a structured question. */
  interface StructuredOption {
    label: string;
    description?: string;
  }

  /** One question in the structured ``questions[]`` shape. */
  interface StructuredQuestion {
    header?: string;
    question: string;
    multiSelect: boolean;
    options: StructuredOption[];
  }

  /** Discriminated parse result — drives the render branch. */
  type ParsedInput =
    | { kind: "structured"; questions: StructuredQuestion[] }
    | { kind: "legacy"; question: string }
    | { kind: "unknown"; pretty: string };

  /** Best-effort string getter — undefined when not a non-empty string. */
  function readString(source: Record<string, unknown>, key: string): string | undefined {
    const value = source[key];
    return typeof value === "string" && value.length > 0 ? value : undefined;
  }

  /** Coerce an unknown into a {@link StructuredOption} or null when malformed. */
  function parseOption(raw: unknown): StructuredOption | null {
    if (raw === null || typeof raw !== "object") return null;
    const obj = raw as Record<string, unknown>;
    const label = readString(obj, "label");
    if (label === undefined) return null;
    const description = readString(obj, "description");
    return description !== undefined ? { label, description } : { label };
  }

  /** Coerce an unknown into a {@link StructuredQuestion} or null when malformed. */
  function parseQuestionEntry(raw: unknown): StructuredQuestion | null {
    if (raw === null || typeof raw !== "object") return null;
    const obj = raw as Record<string, unknown>;
    const question = readString(obj, "question");
    if (question === undefined) return null;
    const optionsRaw = obj["options"];
    if (!Array.isArray(optionsRaw)) return null;
    const options: StructuredOption[] = [];
    for (const entry of optionsRaw) {
      const parsed = parseOption(entry);
      if (parsed !== null) options.push(parsed);
    }
    if (options.length === 0) return null;
    const header = readString(obj, "header");
    const multiSelect = obj["multiSelect"] === true;
    return header !== undefined
      ? { header, question, multiSelect, options }
      : { question, multiSelect, options };
  }

  /**
   * Parse the ``tool_input_json`` payload into a {@link ParsedInput}.
   *
   * Order matters: the structured shape is checked first (because a
   * payload like ``{question: "...", questions: [...]}`` would
   * spuriously satisfy the legacy branch otherwise).
   */
  function parseInput(raw: string): ParsedInput {
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return { kind: "unknown", pretty: raw };
    }
    if (parsed === null || typeof parsed !== "object") {
      return { kind: "unknown", pretty: raw };
    }
    const obj = parsed as Record<string, unknown>;
    const questionsRaw = obj["questions"];
    if (Array.isArray(questionsRaw) && questionsRaw.length > 0) {
      const questions: StructuredQuestion[] = [];
      for (const entry of questionsRaw) {
        const q = parseQuestionEntry(entry);
        if (q !== null) questions.push(q);
      }
      if (questions.length > 0) return { kind: "structured", questions };
    }
    const legacyQuestion = readString(obj, "question");
    if (legacyQuestion !== undefined) {
      return { kind: "legacy", question: legacyQuestion };
    }
    let pretty: string;
    try {
      pretty = JSON.stringify(parsed, null, 2);
    } catch {
      pretty = raw;
    }
    return { kind: "unknown", pretty };
  }

  const parsed = $derived(parseInput(approval.toolInputJson));

  /**
   * Per-question selection state for the structured branch. Index in the
   * outer array matches the parsed ``questions`` array; each inner array
   * holds the labels of options the user has picked for that question.
   *
   * Re-initialised whenever the parsed shape changes so a swapped
   * approval (rare, but possible across modal re-mounts) never inherits
   * stale picks from a different question set.
   */
  let selections = $state<string[][]>([]);

  $effect(() => {
    selections = parsed.kind === "structured" ? parsed.questions.map(() => []) : [];
  });

  /** Free-text answer for legacy + unknown branches. */
  let freeText = $state("");
  let submitting = $state(false);
  let cancelling = $state(false);
  let error = $state<string | null>(null);

  let firstFocusEl: HTMLElement | null = $state(null);

  onMount(() => {
    firstFocusEl?.focus();
  });

  /** Toggle the radio (single-select) selection at ``questionIdx``. */
  function selectSingle(questionIdx: number, label: string): void {
    const next = selections.slice();
    next[questionIdx] = [label];
    selections = next;
  }

  /** Toggle the checkbox (multi-select) selection at ``questionIdx``. */
  function toggleMulti(questionIdx: number, label: string): void {
    const current = selections[questionIdx] ?? [];
    const next = selections.slice();
    next[questionIdx] = current.includes(label)
      ? current.filter((entry) => entry !== label)
      : [...current, label];
    selections = next;
  }

  /**
   * True when every question in the structured branch has ≥1 selection.
   * Used to gate the submit button.
   */
  const structuredAnswered = $derived(
    parsed.kind === "structured" &&
      selections.length === parsed.questions.length &&
      selections.every((picks) => picks.length > 0),
  );

  /**
   * True when the modal has enough input to submit on the current
   * branch. Structured: every question answered. Legacy/unknown:
   * non-empty trimmed text.
   */
  const canSubmit = $derived(
    parsed.kind === "structured" ? structuredAnswered : freeText.trim() !== "",
  );

  /**
   * Build the ``answer`` string sent to the broker. Structured input is
   * collapsed to one labelled line per question (header or trimmed
   * question prefix, then the picked option labels joined by ``", "``);
   * legacy/unknown input is the raw trimmed text.
   */
  function buildAnswer(): string {
    if (parsed.kind !== "structured") return freeText.trim();
    const lines: string[] = [];
    parsed.questions.forEach((question, idx) => {
      const picks = selections[idx] ?? [];
      const prefix = question.header ?? question.question;
      lines.push(`${prefix}: ${picks.join(", ")}`);
    });
    return lines.join("\n");
  }

  async function submit(): Promise<void> {
    if (submitting || cancelling || !canSubmit) return;
    submitting = true;
    error = null;
    try {
      await postApproval(sessionId, approval.requestId, true, buildAnswer());
      // Modal stays visible until the approval_resolved event arrives
      // via the WebSocket and clears pendingApproval in the store.
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      submitting = false;
    }
  }

  /**
   * Cancel — POSTs ``approved: false`` (no answer) so the SDK callback
   * resolves as a denial and the agent receives a final answer rather than
   * blocking the broker indefinitely. Mirrors ``ApprovalModal``'s Deny path.
   */
  async function cancel(): Promise<void> {
    if (submitting || cancelling) return;
    cancelling = true;
    error = null;
    try {
      await postApproval(sessionId, approval.requestId, false);
      // Modal stays visible until the approval_resolved event arrives.
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      cancelling = false;
    }
  }

  /**
   * Enter (without shift) submits on the legacy/unknown free-text
   * branches. Structured branch ignores Enter so a stray keypress on a
   * radio doesn't accidentally submit before the user has read the
   * other questions.
   */
  function handleFreeTextKeydown(event: KeyboardEvent): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  }
</script>

<!-- Backdrop -->
<div
  class="ask-modal__backdrop fixed inset-0 z-40 flex items-center justify-center bg-black/50"
  aria-modal="true"
  role="dialog"
  aria-label={APPROVAL_STRINGS.askDialogAriaLabel}
  data-testid="ask-user-question-modal"
>
  <div
    class="ask-modal__panel relative flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-lg bg-surface-1 shadow-xl"
  >
    <!-- Header -->
    <div class="flex items-center border-b border-border px-4 py-3">
      <h2 class="text-sm font-semibold text-fg-strong" data-testid="ask-modal-title">
        {APPROVAL_STRINGS.askDialogTitle}
      </h2>
    </div>

    <!-- Body -->
    <div class="flex-1 overflow-y-auto px-4 py-3 text-sm">
      {#if parsed.kind === "structured"}
        <ol class="ask-modal__questions flex flex-col gap-5" data-testid="ask-modal-structured">
          {#each parsed.questions as question, qIdx (qIdx)}
            <li class="ask-modal__question flex flex-col gap-2">
              {#if question.header !== undefined}
                <h3
                  class="text-xs font-semibold uppercase tracking-wide text-fg-muted"
                  data-testid="ask-modal-question-header"
                >
                  {question.header}
                </h3>
              {/if}
              <p class="text-fg-strong" data-testid="ask-modal-question-prompt">
                {question.question}
              </p>
              <p class="text-xs text-fg-muted" data-testid="ask-modal-select-hint">
                {question.multiSelect
                  ? APPROVAL_STRINGS.multiSelectHint
                  : APPROVAL_STRINGS.singleSelectHint}
              </p>
              <ul class="flex flex-col gap-1.5">
                {#each question.options as option, oIdx (oIdx)}
                  {@const checked = (selections[qIdx] ?? []).includes(option.label)}
                  <li>
                    <label
                      class="flex cursor-pointer items-start gap-2 rounded border border-border bg-surface-2 px-3 py-2 hover:bg-surface-3"
                      data-testid="ask-modal-option"
                    >
                      {#if question.multiSelect}
                        <input
                          type="checkbox"
                          class="mt-1"
                          name={`q${qIdx}`}
                          value={option.label}
                          {checked}
                          disabled={submitting}
                          onchange={() => toggleMulti(qIdx, option.label)}
                          data-testid="ask-modal-checkbox"
                        />
                      {:else}
                        <input
                          type="radio"
                          class="mt-1"
                          name={`q${qIdx}`}
                          value={option.label}
                          {checked}
                          disabled={submitting}
                          onchange={() => selectSingle(qIdx, option.label)}
                          data-testid="ask-modal-radio"
                        />
                      {/if}
                      <span class="flex flex-col gap-0.5">
                        <span class="font-medium text-fg-strong">{option.label}</span>
                        {#if option.description !== undefined}
                          <span class="text-xs text-fg-muted">{option.description}</span>
                        {/if}
                      </span>
                    </label>
                  </li>
                {/each}
              </ul>
            </li>
          {/each}
        </ol>
      {:else if parsed.kind === "legacy"}
        <p class="text-fg-strong" data-testid="ask-modal-question">{parsed.question}</p>
        <div class="mt-3">
          <label class="block font-medium text-fg-muted" for="ask-answer">
            {APPROVAL_STRINGS.answerLabel}
          </label>
          <textarea
            id="ask-answer"
            class="mt-1 w-full rounded border border-border bg-surface-2 px-3 py-2 text-sm text-fg-strong placeholder:text-fg-muted focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
            rows={3}
            placeholder={APPROVAL_STRINGS.answerPlaceholder}
            disabled={submitting}
            bind:value={freeText}
            bind:this={firstFocusEl}
            onkeydown={handleFreeTextKeydown}
            data-testid="ask-modal-answer"
          ></textarea>
        </div>
      {:else}
        <p class="text-fg-muted" data-testid="ask-modal-unknown-notice">
          {APPROVAL_STRINGS.unknownShapeNotice}
        </p>
        <pre
          class="mt-2 max-h-48 overflow-auto rounded border border-border bg-surface-2 p-2 text-xs text-fg-strong"
          data-testid="ask-modal-unknown-pretty">{parsed.pretty}</pre>
        <div class="mt-3">
          <label class="block font-medium text-fg-muted" for="ask-answer">
            {APPROVAL_STRINGS.answerLabel}
          </label>
          <textarea
            id="ask-answer"
            class="mt-1 w-full rounded border border-border bg-surface-2 px-3 py-2 text-sm text-fg-strong placeholder:text-fg-muted focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
            rows={3}
            placeholder={APPROVAL_STRINGS.answerPlaceholder}
            disabled={submitting}
            bind:value={freeText}
            bind:this={firstFocusEl}
            onkeydown={handleFreeTextKeydown}
            data-testid="ask-modal-answer"
          ></textarea>
        </div>
      {/if}

      {#if error !== null}
        <p class="mt-2 text-xs text-red-400" data-testid="ask-modal-error">{error}</p>
      {:else if parsed.kind === "structured" && !structuredAnswered}
        <p class="mt-2 text-xs text-fg-muted" data-testid="ask-modal-validation">
          {APPROVAL_STRINGS.validationMissingSelection}
        </p>
      {/if}
    </div>

    <!-- Footer -->
    <div class="flex justify-end gap-2 border-t border-border px-4 py-3">
      <button
        type="button"
        class="rounded border border-border px-4 py-1.5 text-sm font-medium text-fg-strong hover:bg-surface-2 disabled:opacity-50"
        disabled={submitting || cancelling}
        data-testid="ask-modal-cancel"
        onclick={cancel}
      >
        {APPROVAL_STRINGS.cancelLabel}
      </button>
      <button
        type="button"
        class="rounded bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        disabled={submitting || cancelling || !canSubmit}
        data-testid="ask-modal-submit"
        onclick={submit}
      >
        {APPROVAL_STRINGS.submitLabel}
      </button>
    </div>
  </div>
</div>
