<script lang="ts">
  /**
   * System routing rules section — wraps ``RoutingRuleEditor`` (kind="system").
   * Extracted from ``+page.svelte`` as part of gap-cycle-07-007.
   */
  import type { SaveStatus } from "../sections.js";
  import RoutingRuleEditor from "$lib/components/routing/RoutingRuleEditor.svelte";
  import { ROUTING_RULES_SECTION_STRINGS } from "$lib/config.js";

  interface Props {
    onsaveStatus?: (status: SaveStatus) => void;
  }

  // The RoutingRuleEditor manages its own save state internally.
  const { onsaveStatus: _onsaveStatus }: Props = $props();
</script>

<section class="settings-page__group" aria-label={ROUTING_RULES_SECTION_STRINGS.ariaLabel}>
  <h2 class="settings-page__heading">{ROUTING_RULES_SECTION_STRINGS.heading}</h2>
  <p class="settings-page__lede">
    {ROUTING_RULES_SECTION_STRINGS.lede}
  </p>
  <RoutingRuleEditor kind="system" />
</section>
