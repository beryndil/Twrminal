<script lang="ts">
  /** Privacy section — surfaces the operator-facing data-handling
   * promise the project's TELEMETRY.md commits to.
   *
   * Three rows:
   *   1. "Your data stays on this device" — the headline statement.
   *      Paired with a link to TELEMETRY.md on GitHub for the full
   *      acknowledgment + provider list.
   *   2. "Data directory" — the resolved XDG data home, fetched from
   *      `/api/health` so it reflects the actual `XDG_DATA_HOME` of
   *      the running server (rather than guessing `~/.local/share`).
   *      Trailing button:
   *        - When the host's `shell.file_explorer_command` is
   *          configured, posts to `/api/shell/open` and the OS file
   *          manager opens the directory.
   *        - When unconfigured (server returns 400), falls back to
   *          copying the path to the clipboard so the user can paste
   *          into a terminal. The browser sandbox refuses to open
   *          file:// URIs from JS, so the server-side dispatcher is
   *          the only honest path; the clipboard copy is the safety
   *          net the executor plug calls for.
   *
   * The section never PATCHes anything — rows are read-only or
   * action-only — so we don't carry a per-row save state. */
  import SettingsCard from '../SettingsCard.svelte';
  import SettingsDivider from '../SettingsDivider.svelte';
  import SettingsLink from '../SettingsLink.svelte';
  import SettingsRow from '../SettingsRow.svelte';
  import { fetchHealth } from '$lib/api/core';
  import { openShell } from '$lib/api/shell';

  /** Public source for the telemetry acknowledgment. The repo URL is
   * stable across releases; pointing at `main` ensures the user lands
   * on the latest version without a tag-bump per release. */
  const TELEMETRY_URL = 'https://github.com/Beryndil/Bearings/blob/main/TELEMETRY.md';

  let dataDir = $state<string | null>(null);
  let error = $state<string | null>(null);
  let openState = $state<
    | { kind: 'idle' }
    | { kind: 'opening' }
    | { kind: 'copied'; path: string }
    | { kind: 'error'; message: string }
  >({ kind: 'idle' });

  $effect(() => {
    fetchHealth()
      .then((h) => {
        dataDir = h.data_dir;
      })
      .catch((err: unknown) => {
        error = err instanceof Error ? err.message : String(err);
      });
  });

  /** Try the configured file-explorer dispatcher; fall back to
   * clipboard on a 400 (host command not configured). 400 carries the
   * config key name verbatim so we can surface it if the clipboard
   * fallback also fails. */
  async function openDataDir(): Promise<void> {
    if (!dataDir) return;
    openState = { kind: 'opening' };
    try {
      await openShell('file_explorer', dataDir);
      openState = { kind: 'idle' };
    } catch (err) {
      // Browsers cannot open `file://` paths from script — the only
      // honest fallback is to give the user the path so they can
      // paste it into a terminal or file manager themselves.
      try {
        await navigator.clipboard.writeText(dataDir);
        openState = { kind: 'copied', path: dataDir };
      } catch (clipErr) {
        const msg =
          err instanceof Error
            ? err.message
            : clipErr instanceof Error
              ? clipErr.message
              : 'Could not open or copy the data directory.';
        openState = { kind: 'error', message: msg };
      }
    }
  }
</script>

<div class="flex flex-col gap-4" data-testid="settings-section-privacy">
  <SettingsCard>
    <SettingsRow
      title="Your data stays on this device"
      description="Bearings makes no analytics, crash-report, or telemetry calls. The
        only outbound traffic is the Claude API, with your own credentials. See
        TELEMETRY.md for the full acknowledgment."
    >
      {#snippet control()}
        <a
          href={TELEMETRY_URL}
          target="_blank"
          rel="noopener noreferrer"
          class="text-sm text-sky-400 hover:text-sky-300 hover:underline
            focus:outline-none focus:underline"
          data-testid="settings-privacy-telemetry"
        >
          TELEMETRY.md ↗
        </a>
      {/snippet}
    </SettingsRow>

    <SettingsDivider inset />

    <SettingsRow
      title="Data directory"
      description={dataDir ??
        (error
          ? `Could not reach /api/health: ${error}`
          : 'Resolving from /api/health…')}
    >
      {#snippet control()}
        <button
          type="button"
          class="text-sm text-sky-400 hover:text-sky-300 hover:underline
            focus:outline-none focus:underline disabled:opacity-50
            disabled:cursor-not-allowed"
          disabled={!dataDir || openState.kind === 'opening'}
          onclick={openDataDir}
          data-testid="settings-privacy-open-data-dir"
        >
          {#if openState.kind === 'opening'}
            Opening…
          {:else if openState.kind === 'copied'}
            Path copied
          {:else}
            Open data dir
          {/if}
        </button>
      {/snippet}
      {#snippet footnote()}
        {#if openState.kind === 'copied'}
          File explorer not configured — copied
          <code class="font-mono">{openState.path}</code> to the clipboard.
          Set <code class="font-mono">shell.file_explorer_command</code> in
          <code class="font-mono">config.toml</code> to open it directly.
        {:else if openState.kind === 'error'}
          <span class="text-rose-400" role="alert">{openState.message}</span>
        {/if}
      {/snippet}
    </SettingsRow>
  </SettingsCard>
</div>
