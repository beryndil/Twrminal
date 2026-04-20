<script lang="ts">
  import { prefs } from '$lib/stores/prefs.svelte';
  import { auth } from '$lib/stores/auth.svelte';

  let { open = $bindable(false) }: { open?: boolean } = $props();

  let model = $state(prefs.defaultModel);
  let workdir = $state(prefs.defaultWorkingDir);
  let token = $state(prefs.authToken);

  $effect(() => {
    if (open) {
      model = prefs.defaultModel;
      workdir = prefs.defaultWorkingDir;
      token = prefs.authToken;
    }
  });

  function onSave() {
    prefs.save({
      defaultModel: model,
      defaultWorkingDir: workdir,
      authToken: token
    });
    // If the gate is still up (required/invalid) and the user supplied
    // a token, flip the store to `ok` so the app boots.
    if (token.trim() && (auth.status === 'required' || auth.status === 'invalid')) {
      auth.saveToken(token.trim());
    }
    open = false;
  }

  function onCancel() {
    open = false;
  }
</script>

{#if open}
  <div class="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/80 p-4">
    <form
      class="w-full max-w-md rounded-lg border border-slate-800 bg-slate-900 p-6 shadow-2xl
        flex flex-col gap-4"
      onsubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
    >
      <header class="flex items-start justify-between">
        <div>
          <h2 class="text-lg font-medium">Settings</h2>
          <p class="text-xs text-slate-400 mt-1">
            Stored in <code>localStorage</code>. Empty fields clear the setting.
          </p>
        </div>
        <button
          type="button"
          class="text-slate-500 hover:text-slate-300 text-sm"
          aria-label="Close settings"
          onclick={onCancel}
        >
          ✕
        </button>
      </header>

      <label class="flex flex-col gap-1 text-xs">
        <span class="text-slate-400">Auth token</span>
        <input
          type="password"
          class="rounded bg-slate-950 border border-slate-800 px-2 py-2 text-sm font-mono
            focus:outline-none focus:border-slate-600"
          autocomplete="off"
          placeholder="leave empty if the server has auth disabled"
          bind:value={token}
        />
      </label>

      <label class="flex flex-col gap-1 text-xs">
        <span class="text-slate-400">Default model</span>
        <input
          type="text"
          class="rounded bg-slate-950 border border-slate-800 px-2 py-2 text-sm font-mono
            focus:outline-none focus:border-slate-600"
          placeholder="claude-opus-4-7"
          bind:value={model}
        />
      </label>

      <label class="flex flex-col gap-1 text-xs">
        <span class="text-slate-400">Default working dir</span>
        <input
          type="text"
          class="rounded bg-slate-950 border border-slate-800 px-2 py-2 text-sm font-mono
            focus:outline-none focus:border-slate-600"
          placeholder="/home/…"
          bind:value={workdir}
        />
      </label>

      <div class="flex items-center justify-end gap-2 pt-2">
        <button
          type="button"
          class="rounded bg-slate-800 hover:bg-slate-700 px-3 py-2 text-sm"
          onclick={onCancel}
        >
          Cancel
        </button>
        <button
          type="submit"
          class="rounded bg-emerald-600 hover:bg-emerald-500 px-3 py-2 text-sm"
        >
          Save
        </button>
      </div>
    </form>
  </div>
{/if}
