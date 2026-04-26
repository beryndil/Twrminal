<script lang="ts">
  /** Settings dialog — Spyglass-parity sectioned layout with the
   * accessibility floor every modal in this app should hit:
   *
   *   - Esc closes (document-level keydown so the listener doesn't
   *     depend on focus being inside the dialog)
   *   - Backdrop click closes
   *   - Tab is trapped inside the dialog; first/last focusable
   *     elements wrap to each other so focus can't escape into the
   *     background page
   *   - Focus is captured before open and restored on close, so
   *     keyboard users land back where they invoked the dialog from
   *   - On open, focus moves to the close button as a stable,
   *     unsurprising target (active rail tab is what's in tabindex=0
   *     on the rail; close is one Tab back from there)
   *   - Real `<IconX/>` glyph for the close button instead of the
   *     "✕" character, so high-contrast / screen-reader paths read
   *     it as a real button with an aria-label rather than an
   *     opaque unicode character
   *
   * Section bodies live in their own components under
   * `settings/sections/`. Every row autosaves; the footer carries a
   * cross-row indicator from `preferences.lastSaveStatus`. */
  import { tick } from 'svelte';
  import { preferences } from '$lib/stores/preferences.svelte';
  import { uiActions } from '$lib/stores/ui_actions.svelte';
  import SettingsShell from './settings/SettingsShell.svelte';
  import IconX from './icons/IconX.svelte';

  let { open = $bindable(false) }: { open?: boolean } = $props();

  /** The element that had focus when the dialog opened. We restore
   * focus here on close so keyboard users land back at the trigger. */
  let returnFocusTo: HTMLElement | null = null;
  /** Refs into the dialog for the focus trap. */
  let dialogEl: HTMLDivElement | undefined = $state();
  let closeButtonEl: HTMLButtonElement | undefined = $state();

  function onClose(): void {
    open = false;
  }

  /** Strip the `?settings=<id>` deep-link param when the dialog
   * closes. Leaves other params alone (so a Settings open from a
   * filtered sidebar URL doesn't clobber the filter). Dialog-open
   * state is the URL-controlling scope; the shell only writes the
   * value, the dialog owns the lifecycle. */
  function clearSettingsParam(): void {
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    if (!url.searchParams.has('settings')) return;
    url.searchParams.delete('settings');
    window.history.replaceState(window.history.state, '', url);
  }

  /** Backdrop click handler. The dialog surface stops propagation,
   * so a click that reaches `currentTarget` is genuinely on the
   * backdrop. */
  function onBackdrop(e: MouseEvent): void {
    if (e.target === e.currentTarget) onClose();
  }

  /** Focus-trap key handler. Tab on the last focusable wraps to the
   * first; Shift+Tab on the first wraps to the last. Esc closes. */
  function onKey(e: KeyboardEvent): void {
    if (!open) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key !== 'Tab' || !dialogEl) return;
    const focusables = Array.from(
      dialogEl.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      )
    ).filter((el) => !el.hasAttribute('disabled') && el.offsetParent !== null);
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  // Capture / restore focus + initial focus move. The effect's
  // dependency on `open` runs the body when the value flips. Splitting
  // the open and close branches keeps the lifecycle obvious.
  $effect(() => {
    if (open) {
      returnFocusTo = document.activeElement as HTMLElement | null;
      // After the dialog mounts, move focus to the close button so
      // Tab cycles forward into the nav rail and content. tick()
      // waits a microtask so `closeButtonEl` is bound.
      void tick().then(() => closeButtonEl?.focus());
    } else if (returnFocusTo) {
      returnFocusTo.focus();
      returnFocusTo = null;
      clearSettingsParam();
    }
  });

  // Mutually-exclusive overlays: when the cheat sheet opens (e.g. from
  // Help → "Show keyboard shortcuts", or the `?` chord while the
  // dialog is up), close the Settings dialog so we don't stack two
  // modals. Same convention `uiActions.openNewSession` / `openTemplatePicker`
  // enforce for sidebar overlays.
  $effect(() => {
    if (uiActions.cheatSheetOpen && open) {
      open = false;
    }
  });
</script>

<svelte:window onkeydown={onKey} />

{#if open}
  <div
    class="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/80 p-4"
    role="presentation"
    onclick={onBackdrop}
    data-testid="settings-backdrop"
  >
    <div
      bind:this={dialogEl}
      class="w-full max-w-3xl rounded-lg border border-slate-800 bg-slate-900 shadow-2xl
        flex flex-col"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-dialog-title"
      data-testid="settings-dialog"
    >
      <header
        class="flex items-start justify-between px-6 py-4 border-b border-slate-800"
      >
        <div>
          <h2 id="settings-dialog-title" class="text-lg font-medium">Settings</h2>
          <p class="text-xs text-slate-400 mt-1">
            Changes save automatically. Auth token stays on this device.
          </p>
        </div>
        <button
          bind:this={closeButtonEl}
          type="button"
          class="text-slate-500 hover:text-slate-300 p-1 rounded
            focus:outline-none focus:ring-2 focus:ring-sky-500/60"
          aria-label="Close settings"
          onclick={onClose}
          data-testid="settings-close"
        >
          <IconX size={16} />
        </button>
      </header>

      <SettingsShell />

      <footer
        class="px-6 py-2 border-t border-slate-800 text-xs min-h-[2rem]
          flex items-center"
        data-testid="settings-footer"
      >
        {#if preferences.lastSaveStatus.kind === 'saving'}
          <span class="text-slate-400 italic" role="status" aria-live="polite">
            Saving…
          </span>
        {:else if preferences.lastSaveStatus.kind === 'saved'}
          <span class="text-emerald-400" role="status" aria-live="polite">
            All changes saved
          </span>
        {:else if preferences.lastSaveStatus.kind === 'error'}
          <span class="text-rose-400" role="alert">
            Failed to save: {preferences.lastSaveStatus.error}
          </span>
        {:else}
          <span class="text-slate-600">Ready.</span>
        {/if}
      </footer>
    </div>
  </div>
{/if}
