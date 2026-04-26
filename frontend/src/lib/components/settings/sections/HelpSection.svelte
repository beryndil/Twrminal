<script lang="ts">
  /** Help section — central jump-off point for the in-app reference
   * material the operator needs while running the app.
   *
   * Three rows:
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
   *
   * No autosaving controls — every row is link-or-action only. */
  import SettingsCard from '../SettingsCard.svelte';
  import SettingsDivider from '../SettingsDivider.svelte';
  import SettingsLink from '../SettingsLink.svelte';
  import { uiActions } from '$lib/stores/ui_actions.svelte';

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
  </SettingsCard>
</div>
