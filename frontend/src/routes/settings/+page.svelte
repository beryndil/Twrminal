<script lang="ts">
  /**
   * Settings page — Appearance section + System routing rules.
   *
   * Per ``docs/behavior/themes.md`` §"Theme picker UI" the Appearance
   * controls live here (theme picker today; future timezone /
   * density). Per ``docs/model-routing-v1-spec.md`` §10 "Modified:
   * Routing rule editor" the system-wide rule editor lives "under
   * settings" — surfaced as a second section below Appearance.
   *
   * Reachable via the ``/settings`` route. The center column of
   * ``+layout.svelte`` renders this page when no session is selected
   * (i.e. the ``children`` snippet branch).
   *
   * Closing-sweep audit (2026-05-02) — this page previously rendered
   * only ``<ThemePicker />`` despite the sidebar nav labelling it
   * "Settings". The system-rules section closes the gap that left
   * RoutingRuleEditor orphaned (only its own test imported it).
   */
  import { THEME_STRINGS } from "$lib/config";
  import ThemePicker from "$lib/themes/ThemePicker.svelte";
  import RoutingRuleEditor from "$lib/components/routing/RoutingRuleEditor.svelte";
</script>

<section class="settings-page" data-testid="settings-page" aria-label="Settings">
  <section class="settings-page__group" aria-label="Appearance">
    <h1 class="settings-page__heading">{THEME_STRINGS.appearanceHeading}</h1>
    <ThemePicker />
  </section>

  <section class="settings-page__group" aria-label="System routing rules">
    <h2 class="settings-page__heading">System routing rules</h2>
    <p class="settings-page__lede">
      The system-wide rule set evaluated when no per-tag rule matches the routing-preview input. Per
      spec §3 priorities are sparse — drag rows to reorder, or duplicate-and-edit a row to slot a
      new rule between the seeded ones.
    </p>
    <RoutingRuleEditor kind="system" />
  </section>
</section>

<style>
  .settings-page {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    padding: 1rem;
    max-width: 56rem;
    margin: 0 auto;
  }
  .settings-page__group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .settings-page__heading {
    font-size: 1.125rem;
    font-weight: 600;
    color: var(--fg-strong, #f3f4f6);
    margin: 0;
  }
  .settings-page__lede {
    font-size: 0.8125rem;
    color: var(--fg-muted, #888);
    margin: 0;
  }
</style>
