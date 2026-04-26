<script lang="ts">
  /** About section — mirrors Spyglass-Android's
   * `about/AboutScreen.kt` hero treatment.
   *
   * Top-of-pane hero (centered column):
   *   1. App mark (BearingsMark at 64px)
   *   2. App title — "Bearings"
   *   3. Release version — "v0.20.6", from /api/version's `version`
   *   4. Tagline — Bearings' one-line description
   *   5. "by Beryndil" — clickable, opens
   *      hardknocks.university/developer.html
   *   6. Photo of Beryndil — `/about_beryndil.png` (resized from
   *      Spyglass-Android's drawable to 320×307 / ~85 KB), rendered
   *      at 160 px square with 16px rounded corners and crop scale,
   *      same as the Compose treatment.
   *   7. Coffee CTA card — small "Enjoy Bearings?" eyebrow over a
   *      larger "Buy Me a Cup of Coffee" line, sky-accent
   *      background, rounded, click opens the same URL.
   *
   * Below the hero, a small SettingsCard with Build (mtime-derived)
   * and Repository link — operationally useful identity info that
   * the hero version line doesn't surface. Build also has a graceful
   * "dev build" fallback when `/api/version` returns `build: null`
   * (developer running the API without the static bundle built).
   */
  import SettingsCard from '../SettingsCard.svelte';
  import SettingsDivider from '../SettingsDivider.svelte';
  import SettingsLink from '../SettingsLink.svelte';
  import BearingsMark from '../../icons/BearingsMark.svelte';
  import { fetchVersion, type VersionInfo } from '$lib/api/version';

  const COFFEE_URL = 'https://hardknocks.university/developer.html';
  const TAGLINE = 'Localhost web UI for Claude Code agent sessions.';

  let info = $state<VersionInfo | null>(null);
  let error = $state<string | null>(null);

  /** Format the `build` token (nanosecond mtime) as a local
   * timestamp. `null` (no dist directory — dev) → 'dev build'.
   * Unparseable input → 'unknown'; the API contract promises a
   * numeric string but we don't trust silently. */
  function formatBuild(build: string | null): string {
    if (build === null) return 'dev build';
    const ns = Number(build);
    if (!Number.isFinite(ns) || ns <= 0) return 'unknown';
    const ms = Math.floor(ns / 1_000_000);
    return new Date(ms).toLocaleString();
  }

  $effect(() => {
    fetchVersion()
      .then((v) => {
        info = v;
      })
      .catch((err: unknown) => {
        error = err instanceof Error ? err.message : String(err);
      });
  });
</script>

<div class="flex flex-col gap-4" data-testid="settings-section-about">
  <!-- Hero block: mirrors Spyglass AboutScreen.kt's `app_info` item.
       Centered column. Sized to fit inside the dialog's content
       pane without scrolling — photo at 96px (was 160), BearingsMark
       at 40 (was 64), tightened gaps and padding. Treatment is
       still recognisably the Spyglass hero, just at desktop-modal
       density rather than mobile-fullscreen density. -->
  <div class="flex flex-col items-center pt-0 pb-1 gap-1">
    <BearingsMark size={40} label="Bearings" />

    <h3 class="text-lg font-semibold text-sky-400 mt-1">Bearings</h3>

    <p class="text-xs text-slate-400">
      {info ? `v${info.version}` : error ? 'version unavailable' : '…'}
    </p>

    <p class="text-xs text-slate-400">{TAGLINE}</p>

    <a
      href={COFFEE_URL}
      target="_blank"
      rel="noopener noreferrer"
      class="text-xs text-sky-400 hover:text-sky-300 hover:underline
        focus:outline-none focus:underline"
    >
      by Beryndil
    </a>

    <img
      src="/about_beryndil.png"
      alt="Beryndil"
      width="80"
      height="80"
      loading="lazy"
      class="mt-1 h-20 w-20 rounded-xl object-cover shadow-lg"
    />

    <a
      href={COFFEE_URL}
      target="_blank"
      rel="noopener noreferrer"
      class="mt-2 inline-flex flex-col items-center rounded-lg
        bg-sky-600 hover:bg-sky-500 transition-colors
        px-4 py-1.5 text-center
        focus:outline-none focus:ring-2 focus:ring-sky-300/60
        focus:ring-offset-2 focus:ring-offset-slate-900"
      data-testid="settings-coffee-cta"
    >
      <span class="text-[10px] text-sky-100 leading-tight">Enjoy Bearings?</span>
      <span class="text-sm font-semibold text-white leading-tight">
        Buy Me a Cup of Coffee
      </span>
    </a>

    <p class="mt-0.5 text-[10px] text-slate-500">Built in Winnfield, Louisiana.</p>
  </div>

  <!-- Identity card: build identifier + repo. Useful for bug reports
       and links the user actually clicks; the hero version is enough
       at-a-glance, this is the operational detail. -->
  <SettingsCard>
    <SettingsLink
      title="Build"
      description="Identifies the running frontend bundle. Bumps on every npm run build."
      trailing={info ? formatBuild(info.build) : error ? 'unavailable' : '…'}
    />
    <SettingsDivider inset />
    <SettingsLink
      title="Repository"
      description="Source, issues, and releases on GitHub."
      href="https://github.com/Beryndil/Bearings"
      trailing="Beryndil/Bearings ↗"
    />
  </SettingsCard>

  {#if error}
    <p class="text-xs text-rose-400" role="alert">
      Could not reach /api/version: {error}
    </p>
  {/if}
</div>
