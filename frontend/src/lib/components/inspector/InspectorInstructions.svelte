<script lang="ts">
  /**
   * Instructions subsection — exposes the active session's
   * user-customisable instructions (``session_instructions`` on
   * :class:`SessionOut`). When the field is ``null`` or empty the
   * component renders the documented empty-state copy rather than a
   * blank pre-block.
   *
   * Behavior anchors:
   *
   * - ``docs/architecture-v1.md`` §1.2 enumerates this component as
   *   ``InspectorInstructions.svelte`` under ``components/inspector/``.
   * - ``docs/behavior/chat.md`` §"SessionEdit modal" — the "Edit…"
   *   button opens ``SessionEdit`` scrolled to the instructions textarea
   *   (``focusInstructions=true``). Gap: gap-cycle-10-001.
   *
   * The pre-block uses ``whitespace-pre-wrap`` so multi-line
   * instructions render with their original line breaks while still
   * wrapping at the column edge — matches the conversation pane's
   * behaviour on long lines per chat.md §"Conversation rendering".
   */
  import { INSPECTOR_STRINGS } from "../../config";
  import type { SessionOut } from "../../api/sessions";
  import { listTags, type TagOut } from "../../api/tags";
  import { refreshSessions } from "../../stores/sessions.svelte";
  import { currentFilter } from "../../stores/tags.svelte";
  import SessionEdit from "../modals/SessionEdit.svelte";

  interface Props {
    session: SessionOut;
    /** Tags currently attached to this session (from the sessions store). */
    currentTags?: readonly TagOut[];
  }

  const { session, currentTags = [] }: Props = $props();

  // ``session_instructions`` is ``string | null`` on the wire. An empty
  // string is treated the same as ``null`` for display purposes — both
  // render the empty-state copy. Whitespace-only strings are also
  // treated as empty so a stray newline doesn't masquerade as content.
  const trimmed = $derived(session.session_instructions?.trim() ?? "");
  const hasInstructions = $derived(trimmed.length > 0);

  // ---- edit modal state --------------------------------------------------

  let showEditModal = $state(false);
  let allTagsForEdit = $state<TagOut[]>([]);

  async function openEditModal(): Promise<void> {
    try {
      allTagsForEdit = await listTags();
    } catch {
      allTagsForEdit = [];
    }
    showEditModal = true;
  }

  async function handleEditSave(): Promise<void> {
    showEditModal = false;
    await refreshSessions(currentFilter());
  }
</script>

{#if showEditModal}
  <SessionEdit
    {session}
    {currentTags}
    allTags={allTagsForEdit}
    focusInstructions={true}
    onSave={() => void handleEditSave()}
    onCancel={() => {
      showEditModal = false;
    }}
  />
{/if}

<section class="inspector-instructions flex flex-col gap-3" data-testid="inspector-instructions">
  <div class="flex items-center justify-between">
    <h3 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
      {INSPECTOR_STRINGS.instructionsHeading}
    </h3>
    <button
      type="button"
      class="rounded border border-border bg-surface-2 px-1.5 py-0.5 text-xs text-fg hover:bg-surface-1"
      data-testid="inspector-instructions-edit-btn"
      onclick={() => void openEditModal()}
    >
      {INSPECTOR_STRINGS.instructionsEditButton}
    </button>
  </div>

  {#if hasInstructions}
    <pre
      class="inspector-instructions__body whitespace-pre-wrap break-words rounded border border-border bg-surface-2 p-2 font-mono text-xs text-fg"
      data-testid="inspector-instructions-body"
      aria-label={INSPECTOR_STRINGS.instructionsBodyLabel}>{session.session_instructions}</pre>
  {:else}
    <p class="text-fg-muted" data-testid="inspector-instructions-empty">
      {INSPECTOR_STRINGS.instructionsEmpty}
    </p>
  {/if}
</section>
