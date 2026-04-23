import * as api from '$lib/api';
import { menuConfig } from '$lib/stores/menuConfig.svelte';

/**
 * Global billing-display mode. Fetched once from `/api/ui-config` at
 * boot and then treated as immutable for the lifetime of the tab — the
 * TOML knob only changes when Daisy restarts the server, and the
 * frontend reconnects on restart anyway. Two modes:
 *
 *   - `payg` (default): show dollar amounts. Matches the SDK's
 *     `ResultMessage.total_cost_usd`, which equals the developer-API
 *     bill for pay-as-you-go users.
 *   - `subscription`: show token totals. Max/Pro subscribers pay a
 *     flat rate, so dollar figures are meaningless for them; tokens
 *     correlate with the quota that actually depletes.
 *
 * The store also tracks a `loaded` flag so components can avoid
 * flashing the PAYG fallback before `/ui-config` responds — the delta
 * is short (local request), but visible on cold load.
 *
 * `/api/ui-config` is the single boot-time config endpoint; billing
 * owns the fetch and also pushes the parsed `context_menus` payload
 * into the `menuConfig` store so we don't duplicate the round-trip.
 */
class BillingStore {
  mode = $state<api.BillingMode>('payg');
  plan = $state<string | null>(null);
  loaded = $state(false);
  error = $state<string | null>(null);

  /** Fetch `/api/ui-config` and latch the mode. Idempotent — calling
   * twice (e.g. boot + re-boot after auth) repeats the fetch; each
   * response simply overwrites the fields. Errors don't block boot,
   * they just leave the default PAYG behavior in place. */
  async init(): Promise<void> {
    try {
      const cfg = await api.fetchUiConfig();
      this.mode = cfg.billing_mode;
      this.plan = cfg.billing_plan;
      // Fan out the parsed `menus.toml` overrides to the registry
      // consumer. Single fetch, two stores — avoids a duplicate
      // `/api/ui-config` round-trip on boot. A failure below
      // (caught) leaves menuConfig at its empty default, so the
      // registry still renders its built-in ordering.
      menuConfig.hydrate(cfg.context_menus);
      this.error = null;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      // Leave mode/plan at their current (defaulted) values so the
      // UI doesn't regress into an unusable state on a transient
      // /ui-config failure.
    } finally {
      this.loaded = true;
    }
  }

  /** Shorthand used by templates: `{#if billing.showTokens}...`. */
  get showTokens(): boolean {
    return this.mode === 'subscription';
  }
}

export const billing = new BillingStore();
