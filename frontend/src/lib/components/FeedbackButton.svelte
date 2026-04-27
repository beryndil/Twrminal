<script lang="ts">
  /** Compact "report an issue" button for the conversation header.
   *
   * Renders a small megaphone glyph that, on click, opens a GitHub
   * `/issues/new` URL pre-filled with the operator's environment
   * (Bearings version, browser UA, platform, language) plus a
   * steps-to-reproduce scaffold. Bearings does NOT POST any data
   * anywhere — the button only opens a github.com URL the user
   * manually submits. (Standards §17.)
   *
   * Two callers today:
   *   - `ConversationHeader.svelte` — the inline header icon button
   *     this component is tuned for. Same density as the edit /
   *     export / copy / merge / analyze / close cluster.
   *   - `settings/sections/HelpSection.svelte` — the Settings > Help
   *     pane uses `SettingsLink` rows directly; it shares the URL
   *     builder via `$lib/utils/feedback` rather than embedding a
   *     button. This component therefore stays single-purpose.
   *
   * The version is fetched via `/api/version` only at click time,
   * not on mount. We don't want this button — which is rendered on
   * every conversation header — to fire an extra request on every
   * session switch. The first click pays the latency once; the
   * cached promise serves any subsequent clicks instantly.
   */
  import { fetchVersion } from '$lib/api/version';
  import { buildFeedbackUrl, composeEnv, type FeedbackKind } from '$lib/utils/feedback';

  interface Props {
    /** Which issue template the URL targets. Default 'bug' — the
     * header button is pitched as the bug-report entry point;
     * feature requests go through Settings > Help. */
    kind?: FeedbackKind;
    /** Tailwind size class for the icon. Default 'h-3.5 w-3.5' to
     * match the existing header glyphs. */
    sizeClass?: string;
  }

  let { kind = 'bug', sizeClass = 'h-3.5 w-3.5' }: Props = $props();

  /** Memoize the version-fetch promise so repeated clicks don't
   * re-hit `/api/version`. Wrapped in a function so the request
   * doesn't fire until the first click. */
  let versionPromise: ReturnType<typeof fetchVersion> | null = null;

  async function onClick(): Promise<void> {
    if (versionPromise === null) {
      versionPromise = fetchVersion();
    }
    let info: { version: string; build: string | null } | null = null;
    try {
      info = await versionPromise;
    } catch {
      // /api/version unreachable — fall through with null. The
      // builder fills in 'unknown' and the user can still file the
      // report. Reset the cached promise so a transient network
      // blip doesn't poison every future click.
      versionPromise = null;
    }
    const env = composeEnv(info);
    const url = buildFeedbackUrl(kind, env);
    // `noopener,noreferrer` prevents the opened tab from peeking at
    // window.opener. Standards §11 (security defaults for external
    // links) + §17 (no telemetry leakage).
    window.open(url, '_blank', 'noopener,noreferrer');
  }

  const label = $derived(
    kind === 'bug' ? 'Report a bug on GitHub' : 'Request a feature on GitHub'
  );
</script>

<button
  type="button"
  class="text-xs text-slate-500 hover:text-slate-300"
  aria-label={label}
  title={label}
  onclick={onClick}
  data-testid="feedback-button"
>
  <!-- Hand-rolled megaphone glyph. ViewBox 0 0 16 16 to match the
       other icons in this folder; stroke-based so it picks up the
       header's currentColor styling. -->
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 16 16"
    class="inline-block shrink-0 {sizeClass}"
    fill="none"
    stroke="currentColor"
    stroke-width="1.4"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M2 6.5 L2 9.5 L4 9.5 L10.5 12.5 L10.5 3.5 L4 6.5 Z" />
    <path d="M11 6 L13.5 5" />
    <path d="M11 8 L13.7 8" />
    <path d="M11 10 L13.5 11" />
    <path d="M5 9.7 L5.5 13 L7 13 L6.7 10.4" />
  </svg>
</button>
