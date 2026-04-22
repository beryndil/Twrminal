<script lang="ts">
  import { sessions } from '$lib/stores/sessions.svelte';
  import { tags } from '$lib/stores/tags.svelte';
  import { prefs } from '$lib/stores/prefs.svelte';
  import { agent } from '$lib/agent.svelte';
  import * as api from '$lib/api';
  import FolderPicker from './FolderPicker.svelte';
  import ModelSelect from './ModelSelect.svelte';
  import { parseBudget } from '$lib/utils/budget';

  let { open = $bindable(false) }: { open?: boolean } = $props();

  let workingDir = $state('');
  let model = $state('claude-opus-4-7');
  let title = $state('');
  let budget = $state('');
  let submitting = $state(false);
  // v0.4.0 session-kind toggle. 'checklist' hides Budget + Model
  // because checklists never run an agent and never burn tokens —
  // the fields are still sent to the backend (the default-from-tag
  // values survive in state), just not surfaced in the form.
  let kind = $state<'chat' | 'checklist'>('chat');

  // v0.2.13: ≥1 attached tag required. Seeded from the active sidebar
  // filter on open, then user edits with the chip UI below.
  let tagIds = $state<number[]>([]);
  let tagDraft = $state('');
  let tagError = $state<string | null>(null);

  const attachedTags = $derived(
    tagIds.map((id) => tags.list.find((t) => t.id === id)).filter((t): t is api.Tag => t !== undefined)
  );
  const attachedSet = $derived(new Set(tagIds));
  const draftLower = $derived(tagDraft.trim().toLowerCase());
  const suggestions = $derived(
    draftLower === ''
      ? []
      : tags.list.filter((t) => !attachedSet.has(t.id) && t.name.toLowerCase().includes(draftLower))
  );
  const exactMatch = $derived(
    tags.list.find((t) => t.name.toLowerCase() === draftLower) ?? null
  );

  /** Precedence-aware defaults from the tags currently attached.
   * Canonical tag order (pinned-first / sort_order / id); last wins —
   * same rule as tag-memory precedence. */
  function attachedTagDefaults(): { workingDir: string | null; model: string | null } {
    let wd: string | null = null;
    let md: string | null = null;
    for (const t of tags.list) {
      if (!attachedSet.has(t.id)) continue;
      if (t.default_working_dir) wd = t.default_working_dir;
      if (t.default_model) md = t.default_model;
    }
    return { workingDir: wd, model: md };
  }

  // Seed form state when the modal opens. Keyed on the open transition
  // so store refreshes while the form is visible don't clobber edits.
  let seededFor = $state(false);
  $effect(() => {
    if (!open) {
      seededFor = false;
      return;
    }
    if (seededFor) return;
    seededFor = true;
    tagIds = [...tags.selected];
    tagDraft = '';
    tagError = null;
    const td = attachedTagDefaults();
    workingDir = td.workingDir || prefs.defaultWorkingDir || workingDir;
    model = td.model || prefs.defaultModel || model;
  });

  function attachTag(tag: api.Tag) {
    if (attachedSet.has(tag.id)) return;
    tagIds = [...tagIds, tag.id];
    tagDraft = '';
    tagError = null;
    // Apply defaults: working_dir only when the field is empty (don't
    // clobber what the user typed); model unconditionally per the
    // last-wins precedence rule.
    if (!workingDir.trim() && tag.default_working_dir) {
      workingDir = tag.default_working_dir;
    }
    if (tag.default_model) model = tag.default_model;
  }

  function detachTag(id: number) {
    tagIds = tagIds.filter((x) => x !== id);
  }

  async function createAndAttach() {
    const name = tagDraft.trim();
    if (name === '') return;
    tagError = null;
    const created = await tags.create({ name });
    if (!created) {
      tagError = tags.error;
      return;
    }
    attachTag(created);
  }

  function onTagKey(e: KeyboardEvent) {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    if (exactMatch) {
      if (!attachedSet.has(exactMatch.id)) attachTag(exactMatch);
      else tagDraft = '';
      return;
    }
    createAndAttach();
  }

  async function onSubmit() {
    if (tagIds.length === 0) {
      tagError = 'Attach at least one tag before creating a session.';
      return;
    }
    submitting = true;
    const ids = [...tagIds];
    const createdKind = kind;
    const created = await sessions.create({
      working_dir: workingDir.trim() || prefs.defaultWorkingDir || '/tmp',
      model: model.trim() || prefs.defaultModel || 'claude-opus-4-7',
      title: title.trim() || null,
      max_budget_usd: parseBudget(budget),
      tag_ids: ids,
      kind: createdKind
    });
    submitting = false;
    if (!created) return;
    workingDir = '';
    title = '';
    budget = '';
    tagIds = [];
    kind = 'chat';
    for (const id of ids) tags.bumpCount(id, +1);
    open = false;
    // Checklist sessions don't run an agent loop — skip the WS
    // connect so the runner guard doesn't close the socket with
    // a kind-unsupported error.
    if (createdKind === 'chat') {
      await agent.connect(created.id);
    }
  }
</script>

{#if open}
  <form
    class="flex flex-col gap-2 rounded bg-slate-800/60 p-3"
    onsubmit={(e) => {
      e.preventDefault();
      onSubmit();
    }}
  >
    <div
      class="flex rounded bg-slate-900 p-0.5 text-xs"
      role="radiogroup"
      aria-label="Session kind"
    >
      <button
        type="button"
        role="radio"
        aria-checked={kind === 'chat'}
        class="flex-1 rounded px-2 py-1 {kind === 'chat'
          ? 'bg-slate-700 text-slate-100'
          : 'text-slate-400 hover:text-slate-200'}"
        onclick={() => (kind = 'chat')}
      >
        Chat
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={kind === 'checklist'}
        class="flex-1 rounded px-2 py-1 {kind === 'checklist'
          ? 'bg-slate-700 text-slate-100'
          : 'text-slate-400 hover:text-slate-200'}"
        onclick={() => (kind = 'checklist')}
      >
        ☑ Checklist
      </button>
    </div>
    <div class="flex flex-col text-xs gap-1">
      <span class="text-slate-400">Working dir</span>
      <FolderPicker bind:value={workingDir} />
    </div>
    {#if kind === 'chat'}
      <div class="flex flex-col text-xs gap-1">
        <span class="text-slate-400">Model</span>
        <ModelSelect bind:value={model} />
      </div>
    {/if}
    <label class="flex flex-col text-xs gap-1">
      <span class="text-slate-400">Title <span class="text-slate-600">(optional)</span></span>
      <input
        type="text"
        class="rounded bg-slate-950 px-2 py-1 text-sm"
        bind:value={title}
      />
    </label>
    {#if kind === 'chat'}
      <label class="flex flex-col text-xs gap-1">
        <span class="text-slate-400"
          >Budget USD <span class="text-slate-600">(optional)</span></span
        >
        <input
          type="number"
          inputmode="decimal"
          step="0.01"
          min="0"
          placeholder="no cap"
          class="rounded bg-slate-950 px-2 py-1 text-sm font-mono"
          bind:value={budget}
        />
      </label>
    {/if}

    <section class="flex flex-col gap-1 text-xs">
      <span class="text-slate-400">Tags <span class="text-rose-400">*</span></span>
      {#if attachedTags.length > 0}
        <ul class="flex flex-wrap gap-1" aria-label="Attached tags">
          {#each attachedTags as tag (tag.id)}
            <li class="flex items-center gap-1 rounded bg-slate-900 px-2 py-0.5">
              {#if tag.pinned}
                <span class="text-amber-400" aria-label="pinned">★</span>
              {/if}
              <span>{tag.name}</span>
              <button
                type="button"
                class="text-slate-500 hover:text-rose-400"
                aria-label={`Detach ${tag.name}`}
                onclick={() => detachTag(tag.id)}
              >
                ✕
              </button>
            </li>
          {/each}
        </ul>
      {/if}
      <input
        type="text"
        class="rounded bg-slate-950 px-2 py-1 text-sm"
        placeholder="Add a tag (Enter to attach or create)"
        aria-label="New-session tag name"
        bind:value={tagDraft}
        onkeydown={onTagKey}
      />
      {#if suggestions.length > 0}
        <ul class="flex flex-wrap gap-1" aria-label="Tag suggestions">
          {#each suggestions as tag (tag.id)}
            <li>
              <button
                type="button"
                class="rounded bg-slate-900 hover:bg-slate-700 px-2 py-0.5"
                onclick={() => attachTag(tag)}
              >
                + {tag.name}
              </button>
            </li>
          {/each}
        </ul>
      {:else if tagDraft.trim() !== '' && !exactMatch}
        <button
          type="button"
          class="self-start rounded bg-emerald-700 hover:bg-emerald-600 px-2 py-0.5"
          onclick={createAndAttach}
        >
          + Create "{tagDraft.trim()}"
        </button>
      {/if}
      {#if tagError}
        <p class="text-rose-400">{tagError}</p>
      {/if}
    </section>

    <button
      type="submit"
      class="rounded bg-emerald-600 hover:bg-emerald-500 px-2 py-1 text-sm mt-1 disabled:opacity-50"
      disabled={submitting || tagIds.length === 0}
      title={tagIds.length === 0 ? 'Attach at least one tag' : ''}
    >
      {submitting ? 'Creating…' : 'Create session'}
    </button>
  </form>
{/if}
