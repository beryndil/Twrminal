<script lang="ts">
  import type { ApprovalRequestEvent } from '$lib/api';

  type Props = {
    request: ApprovalRequestEvent;
    connected: boolean;
    onRespond: (
      requestId: string,
      decision: 'allow' | 'deny',
      reason?: string,
      updatedInput?: Record<string, unknown>
    ) => boolean;
  };

  const { request, connected, onRespond }: Props = $props();

  // Shape the AskUserQuestion tool puts on the wire. Narrow to what
  // we actually render — the SDK may include extra fields (metadata,
  // annotations) that we pass through untouched on submit.
  type Option = { label: string; description: string; preview?: string };
  type Question = {
    question: string;
    header: string;
    options: Option[];
    multiSelect?: boolean;
  };

  // Defensive parse: the approval event's `input` is typed as
  // `Record<string, unknown>`. If a malformed payload ever reached the
  // modal (e.g. a protocol mismatch after a server upgrade) we want to
  // fall back to the generic JSON view rather than crash.
  const questions = $derived<Question[]>(
    Array.isArray((request.input as { questions?: unknown }).questions)
      ? ((request.input as { questions: Question[] }).questions)
      : []
  );

  // Selections per question, keyed by question text. Single-select =
  // one label; multi-select = set of labels. "Other" text is stored
  // separately and merged in at submit time so toggling options
  // doesn't wipe what the user typed.
  let selectedSingle = $state<Record<string, string>>({});
  let selectedMulti = $state<Record<string, Set<string>>>({});
  let otherText = $state<Record<string, string>>({});

  // Reactive readiness flag: the submit button is disabled until
  // every question has at least one answer (an option toggled on or
  // non-empty "Other" text). Matches the contract that every question
  // in the array is required.
  //
  // Why the length guard: `[].every(...)` is vacuously true, so a
  // malformed payload (no `questions` array at all) would otherwise
  // land on an enabled Submit that sends an empty-answer allow —
  // exactly the pre-fix behavior we're replacing.
  const allAnswered = $derived(
    questions.length > 0 &&
      questions.every((q) => {
        const other = (otherText[q.question] ?? '').trim();
        if (other) return true;
        if (q.multiSelect) return (selectedMulti[q.question]?.size ?? 0) > 0;
        return !!selectedSingle[q.question];
      })
  );

  // Set to the attempted decision while the response is in-flight so
  // the button text flips to "sending…" and a failed send rolls back
  // to the idle state. Mirrors ApprovalModal's pending pattern.
  let pending = $state<'allow' | 'deny' | null>(null);

  function toggleMulti(questionText: string, label: string): void {
    const current = selectedMulti[questionText] ?? new Set<string>();
    const next = new Set(current);
    if (next.has(label)) next.delete(label);
    else next.add(label);
    // Assign a fresh object so Svelte's fine-grained reactivity
    // picks up the change — mutating a nested Set in place doesn't
    // trigger a re-render on its own.
    selectedMulti = { ...selectedMulti, [questionText]: next };
  }

  function pickSingle(questionText: string, label: string): void {
    selectedSingle = { ...selectedSingle, [questionText]: label };
  }

  function buildAnswers(): Record<string, string> {
    const answers: Record<string, string> = {};
    for (const q of questions) {
      const other = (otherText[q.question] ?? '').trim();
      if (q.multiSelect) {
        const picks = Array.from(selectedMulti[q.question] ?? []);
        if (other) picks.push(other);
        answers[q.question] = picks.join(', ');
      } else {
        // Precedence: typed "Other" wins over an option click when
        // both are present. The typed text is an explicit signal the
        // user wanted a custom answer.
        answers[q.question] = other || selectedSingle[q.question] || '';
      }
    }
    return answers;
  }

  function submit(): void {
    if (pending !== null || !allAnswered) return;
    pending = 'allow';
    // Preserve the original input and append answers. The SDK
    // invokes the tool with this merged payload; the tool echoes
    // `answers` back to the agent as its result.
    const updatedInput = { ...(request.input as object), answers: buildAnswers() };
    const ok = onRespond(request.request_id, 'allow', undefined, updatedInput);
    if (!ok) pending = null;
  }

  function cancel(): void {
    if (pending !== null) return;
    pending = 'deny';
    const ok = onRespond(request.request_id, 'deny', 'user cancelled');
    if (!ok) pending = null;
  }

  // ESC must NOT resolve the gate — same invariant as ApprovalModal.
  // A dismissed question modal would otherwise send an empty-answer
  // allow or silently leave the SDK parked. Cancel is click-only.
  $effect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
      }
    }
    window.addEventListener('keydown', onKey, { capture: true });
    return () => window.removeEventListener('keydown', onKey, { capture: true });
  });
</script>

<div
  class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80
    backdrop-blur-sm"
  role="dialog"
  aria-modal="true"
  aria-labelledby="ask-title"
  data-testid="ask-user-question-modal"
>
  <div
    class="bg-slate-900 border border-sky-800 rounded-lg shadow-2xl w-full
      max-w-xl mx-4 max-h-[85vh] flex flex-col"
  >
    <header class="px-5 py-3 border-b border-slate-800 flex-shrink-0">
      <h2
        id="ask-title"
        class="text-sm font-medium text-sky-200 flex items-center gap-2"
      >
        <span
          class="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded
            bg-sky-900 text-sky-200"
        >
          question
        </span>
        The agent is asking for your input
      </h2>
    </header>

    <div class="px-5 py-4 overflow-y-auto flex flex-col gap-5">
      {#if questions.length === 0}
        <p class="text-sm text-amber-300" data-testid="ask-malformed">
          The agent sent a malformed AskUserQuestion payload. Cancel to deny
          the call.
        </p>
      {/if}

      {#each questions as q, qi (qi)}
        <fieldset class="flex flex-col gap-2">
          <legend class="flex items-center gap-2 mb-1">
            <span
              class="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded
                bg-slate-800 text-slate-300"
            >
              {q.header}
            </span>
            {#if q.multiSelect}
              <span class="text-[10px] uppercase tracking-wider text-slate-500">
                pick any
              </span>
            {/if}
          </legend>
          <p class="text-sm text-slate-200">{q.question}</p>
          <div class="flex flex-col gap-1.5" data-testid="ask-options-{qi}">
            {#each q.options as opt, oi (oi)}
              {@const checked = q.multiSelect
                ? (selectedMulti[q.question]?.has(opt.label) ?? false)
                : selectedSingle[q.question] === opt.label}
              <label
                class="flex items-start gap-2 px-3 py-2 rounded border cursor-pointer
                  transition-colors {checked
                  ? 'border-sky-700 bg-sky-950/40'
                  : 'border-slate-800 bg-slate-950 hover:border-slate-700'}"
              >
                <input
                  type={q.multiSelect ? 'checkbox' : 'radio'}
                  name="q-{qi}"
                  value={opt.label}
                  checked={checked}
                  disabled={pending !== null}
                  onchange={() =>
                    q.multiSelect
                      ? toggleMulti(q.question, opt.label)
                      : pickSingle(q.question, opt.label)}
                  class="mt-0.5 accent-sky-500"
                  data-testid="ask-option-{qi}-{oi}"
                />
                <span class="flex-1 text-xs">
                  <span class="text-slate-200">{opt.label}</span>
                  {#if opt.description}
                    <span class="block text-slate-400 mt-0.5">
                      {opt.description}
                    </span>
                  {/if}
                </span>
              </label>
            {/each}
            <label class="flex flex-col gap-1 mt-1">
              <span class="text-[10px] uppercase tracking-wider text-slate-500">
                Other
              </span>
              <input
                type="text"
                bind:value={otherText[q.question]}
                disabled={pending !== null}
                placeholder="Type a custom answer"
                class="px-2 py-1.5 text-xs rounded bg-slate-950 border
                  border-slate-800 text-slate-200 placeholder:text-slate-600
                  focus:outline-none focus:border-sky-700"
                data-testid="ask-other-{qi}"
              />
            </label>
          </div>
        </fieldset>
      {/each}

      {#if !connected}
        <p class="text-xs text-amber-300">
          Reconnecting — your response will send once the socket is back.
        </p>
      {/if}
    </div>

    <footer
      class="px-5 py-3 border-t border-slate-800 flex justify-end gap-2
        flex-shrink-0"
    >
      <button
        type="button"
        class="px-3 py-1.5 text-xs rounded bg-slate-800 text-slate-200
          hover:bg-slate-700 disabled:opacity-50"
        onclick={cancel}
        disabled={pending !== null || !connected}
        data-testid="ask-cancel"
      >
        {pending === 'deny' ? 'Cancelling…' : 'Cancel'}
      </button>
      <button
        type="button"
        class="px-3 py-1.5 text-xs rounded bg-emerald-600 text-white
          hover:bg-emerald-500 disabled:opacity-50"
        onclick={submit}
        disabled={pending !== null || !connected || !allAnswered}
        data-testid="ask-submit"
      >
        {pending === 'allow' ? 'Sending…' : 'Submit'}
      </button>
    </footer>
  </div>
</div>
