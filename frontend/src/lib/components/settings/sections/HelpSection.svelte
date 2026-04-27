<script lang="ts">
  /** Help section — central jump-off point for the in-app reference
   * material the operator needs while running the app.
   *
   * Five rows:
   *   1. "Keyboard shortcuts" — opens the cheat-sheet overlay via the
   *      shared `uiActions` store. The same overlay is bound to the
   *      `?` chord by the keyboard registry, so this row is a
   *      mouse-friendly entry point with identical behavior. Closing
   *      the Settings dialog before opening the overlay is the right
   *      flow — Settings is z-index 40, the cheat sheet is z-index
   *      50, and overlapping overlays are bad UX.
   *   2. "README" — opens the GitHub repo's README in a new tab.
   *      Stable canonical link: `main`'s README is what the user is
   *      running close enough to, and we don't want a release-tag
   *      bump per release.
   *   3. "Docs" — opens the `docs/` directory on GitHub for deeper
   *      reference (checklists, context menu, themes, menus.toml).
   *      Same `main`-pinning rationale.
   *   4. "Report a bug" — opens GitHub's `/issues/new` with the
   *      `bug.yml` template, body prefilled with version + browser
   *      env + steps-to-reproduce scaffold. (Standards §17.)
   *   5. "Request a feature" — same channel, `feature.yml` template.
   *
   * Bearings does NOT POST anything anywhere on click — both
   * feedback rows just open a github.com URL the user manually
   * submits. (§17 forbids telemetry.)
   *
   * No autosaving controls — every row is link-or-action only. */
  import SettingsCard from '../SettingsCard.svelte';
  import SettingsDivider from '../SettingsDivider.svelte';
  import SettingsLink from '../SettingsLink.svelte';
  import { uiActions } from '$lib/stores/ui_actions.svelte';
  import { fetchVersion } from '$lib/api/version';
  import {
    buildFeedbackUrl,
    composeEnv,
    type FeedbackKind
  } from '$lib/utils/feedback';

  const README_URL = 'https://github.com/Beryndil/Bearings#readme';
  const DOCS_URL = 'https://github.com/Beryndil/Bearings/tree/main/docs';

  /** Open the cheat-sheet overlay. The Settings dialog watches
   * `uiActions.cheatSheetOpen` and closes itself when this flips —
   * mutually-exclusive overlays are the convention enforced by
   * `uiActions.openNewSession` / `openTemplatePicker`, and the
   * keyboard registry's Esc handler likewise closes overlays one at
   * a time. Setting the flag is the whole action; Settings reacts. */
  function showCheatSheet(): void {
    uiActions.cheatSheetOpen = true;
  }

  /** Build and open a prefilled GitHub `/issues/new` URL. Fetches
   * `/api/version` lazily — only on click — so opening Settings
   * doesn't fire a request. Network failure falls through to
   * version='unknown' so a transient blip doesn't block reporting. */
  async function openFeedback(kind: FeedbackKind): Promise<void> {
    let info: { version: string; build: string | null } | null = null;
    try {
      info = await fetchVersion();
    } catch {
      info = null;
    }
    const url = buildFeedbackUrl(kind, composeEnv(info));
    window.open(url, '_blank', 'noopener,noreferrer');
  }
</script>

<div class="flex flex-col gap-4" data-testid="settings-section-help">
  <SettingsCard>
    <SettingsLink
      title="Keyboard shortcuts"
      description="Opens the cheat sheet — same overlay you can summon any time with the ? key."
      onClick={showCheatSheet}
      trailing="Show ?"
    />
    <SettingsDivider inset />
    <SettingsLink
      title="README"
      description="Setup, build, and architecture overview on GitHub."
      href={README_URL}
      trailing="README ↗"
    />
    <SettingsDivider inset />
    <SettingsLink
      title="Documentation"
      description="In-repo reference for checklists, context menus, themes, and menus.toml."
      href={DOCS_URL}
      trailing="docs/ ↗"
    />
    <SettingsDivider inset />
    <SettingsLink
      title="Report a bug"
      description="Opens GitHub with environment and a steps-to-reproduce scaffold prefilled."
      onClick={() => openFeedback('bug')}
      trailing="New bug ↗"
    />
    <SettingsDivider inset />
    <SettingsLink
      title="Request a feature"
      description="Opens GitHub with a problem / proposal scaffold prefilled."
      onClick={() => openFeedback('feature')}
      trailing="New request ↗"
    />
  </SettingsCard>
</div>
