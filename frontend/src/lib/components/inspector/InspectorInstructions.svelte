<script lang="ts">
  /**
   * Instructions subsection — renders the full assembled system-prompt
   * layer breakdown for the active session.  Each layer kind appears as
   * a collapsible row showing the kind label, optional source path, and
   * approximate token count.  Kinds with no content render an
   * empty-state message.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/chat.md`` §"System-prompt layers contract" —
   *   layer kinds, display order, and empty-state rules.
   * - ``docs/architecture-v1.md`` §1.2 — component registered as
   *   ``InspectorInstructions.svelte`` under ``components/inspector/``.
   * - Gap-cycle-13-004 implements this full-layer view; previous
   *   revisions rendered only ``session_instructions``.
   *
   * The ``Edit…`` button on the ``session_instructions`` section opens
   * ``SessionEdit`` scrolled to the instructions textarea
   * (``focusInstructions=true``) per gap-cycle-10-001.
   */
  import { INSPECTOR_STRINGS } from "../../config";
  import type { SessionOut, SystemPromptLayer } from "../../api/sessions";
  import { getSessionSystemPrompt } from "../../api/sessions";
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

  // ---- layer kinds in display order -------------------------------------

  type LayerKind =
    | "session_instructions"
    | "baseline"
    | "project_claude_md"
    | "tag_memory"
    | "template_baseline";

  const LAYER_DISPLAY_ORDER: readonly LayerKind[] = [
    "session_instructions",
    "baseline",
    "project_claude_md",
    "tag_memory",
    "template_baseline",
  ] as const;

  // ---- system-prompt layers state ---------------------------------------

  let layersLoading = $state(true);
  let layersError = $state(false);
  let allLayers = $state<SystemPromptLayer[]>([]);

  $effect(() => {
    // Re-fetch whenever session id changes.
    const id = session.id;
    layersLoading = true;
    layersError = false;
    allLayers = [];
    getSessionSystemPrompt(id)
      .then((out) => {
        allLayers = out.layers;
        layersLoading = false;
      })
      .catch(() => {
        layersError = true;
        layersLoading = false;
      });
  });

  // Group layers by kind (derived so it re-computes when allLayers changes).
  const layersByKind = $derived(
    Object.fromEntries(
      LAYER_DISPLAY_ORDER.map((kind) => [
        kind,
        allLayers.filter((l) => l.kind === kind),
      ]),
    ) as Record<LayerKind, SystemPromptLayer[]>,
  );

  // ---- collapse/expand state per layer (keyed by kind+index) -----------

  let collapsed = $state<Record<string, boolean>>({});

  function layerKey(kind: string, index: number): string {
    return `${kind}:${index}`;
  }

  function isCollapsed(kind: string, index: number): boolean {
    const key = layerKey(kind, index);
    if (key in collapsed) return collapsed[key];
    // Default: collapse layers whose body exceeds 500 chars.
    const layers = layersByKind[kind as LayerKind] ?? [];
    const body = layers[index]?.body ?? "";
    return body.length > 500;
  }

  function toggleCollapse(kind: string, index: number): void {
    const key = layerKey(kind, index);
    collapsed[key] = !isCollapsed(kind, index);
  }

  // ---- edit modal state -------------------------------------------------

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
    // Re-fetch layers after save so updated session_instructions is visible.
    try {
      const out = await getSessionSystemPrompt(session.id);
      allLayers = out.layers;
    } catch {
      // Non-fatal — stale layers are acceptable until next mount.
    }
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

<section class="inspector-instructions flex flex-col gap-4" data-testid="inspector-instructions">
  <div class="flex items-center justify-between">
    <h3 class="text-xs font-semibold uppercase tracking-wider text-fg-muted">
      {INSPECTOR_STRINGS.instructionsHeading}
    </h3>
  </div>

  {#if layersLoading}
    <p class="text-xs text-fg-muted" data-testid="inspector-instructions-loading">
      {INSPECTOR_STRINGS.instructionsLoadingLayers}
    </p>
  {:else if layersError}
    <p class="text-xs text-fg-error" data-testid="inspector-instructions-error">
      {INSPECTOR_STRINGS.instructionsLayersError}
    </p>
  {:else}
    {#each LAYER_DISPLAY_ORDER as kind (kind)}
      {@const kindLayers = layersByKind[kind]}
      {@const kindLabel = INSPECTOR_STRINGS.instructionsLayerKindLabels[kind]}
      {@const emptyMsg = INSPECTOR_STRINGS.instructionsLayerEmptyState[kind]}

      <div class="flex flex-col gap-1.5" data-testid={`instructions-section-${kind}`}>
        <!-- Section heading row -->
        <div class="flex items-center gap-2">
          <span class="text-xs font-medium uppercase tracking-wider text-fg-muted">
            {kindLabel}
          </span>
          {#if kind === "session_instructions"}
            <button
              type="button"
              class="ml-auto rounded border border-border bg-surface-2 px-1.5 py-0.5 text-xs text-fg hover:bg-surface-1"
              data-testid="inspector-instructions-edit-btn"
              onclick={() => void openEditModal()}
            >
              {INSPECTOR_STRINGS.instructionsEditButton}
            </button>
          {/if}
        </div>

        {#if kindLayers.length === 0}
          <!-- Empty-state row for this kind -->
          <p
            class="text-xs italic text-fg-muted"
            data-testid={`instructions-empty-${kind}`}
          >
            {emptyMsg}
          </p>
        {:else}
          {#each kindLayers as layer, i (i)}
            {@const isLayerCollapsed = isCollapsed(kind, i)}
            <div
              class="flex flex-col rounded border border-border bg-surface-2"
              data-testid={`instructions-layer-${kind}-${i}`}
            >
              <!-- Layer header: source_path + token count + toggle -->
              <button
                type="button"
                class="flex items-center justify-between gap-2 px-2 py-1.5 text-left hover:bg-surface-1"
                data-testid={`instructions-layer-toggle-${kind}-${i}`}
                aria-expanded={!isLayerCollapsed}
                onclick={() => toggleCollapse(kind, i)}
              >
                <span class="min-w-0 truncate font-mono text-xs text-fg">
                  {#if layer.source_path}
                    <span class="text-fg-muted"
                      >{INSPECTOR_STRINGS.instructionsLayerSourceLabel}</span
                    >
                    {layer.source_path}
                  {:else}
                    <span class="text-fg-muted">{kindLabel}</span>
                  {/if}
                </span>
                <span class="shrink-0 text-xs text-fg-muted">
                  {INSPECTOR_STRINGS.instructionsLayerTokensLabel(layer.token_count)}
                </span>
                <span class="shrink-0 text-xs text-fg-muted">
                  {isLayerCollapsed
                    ? INSPECTOR_STRINGS.instructionsLayerExpand
                    : INSPECTOR_STRINGS.instructionsLayerCollapse}
                </span>
              </button>

              {#if !isLayerCollapsed}
                <pre
                  class="whitespace-pre-wrap break-words border-t border-border px-2 py-2 font-mono text-xs text-fg"
                  data-testid={`instructions-layer-body-${kind}-${i}`}
                  aria-label={`${kindLabel} body`}
                >{layer.body}</pre>
              {/if}
            </div>
          {/each}
        {/if}
      </div>
    {/each}
  {/if}
</section>
