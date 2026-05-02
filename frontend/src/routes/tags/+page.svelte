<script lang="ts">
  /**
   * ``/tags`` route — full tag-management surface.
   *
   * Replaces the v1.0 stub ("coming in a follow-up phase") flagged by
   * the closing-sweep audit (2026-05-02, P1.7). Surfaces:
   *
   * 1. Master list of tags grouped by their ``group`` prefix (the
   *    slash-namespace convention). Click a row → load the detail
   *    pane on the right.
   * 2. Detail pane:
   *    - editable name / color / default model / working_dir;
   *    - delete button (cascades through ``session_tags`` +
   *      ``tag_memories`` per the backend route docstring);
   *    - per-tag routing-rule editor (RoutingRuleEditor with
   *      ``kind="tag"``) — closes the second orphan flagged in the
   *      audit (the editor mount in ``/settings`` covered system rules
   *      only; per-tag rules per spec §10 "Lives under each tag").
   * 3. ``+ New tag`` button at the top of the master list — inline
   *    form, server validation surfaces inline.
   *
   * The page does NOT show per-tag session counts — that would
   * require a per-row sessions fetch storm (no aggregated count
   * endpoint exists). A future ``/api/tags?include_session_count=1``
   * extension can light this up without touching the page.
   */
  import { ApiError } from "$lib/api/client";
  import {
    createTag,
    deleteTag,
    listTags,
    updateTag,
    type TagInput,
    type TagOut,
  } from "$lib/api/tags";
  import RoutingRuleEditor from "$lib/components/routing/RoutingRuleEditor.svelte";

  let tags = $state<TagOut[]>([]);
  let loading = $state(true);
  let listError = $state<string | null>(null);
  let selectedId = $state<number | null>(null);
  let creatingNew = $state(false);
  let newTagName = $state("");
  let newTagError = $state<string | null>(null);
  let creating = $state(false);

  // Edit-pane local state — mirrors the selected tag so the user can
  // discard with Cancel without poking the server. Reseeded by an
  // effect when ``selectedId`` flips.
  let editName = $state("");
  let editColor = $state("");
  let editModel = $state("");
  let editWd = $state("");
  let editError = $state<string | null>(null);
  let saving = $state(false);
  let deleting = $state(false);

  $effect(() => {
    void hydrate();
  });

  $effect(() => {
    const id = selectedId;
    if (id === null) {
      return;
    }
    const tag = tags.find((row) => row.id === id);
    if (tag === undefined) {
      return;
    }
    editName = tag.name;
    editColor = tag.color ?? "";
    editModel = tag.default_model ?? "";
    editWd = tag.working_dir ?? "";
    editError = null;
  });

  async function hydrate(): Promise<void> {
    loading = true;
    listError = null;
    try {
      tags = await listTags();
      if (selectedId !== null && !tags.some((row) => row.id === selectedId)) {
        selectedId = null;
      }
    } catch (error) {
      listError = describe(error);
    } finally {
      loading = false;
    }
  }

  function selectTag(id: number): void {
    selectedId = id;
    creatingNew = false;
  }

  function startCreate(): void {
    creatingNew = true;
    newTagName = "";
    newTagError = null;
  }

  async function submitCreate(): Promise<void> {
    const name = newTagName.trim();
    if (name === "") {
      newTagError = "Name is required.";
      return;
    }
    creating = true;
    newTagError = null;
    try {
      const created = await createTag({ name });
      tags = [...tags, created].sort((a, b) => a.name.localeCompare(b.name));
      creatingNew = false;
      selectedId = created.id;
    } catch (error) {
      newTagError = describe(error);
    } finally {
      creating = false;
    }
  }

  async function submitEdit(): Promise<void> {
    if (selectedId === null) {
      return;
    }
    const id = selectedId;
    const trimmedName = editName.trim();
    if (trimmedName === "") {
      editError = "Name is required.";
      return;
    }
    const payload: TagInput = {
      name: trimmedName,
      color: editColor.trim() === "" ? null : editColor.trim(),
      default_model: editModel.trim() === "" ? null : editModel.trim(),
      working_dir: editWd.trim() === "" ? null : editWd.trim(),
    };
    saving = true;
    editError = null;
    try {
      const updated = await updateTag(id, payload);
      tags = tags
        .map((row) => (row.id === id ? updated : row))
        .sort((a, b) => a.name.localeCompare(b.name));
    } catch (error) {
      editError = describe(error);
    } finally {
      saving = false;
    }
  }

  async function submitDelete(): Promise<void> {
    if (selectedId === null) {
      return;
    }
    const id = selectedId;
    const tag = tags.find((row) => row.id === id);
    const label = tag?.name ?? `tag ${id}`;
    if (!window.confirm(`Delete ${label}? Sessions tagged with it lose the chip.`)) {
      return;
    }
    deleting = true;
    editError = null;
    try {
      await deleteTag(id);
      tags = tags.filter((row) => row.id !== id);
      selectedId = null;
    } catch (error) {
      editError = describe(error);
    } finally {
      deleting = false;
    }
  }

  function describe(error: unknown): string {
    if (error instanceof ApiError) {
      const detail = (error.body as { detail?: unknown } | null)?.detail;
      if (typeof detail === "string") {
        return detail;
      }
      return error.message;
    }
    return error instanceof Error ? error.message : String(error);
  }

  // Group the tags by their ``group`` prefix for the master list. An
  // empty group means "ungrouped" — surfaced under a special bucket
  // so flat tag sets still render meaningfully.
  const groupedTags = $derived(groupTagsByPrefix(tags));

  function groupTagsByPrefix(rows: TagOut[]): Array<[string, TagOut[]]> {
    const buckets = new Map<string, TagOut[]>();
    for (const row of rows) {
      const key = row.group ?? "(ungrouped)";
      const bucket = buckets.get(key) ?? [];
      bucket.push(row);
      buckets.set(key, bucket);
    }
    return [...buckets.entries()].sort(([a], [b]) => a.localeCompare(b));
  }

  const selected = $derived(tags.find((row) => row.id === selectedId) ?? null);
</script>

<section class="tags-page" data-testid="tags-page" aria-label="Tag management">
  <aside class="tags-page__list" aria-label="Tag list">
    <div class="tags-page__list-header">
      <h1>Tags</h1>
      <button
        type="button"
        class="tags-page__new"
        onclick={startCreate}
        data-testid="tags-page-new"
      >
        + New tag
      </button>
    </div>

    {#if creatingNew}
      <form
        class="tags-page__create-form"
        onsubmit={(event) => {
          event.preventDefault();
          void submitCreate();
        }}
      >
        <input
          type="text"
          placeholder="tag/name"
          aria-label="New tag name"
          bind:value={newTagName}
          data-testid="tags-page-new-name"
        />
        <button type="submit" disabled={creating} data-testid="tags-page-new-submit">
          {creating ? "Creating…" : "Create"}
        </button>
        <button type="button" onclick={() => (creatingNew = false)}>Cancel</button>
        {#if newTagError !== null}
          <p class="tags-page__error" role="alert">{newTagError}</p>
        {/if}
      </form>
    {/if}

    {#if loading}
      <p class="tags-page__hint">Loading tags…</p>
    {:else if listError !== null}
      <p class="tags-page__error" role="alert">Couldn't load tags: {listError}</p>
    {:else if tags.length === 0}
      <p class="tags-page__hint">No tags yet. Create one above to get started.</p>
    {:else}
      {#each groupedTags as [group, rows] (group)}
        <section class="tags-page__group">
          <h2 class="tags-page__group-heading">{group}</h2>
          <ul class="tags-page__rows">
            {#each rows as tag (tag.id)}
              {@const active = tag.id === selectedId}
              <li>
                <button
                  type="button"
                  class="tags-page__row"
                  class:tags-page__row--active={active}
                  aria-pressed={active}
                  onclick={() => selectTag(tag.id)}
                  data-testid={`tags-page-row-${tag.id}`}
                >
                  <span
                    class="tags-page__swatch"
                    style={tag.color ? `background:${tag.color};` : undefined}
                    aria-hidden="true"
                  ></span>
                  <span class="tags-page__row-name">{tag.name}</span>
                </button>
              </li>
            {/each}
          </ul>
        </section>
      {/each}
    {/if}
  </aside>

  <main class="tags-page__detail" aria-label="Selected tag detail">
    {#if selected === null}
      <p class="tags-page__hint">Pick a tag from the list to edit it, or create a new one.</p>
    {:else}
      <header class="tags-page__detail-header">
        <h2>{selected.name}</h2>
        <button
          type="button"
          class="tags-page__delete"
          onclick={() => void submitDelete()}
          disabled={deleting}
          data-testid="tags-page-delete"
        >
          {deleting ? "Deleting…" : "Delete tag"}
        </button>
      </header>

      <form
        class="tags-page__edit-form"
        onsubmit={(event) => {
          event.preventDefault();
          void submitEdit();
        }}
      >
        <label>
          <span>Name</span>
          <input type="text" bind:value={editName} data-testid="tags-page-edit-name" />
        </label>
        <label>
          <span>Color (hex or palette token)</span>
          <input
            type="text"
            bind:value={editColor}
            placeholder="#1d4ed8"
            data-testid="tags-page-edit-color"
          />
        </label>
        <label>
          <span>Default model</span>
          <input
            type="text"
            bind:value={editModel}
            placeholder="sonnet"
            data-testid="tags-page-edit-model"
          />
        </label>
        <label>
          <span>Default working dir</span>
          <input
            type="text"
            bind:value={editWd}
            placeholder="/home/you/Projects/example"
            data-testid="tags-page-edit-wd"
          />
        </label>
        <div class="tags-page__edit-actions">
          <button type="submit" disabled={saving} data-testid="tags-page-edit-save">
            {saving ? "Saving…" : "Save"}
          </button>
          {#if editError !== null}
            <p class="tags-page__error" role="alert">{editError}</p>
          {/if}
        </div>
      </form>

      <section class="tags-page__routing" aria-label="Routing rules for this tag">
        <h3>Routing rules</h3>
        <p class="tags-page__hint">
          Per spec §10 — these rules evaluate before the system rule set when a session attached to
          this tag asks for a routing decision.
        </p>
        <RoutingRuleEditor kind="tag" tagId={selected.id} />
      </section>
    {/if}
  </main>
</section>

<style>
  .tags-page {
    display: grid;
    grid-template-columns: minmax(16rem, 22rem) minmax(0, 1fr);
    gap: 1rem;
    padding: 1rem;
    height: 100%;
    overflow: hidden;
  }
  .tags-page__list {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    overflow-y: auto;
  }
  .tags-page__list-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
  }
  .tags-page__list-header h1 {
    font-size: 1.125rem;
    font-weight: 600;
    margin: 0;
  }
  .tags-page__new,
  .tags-page__create-form button[type="submit"],
  .tags-page__edit-actions button[type="submit"] {
    background: rgb(var(--bearings-accent));
    color: white;
    border: none;
    border-radius: 0.25rem;
    padding: 0.25rem 0.625rem;
    font-size: 0.75rem;
    cursor: pointer;
  }
  .tags-page__create-form {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
    align-items: center;
    padding: 0.5rem;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.375rem;
  }
  .tags-page__create-form input {
    background: rgb(var(--bearings-surface-2));
    color: inherit;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.25rem 0.5rem;
    font: inherit;
    flex: 1 1 auto;
    min-width: 8rem;
  }
  .tags-page__create-form button[type="button"] {
    background: rgb(var(--bearings-surface-2));
    color: inherit;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.25rem 0.625rem;
    font-size: 0.75rem;
    cursor: pointer;
  }
  .tags-page__group-heading {
    font-size: 0.6875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: rgb(var(--bearings-fg-muted));
    margin: 0.25rem 0;
  }
  .tags-page__rows {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.125rem;
  }
  .tags-page__row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
    background: transparent;
    color: inherit;
    border: 1px solid transparent;
    border-radius: 0.25rem;
    padding: 0.25rem 0.5rem;
    text-align: left;
    cursor: pointer;
  }
  .tags-page__row:hover {
    background: rgb(var(--bearings-surface-2));
  }
  .tags-page__row--active {
    background: rgb(var(--bearings-surface-2));
    border-color: rgb(var(--bearings-accent));
  }
  .tags-page__swatch {
    width: 0.625rem;
    height: 0.625rem;
    border-radius: 999px;
    background: rgb(var(--bearings-border));
    flex-shrink: 0;
  }
  .tags-page__row-name {
    font-size: 0.8125rem;
  }
  .tags-page__detail {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    overflow-y: auto;
  }
  .tags-page__detail-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .tags-page__detail-header h2 {
    font-size: 1rem;
    font-weight: 600;
    margin: 0;
  }
  .tags-page__delete {
    background: #b91c1c;
    color: white;
    border: none;
    border-radius: 0.25rem;
    padding: 0.25rem 0.625rem;
    font-size: 0.75rem;
    cursor: pointer;
  }
  .tags-page__edit-form {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.375rem;
    padding: 0.75rem;
  }
  .tags-page__edit-form label {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: 0.8125rem;
  }
  .tags-page__edit-form label span {
    color: rgb(var(--bearings-fg-muted));
  }
  .tags-page__edit-form input {
    background: rgb(var(--bearings-surface-2));
    color: inherit;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.375rem 0.5rem;
    font: inherit;
  }
  .tags-page__edit-actions {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
  .tags-page__routing {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.375rem;
    padding: 0.75rem;
  }
  .tags-page__routing h3 {
    font-size: 0.875rem;
    font-weight: 600;
    margin: 0;
  }
  .tags-page__hint {
    font-size: 0.8125rem;
    color: rgb(var(--bearings-fg-muted));
    margin: 0;
  }
  .tags-page__error {
    font-size: 0.8125rem;
    color: #f87171;
    margin: 0;
  }
</style>
