<script lang="ts">
  /**
   * Sidebar bottom user identity block — Phase 2c of the v1.0.0
   * dashboard redesign. Displays who's signed in (display_name from
   * preferences, falling back to "Operator" when unset) alongside an
   * initials-avatar circle. Click opens the existing Settings modal
   * — same behavior as the gear nav item just above. The duplication
   * is deliberate: avatar-as-settings-target is a chat-app idiom
   * users reach for without thinking.
   *
   * The mockup also showed a plan badge ("Max Plan") under the name;
   * Bearings doesn't have a plan/tier concept (it's a localhost
   * developer tool, not a SaaS), so the second line shows the
   * working-mode label instead — "Localhost · Beryndil" — anchoring
   * the user in *where* they're connected rather than *what they're
   * paying for*.
   */
  import { preferences } from '$lib/stores/preferences.svelte';
  import { uiActions } from '$lib/stores/ui_actions.svelte';

  let displayName = $derived(preferences.displayName?.trim() || 'Operator');

  /** Two-character avatar from initials. Splits on whitespace +
   * picks the first letter of the first and last token; single-name
   * users get the first two letters of that name. ASCII-folded the
   * minimum amount needed for the common case — no full Unicode
   * normalization, since the avatar is decorative. */
  function initials(name: string): string {
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    return parts[0].slice(0, 2).toUpperCase();
  }

  let avatarText = $derived(initials(displayName));
  /** When the user has uploaded an avatar (`/api/preferences/avatar`)
   * the store carries the cache-busted URL; otherwise we render the
   * initials circle. Branching on `null` rather than truthiness so a
   * zero-length string (impossible by construction, but cheap to be
   * defensive) still falls back to initials instead of rendering a
   * broken `<img>`. */
  let avatarUrl = $derived(preferences.avatarUrl);
</script>

<button
  type="button"
  class="flex w-full items-center gap-2 rounded-md border border-slate-800
    bg-slate-900 px-2 py-1.5 text-left text-xs hover:border-slate-700
    hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500"
  onclick={() => (uiActions.settingsOpen = true)}
  data-testid="user-identity-block"
  aria-label="Open settings (signed in as {displayName})"
>
  {#if avatarUrl}
    <img
      src={avatarUrl}
      alt=""
      class="h-7 w-7 shrink-0 rounded-full object-cover"
      aria-hidden="true"
    />
  {:else}
    <span
      class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full
        bg-accent-brand/85 text-[10px] font-semibold text-white"
      aria-hidden="true"
    >
      {avatarText}
    </span>
  {/if}
  <span class="min-w-0 flex-1">
    <span class="block truncate text-sm font-medium text-slate-200">{displayName}</span>
    <span class="block truncate text-[10px] text-slate-500">Localhost</span>
  </span>
</button>
