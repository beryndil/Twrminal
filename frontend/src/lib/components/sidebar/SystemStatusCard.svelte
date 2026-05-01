<script lang="ts">
  /**
   * Sidebar System Status card — Phase 2c of the v1.0.0 dashboard
   * redesign. Aggregates the always-on health signals into a single
   * card so the user can glance at sidebar-bottom and see "is
   * everything OK?" without hunting through other surfaces.
   *
   * Two lines, each a colored dot + label:
   *   ● Connection — derived from `agent.state` (open/connecting/closed)
   *   ● Claude reachable — same source today (the agent connection IS
   *     the Claude connection); kept as a separate line because they
   *     can diverge once we expose model-fallback state on the wire
   *
   * The mockup also showed a "Last sync: 2m ago" line, but the
   * version watcher doesn't expose a last-check timestamp today
   * (it tracks build-token divergence, not poll wall-clock); rather
   * than invent a timestamp the card doesn't honestly know, the row
   * is omitted until `versionWatcher.lastChecked` (or equivalent)
   * lands.
   *
   * Status bar at the bottom of the viewport already shows
   * connection + recovery + auto-save in a single row; this card is
   * the *card-shaped* version for the sidebar surface — same signals,
   * different framing. The two are intentionally redundant: the
   * status bar is the always-visible at-a-glance check, this card
   * is the at-rest read for sidebar dwell.
   */
  import { agent } from '$lib/agent.svelte';

  type Status = 'ok' | 'warn' | 'down';

  let connectionStatus = $derived<Status>(
    agent.state === 'open' ? 'ok' : agent.state === 'connecting' ? 'warn' : 'down'
  );

  let connectionLabel = $derived(
    agent.state === 'open'
      ? 'Connected'
      : agent.state === 'connecting'
        ? 'Connecting…'
        : 'Disconnected'
  );
</script>

<div
  class="rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-xs"
  data-testid="system-status-card"
  aria-label="System status"
>
  <div class="mb-1.5 text-[10px] uppercase tracking-wider text-slate-500">System Status</div>
  <ul class="flex flex-col gap-1 text-slate-300">
    <li class="flex items-center gap-2" data-testid="system-status-connection">
      <span
        class="h-1.5 w-1.5 rounded-full
          {connectionStatus === 'ok'
          ? 'bg-accent-brand'
          : connectionStatus === 'warn'
            ? 'bg-amber-500'
            : 'bg-rose-500'}"
        aria-hidden="true"
      ></span>
      <span>{connectionLabel}</span>
    </li>
    <li class="flex items-center gap-2" data-testid="system-status-claude">
      <span
        class="h-1.5 w-1.5 rounded-full
          {connectionStatus === 'ok' ? 'bg-accent-brand' : 'bg-slate-600'}"
        aria-hidden="true"
      ></span>
      <span>Claude {connectionStatus === 'ok' ? 'reachable' : 'unreachable'}</span>
    </li>
  </ul>
</div>
