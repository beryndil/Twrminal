<script lang="ts">
  /**
   * System routing rules section — wraps ``RoutingRuleEditor`` (kind="system").
   * Extracted from ``+page.svelte`` as part of gap-cycle-07-007.
   */
  import type { SaveStatus } from "../sections.js";
  import RoutingRuleEditor from "$lib/components/routing/RoutingRuleEditor.svelte";

  interface Props {
    onsaveStatus?: (status: SaveStatus) => void;
  }

  // The RoutingRuleEditor manages its own save state internally.
  const { onsaveStatus: _onsaveStatus }: Props = $props();
</script>

<section class="settings-page__group" aria-label="System routing rules">
  <h2 class="settings-page__heading">System routing rules</h2>
  <p class="settings-page__lede">
    The system-wide rule set evaluated when no per-tag rule matches the routing-preview input. Per
    spec §3 priorities are sparse — drag rows to reorder, or duplicate-and-edit a row to slot a new
    rule between the seeded ones.
  </p>
  <RoutingRuleEditor kind="system" />
</section>
