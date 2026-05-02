<script lang="ts">
  /**
   * ``/sessions/new`` route — new-session dialog as a full-page surface.
   *
   * Behavior contract
   * -----------------
   *
   * 1. Renders an inline tags multiselect + working-dir input above
   *    :class:`NewSessionForm`. The form itself owns the routing axes
   *    selectors, the routing preview, the quota bars, and the
   *    first-message textarea (per its own docstring); this parent
   *    supplies the two fields the form leaves to its host (``tagIds``
   *    + ``workingDir``).
   * 2. On submit:
   *    - Validates ``tagIds.length >= 1`` (the v1 form requires at
   *      least one tag — matches the v0.17 NewSessionForm contract).
   *    - Validates ``workingDir.trim() !== ""`` (the create endpoint
   *      requires a non-empty path).
   *    - Validates ``firstMessage.trim() !== ""`` so the freshly-
   *      created session always has a kick-off prompt — without one
   *      the user lands on an empty conversation that can't be
   *      restarted via Up-arrow.
   *    - POSTs ``/api/sessions`` with the full payload.
   *    - POSTs the first message via :func:`sendPrompt`.
   *    - ``goto(/sessions/<new id>)`` so the URL-driven layout takes
   *      over and the conversation pane fills in.
   *
   * Validation surfaces inline above the submit row; the form itself
   * does not own the error rendering because the form is shared with
   * tests and other potential hosts that may have their own validation.
   *
   * Closing-sweep audit (2026-05-02) — this route was the missing
   * surface that made ``+ New Session`` go nowhere.
   */
  import { goto } from "$app/navigation";

  import { createSession } from "$lib/api/sessions";
  import { listTags, type TagOut } from "$lib/api/tags";
  import { sendPrompt } from "$lib/api/prompt";
  import { ApiError } from "$lib/api/client";
  import { EXECUTOR_MODEL_SONNET, SESSION_KIND_CHAT, type ExecutorModel } from "$lib/config";
  import NewSessionForm, {
    type NewSessionSubmission,
  } from "$lib/components/new_session/NewSessionForm.svelte";

  /** Title is derived from the first message — single line, ≤80 chars. */
  const TITLE_MAX_FROM_MESSAGE = 80;
  const TITLE_FALLBACK = "(untitled)";

  let availableTags = $state<TagOut[]>([]);
  let tagsLoading = $state(true);
  let tagsError = $state<string | null>(null);

  let selectedTagIds = $state<number[]>([]);
  let workingDir = $state("");

  let submitError = $state<string | null>(null);
  let submitting = $state(false);

  // Hydrate the tag list once on mount. A failure leaves the picker
  // empty + the user can still type a working dir + first message but
  // the submit guard ("≥1 tag") will surface the failure.
  $effect(() => {
    void hydrateTags();
  });

  async function hydrateTags(): Promise<void> {
    tagsLoading = true;
    tagsError = null;
    try {
      availableTags = await listTags();
    } catch (error) {
      tagsError = error instanceof Error ? error.message : String(error);
    } finally {
      tagsLoading = false;
    }
  }

  function toggleTag(tagId: number): void {
    if (selectedTagIds.includes(tagId)) {
      selectedTagIds = selectedTagIds.filter((id) => id !== tagId);
    } else {
      selectedTagIds = [...selectedTagIds, tagId];
    }
  }

  /**
   * Pull a sensible session title from the first message: first line,
   * trimmed, capped at :data:`TITLE_MAX_FROM_MESSAGE` characters with a
   * single ``…`` suffix when truncated. The fallback is the database
   * sentinel used by the migration's title-coercion rule.
   */
  function deriveTitle(firstMessage: string): string {
    const firstLine = firstMessage.split(/\r?\n/, 1)[0]?.trim() ?? "";
    if (firstLine === "") {
      return TITLE_FALLBACK;
    }
    if (firstLine.length <= TITLE_MAX_FROM_MESSAGE) {
      return firstLine;
    }
    return `${firstLine.slice(0, TITLE_MAX_FROM_MESSAGE - 1)}…`;
  }

  /**
   * The form's executor selection is the wire model name — pass it
   * straight through to the create endpoint. The DB layer's model
   * validator accepts both the short ids (``sonnet`` / ``haiku`` /
   * ``opus``) and the full ``claude-*`` ids; the form emits the short
   * form so the backend does the right thing.
   */
  function pickModel(executor: ExecutorModel): string {
    return executor;
  }

  async function handleSubmit(payload: NewSessionSubmission): Promise<void> {
    submitError = null;
    if (payload.tagIds.length === 0) {
      submitError = "Attach at least one tag.";
      return;
    }
    const trimmedWd = workingDir.trim();
    if (trimmedWd === "") {
      submitError = "Working dir is required.";
      return;
    }
    const trimmedMessage = payload.firstMessage.trim();
    if (trimmedMessage === "") {
      submitError = "First message is required.";
      return;
    }
    submitting = true;
    try {
      const created = await createSession({
        kind: SESSION_KIND_CHAT,
        title: deriveTitle(payload.firstMessage),
        working_dir: trimmedWd,
        model: pickModel(payload.routing.executor),
        tag_ids: payload.tagIds,
      });
      // Queue the kick-off prompt against the new session so the
      // first turn is already in flight by the time the URL flips.
      await sendPrompt(created.id, trimmedMessage);
      await goto(`/sessions/${encodeURIComponent(created.id)}`);
    } catch (error) {
      const message = error instanceof ApiError ? describeApiError(error) : String(error);
      submitError = `Couldn't create the session: ${message}`;
    } finally {
      submitting = false;
    }
  }

  function describeApiError(error: ApiError): string {
    const detail = (error.body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") {
      return detail;
    }
    return error.message;
  }

  function handleCancel(): void {
    void goto("/");
  }

  // Default executor — matches the form's own default so the routing
  // preview line shows "Sonnet" before the user touches anything.
  const _defaultExecutor: ExecutorModel = EXECUTOR_MODEL_SONNET;
  void _defaultExecutor;
</script>

<section class="new-session-page" data-testid="new-session-page" aria-label="Create new session">
  <header class="new-session-page__header">
    <h1>Create a new session</h1>
    <p class="new-session-page__lede">
      Pick at least one tag, point at a working directory, and write the first message. The routing
      axes below adapt as you type.
    </p>
  </header>

  <fieldset class="new-session-page__tags">
    <legend>Tags</legend>
    {#if tagsLoading}
      <p class="new-session-page__hint">Loading tags…</p>
    {:else if tagsError !== null}
      <p class="new-session-page__error" role="alert">Couldn't load tags: {tagsError}</p>
    {:else if availableTags.length === 0}
      <p class="new-session-page__hint">
        No tags yet. Create one from the Tags page first; the new-session form requires at least
        one.
      </p>
    {:else}
      <ul class="new-session-page__tag-list" aria-label="Available tags">
        {#each availableTags as tag (tag.id)}
          {@const active = selectedTagIds.includes(tag.id)}
          <li>
            <button
              type="button"
              class="new-session-page__tag-chip"
              class:new-session-page__tag-chip--active={active}
              aria-pressed={active}
              onclick={() => toggleTag(tag.id)}
              data-testid={`new-session-tag-${tag.id}`}
            >
              {tag.name}
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </fieldset>

  <label class="new-session-page__field">
    <span>Working directory</span>
    <input
      type="text"
      data-testid="new-session-working-dir"
      placeholder="/home/you/Projects/example"
      bind:value={workingDir}
    />
  </label>

  <NewSessionForm
    tagIds={selectedTagIds}
    {workingDir}
    onSubmit={(payload) => {
      void handleSubmit(payload);
    }}
    onCancel={handleCancel}
  />

  {#if submitError !== null}
    <p class="new-session-page__error" role="alert" data-testid="new-session-submit-error">
      {submitError}
    </p>
  {/if}
  {#if submitting}
    <p class="new-session-page__hint" data-testid="new-session-submitting">Creating session…</p>
  {/if}
</section>

<style>
  .new-session-page {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 1rem;
    max-width: 44rem;
    margin: 0 auto;
  }
  .new-session-page__header h1 {
    font-size: 1.25rem;
    font-weight: 600;
    margin: 0;
  }
  .new-session-page__lede {
    font-size: 0.875rem;
    color: rgb(var(--bearings-fg-muted));
    margin: 0.25rem 0 0 0;
  }
  .new-session-page__tags {
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.375rem;
    padding: 0.5rem 0.75rem;
  }
  .new-session-page__tags legend {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: rgb(var(--bearings-fg-muted));
    padding: 0 0.25rem;
  }
  .new-session-page__tag-list {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .new-session-page__tag-chip {
    background: rgb(var(--bearings-surface-2));
    color: inherit;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 999px;
    padding: 0.125rem 0.625rem;
    font: inherit;
    font-size: 0.75rem;
    cursor: pointer;
  }
  .new-session-page__tag-chip--active {
    background: rgb(var(--bearings-accent));
    color: white;
    border-color: transparent;
  }
  .new-session-page__field {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: 0.8125rem;
  }
  .new-session-page__field span {
    color: rgb(var(--bearings-fg-muted));
  }
  .new-session-page__field input {
    background: rgb(var(--bearings-surface-2));
    color: inherit;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.375rem 0.5rem;
    font: inherit;
  }
  .new-session-page__hint {
    font-size: 0.8125rem;
    color: rgb(var(--bearings-fg-muted));
    margin: 0;
  }
  .new-session-page__error {
    font-size: 0.8125rem;
    color: #f87171;
    margin: 0;
  }
</style>
