<script lang="ts">
  import { untrack } from 'svelte';
  import { prefs } from '$lib/stores/prefs.svelte';
  import { preferences } from '$lib/stores/preferences.svelte';
  import { auth } from '$lib/stores/auth.svelte';
  import {
    notifyPermission,
    notifySupported,
    requestNotifyPermission
  } from '$lib/utils/notify';

  let { open = $bindable(false) }: { open?: boolean } = $props();

  // Server-backed fields hydrate from the preferences store. Local
  // state mirrors them so the modal can defer the PATCH until Save —
  // edit-then-Cancel reverts cleanly because we never touched the
  // shared store mid-edit.
  let displayName = $state(preferences.displayName ?? '');
  let model = $state(preferences.defaultModel);
  let workdir = $state(preferences.defaultWorkingDir);
  let notifyOnComplete = $state(preferences.notifyOnComplete);
  // Theme picker (Themes & skins v1, design §4 Track A). The select
  // binds directly to `theme`; on Save we PATCH the server, which then
  // writes the localStorage cache that the no-flash boot script in
  // app.html reads on next reload. The store's applyTheme() runs as
  // part of update() too, so the data-theme attribute flips
  // immediately on Save without waiting for a page refresh.
  let theme = $state(preferences.theme ?? 'midnight-glass');
  // Auth token is intentionally still client-side: the server can't
  // authorize itself on its own stored token, so this stays in
  // localStorage via the `prefs` store.
  let token = $state(prefs.authToken);
  /** Tracked so the UI can show the live browser permission state
   * ("blocked in browser" when denied). Refreshed each time the
   * modal opens and after a permission request resolves. */
  let permission = $state(notifyPermission());
  /** Save-time error surface. PATCH to /api/preferences can fail
   * (server down, transient 500) — we keep the modal open and show
   * the error rather than swallow it, so the user can retry without
   * losing their typed values. */
  let saveError = $state<string | null>(null);
  let saving = $state(false);

  // Seed from the live stores ONLY on the open transition. We can't
  // track `preferences.*` reactively here because `preferences.update`
  // re-assigns the in-memory row mid-Save (the PATCH response replaces
  // the field values), which would re-fire the effect and clobber the
  // user's typed edits. `untrack` reads the values without subscribing
  // so the effect's only dependency is `open` itself.
  $effect(() => {
    if (!open) return;
    untrack(() => {
      displayName = preferences.displayName ?? '';
      model = preferences.defaultModel;
      workdir = preferences.defaultWorkingDir;
      notifyOnComplete = preferences.notifyOnComplete;
      theme = preferences.theme ?? 'midnight-glass';
      token = prefs.authToken;
      permission = notifyPermission();
      saveError = null;
    });
  });

  async function onNotifyToggle(e: Event) {
    const checked = (e.currentTarget as HTMLInputElement).checked;
    notifyOnComplete = checked;
    if (checked) {
      // Ask the browser the moment the user opts in, not on Save.
      // Gives them a chance to flip the prompt while the modal is
      // still open — and makes "I enabled it but nothing fires" a
      // single UX step to debug.
      permission = await requestNotifyPermission();
      if (permission !== 'granted') {
        notifyOnComplete = false;
      }
    }
  }

  async function onSave() {
    saving = true;
    saveError = null;
    try {
      // Send only the fields that actually changed. Empty strings on
      // the nullable string columns coalesce to `null` (clear); the
      // backend trim-and-coalesce validator handles whitespace-only
      // submissions on `display_name` so we don't have to normalise
      // here.
      await preferences.update({
        display_name: displayName.trim() === '' ? null : displayName,
        theme,
        default_model: model.trim() === '' ? null : model,
        default_working_dir: workdir.trim() === '' ? null : workdir,
        notify_on_complete: notifyOnComplete
      });
    } catch (err) {
      saveError = err instanceof Error ? err.message : String(err);
      saving = false;
      return;
    }
    // Auth token is local-only — save it whether or not the
    // preferences PATCH succeeded.
    prefs.save({ authToken: token });
    if (token.trim() && (auth.status === 'required' || auth.status === 'invalid')) {
      auth.saveToken(token.trim());
    }
    saving = false;
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
        void onSave();
      }}
    >
      <header class="flex items-start justify-between">
        <div>
          <h2 class="text-lg font-medium">Settings</h2>
          <p class="text-xs text-slate-400 mt-1">
            Display name, defaults, and notifications sync to the server
            (preferences row). Auth token stays in <code>localStorage</code>.
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
        <span class="text-slate-400">Display name</span>
        <input
          type="text"
          class="rounded bg-slate-950 border border-slate-800 px-2 py-2 text-sm
            focus:outline-none focus:border-slate-600"
          maxlength="64"
          placeholder="Replaces 'user' on your message bubbles"
          bind:value={displayName}
        />
      </label>

      <label class="flex flex-col gap-1 text-xs">
        <span class="text-slate-400">Theme</span>
        <select
          class="rounded bg-slate-950 border border-slate-800 px-2 py-2 text-sm
            focus:outline-none focus:border-slate-600"
          bind:value={theme}
        >
          <option value="midnight-glass">Midnight Glass (warm-navy, glass panels)</option>
          <option value="default">Default (Tailwind classic dark)</option>
          <option value="paper-light">Paper Light (cream, flat)</option>
        </select>
        <span class="text-slate-500">
          Saved to the server; applies on Save and persists across reloads.
        </span>
      </label>

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

      <div class="flex flex-col gap-1 text-xs">
        <label class="flex items-center gap-2">
          <input
            type="checkbox"
            class="rounded border-slate-700 bg-slate-950"
            checked={notifyOnComplete}
            disabled={!notifySupported() || permission === 'denied'}
            onchange={onNotifyToggle}
          />
          <span class="text-slate-300">Notify when Claude finishes replying</span>
        </label>
        <p class="text-slate-500 pl-6">
          {#if !notifySupported()}
            Your browser does not support desktop notifications.
          {:else if permission === 'denied'}
            Blocked in browser settings — re-allow notifications for this
            site, then re-toggle.
          {:else if notifyOnComplete}
            Fires a tray notification for each completed agent turn. Only
            raised while this tab is hidden or unfocused.
          {:else}
            Off — enable to see a tray notification when a turn completes.
          {/if}
        </p>
      </div>

      {#if saveError}
        <p
          class="rounded border border-rose-800 bg-rose-950/40 px-3 py-2 text-xs text-rose-300"
          role="alert"
        >
          Save failed: {saveError}
        </p>
      {/if}

      <div class="flex items-center justify-end gap-2 pt-2">
        <button
          type="button"
          class="rounded bg-slate-800 hover:bg-slate-700 px-3 py-2 text-sm"
          onclick={onCancel}
          disabled={saving}
        >
          Cancel
        </button>
        <button
          type="submit"
          class="rounded bg-emerald-600 hover:bg-emerald-500 px-3 py-2 text-sm
            disabled:opacity-60 disabled:cursor-not-allowed"
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  </div>
{/if}
