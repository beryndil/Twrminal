<script lang="ts">
  /**
   * Appearance section — theme picker + timezone selector.
   * Extracted from ``+page.svelte`` as part of gap-cycle-07-007.
   */
  import type { SaveStatus } from "../sections.js";
  import {
    KNOWN_DISPLAY_TIMEZONES,
    DISPLAY_TIMEZONE_LABELS,
    THEME_STRINGS,
    TIMEZONE_STRINGS,
    type DisplayTimezone,
  } from "$lib/config";
  import { displaySettingsStore, setTimezone } from "$lib/stores/displaySettings.svelte";
  import ThemePicker from "$lib/themes/ThemePicker.svelte";

  interface Props {
    onsaveStatus?: (status: SaveStatus) => void;
  }

  // Appearance writes go directly through the theme store / localStorage —
  // no explicit save button, so onsaveStatus is unused but declared for
  // registry uniformity.
  const { onsaveStatus: _onsaveStatus }: Props = $props();
</script>

<section class="settings-page__group" aria-label="Appearance">
  <h2 class="settings-page__heading">{THEME_STRINGS.appearanceHeading}</h2>
  <ThemePicker />

  <label class="settings-defaults__field" data-testid="settings-timezone-field">
    <span class="settings-defaults__label">{TIMEZONE_STRINGS.timezoneLabel}</span>
    <select
      class="settings-defaults__select"
      value={displaySettingsStore.timezone ?? "Auto"}
      onchange={(e) => {
        const v = (e.target as HTMLSelectElement).value as DisplayTimezone;
        setTimezone(v === "Auto" ? null : v);
      }}
      data-testid="settings-timezone-select"
    >
      {#each KNOWN_DISPLAY_TIMEZONES as tz (tz)}
        <option value={tz}>{DISPLAY_TIMEZONE_LABELS[tz]}</option>
      {/each}
    </select>
    <span class="settings-page__lede">{TIMEZONE_STRINGS.timezoneCaption}</span>
  </label>
</section>
