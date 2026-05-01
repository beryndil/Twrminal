<script lang="ts">
  /**
   * Accent cards above the chat — Phase 2b of the v1.0.0 dashboard
   * redesign.
   *
   * The mockup placed two summary badges between the session header
   * and the message list, framing always-on Bearings value-adds the
   * user might otherwise not notice:
   *
   *   ┌─ ✓ Saved 38% tokens ──┐  ┌─ 🛡 Recovery armed ────────┐
   *   │ 2.1M vs 3.4M cached    │  │ Up to 5000 events buffered │
   *   └────────────────────────┘  └────────────────────────────┘
   *
   * The card values are computed from data Bearings already has:
   *
   *   Card 1 — token caching savings.
   *     Anthropic's prompt cache prices `cache_read_tokens` at ~10%
   *     of base input cost. We compute "tokens saved by caching" as
   *     `cache_read * 0.9` (i.e. the 90% discount applied to the
   *     cached portion) and express it as a percentage of the total
   *     input that *would* have been billed at full price without
   *     caching (input + cache_creation + cache_read). Suppressed
   *     until the session has at least one cached token — a fresh
   *     session shouldn't shout "0% saved" at the user.
   *
   *   Card 2 — recovery capability.
   *     The mockup version showed a per-session count ("Recovered 3
   *     actions"); that requires a server-side reconnect-count event
   *     that doesn't exist yet (deferred to a follow-up phase). The
   *     honest version names the *mechanism*: every session is backed
   *     by a 5000-event ring buffer that replays after a disconnect,
   *     so the user knows the safety net is on without us inventing a
   *     fake counter.
   *
   * Layout: flex-wrap so the two cards stack on narrow center
   * columns rather than overflowing horizontally. The whole strip is
   * suppressed when no session is selected (avoids a half-empty
   * banner above an empty-state pane).
   */
  import { sessions } from '$lib/stores/sessions.svelte';
  import { conversation } from '$lib/stores/conversation.svelte';
  import * as api from '$lib/api';

  let totals = $state<api.TokenTotals | null>(null);
  let prevStreaming = false;

  $effect(() => {
    const sid = sessions.selected?.id ?? null;
    if (!sid) {
      totals = null;
      return;
    }
    api.getSessionTokens(sid).then(
      (r) => {
        if (sessions.selected?.id === sid) totals = r;
      },
      () => {
        // /tokens failing leaves the prior totals (or null) in place;
        // the card simply doesn't render. No visible error — the
        // accent strip is decorative, not critical.
      }
    );
  });

  // Refresh when a streaming turn completes — same edge-trigger
  // pattern ConversationHeader uses for its subscription token meter,
  // so the card updates in lockstep with the cost line above.
  $effect(() => {
    const active = conversation.streamingActive;
    const sid = sessions.selected?.id ?? null;
    if (!sid) {
      prevStreaming = active;
      return;
    }
    if (prevStreaming && !active) {
      api.getSessionTokens(sid).then(
        (r) => {
          if (sessions.selected?.id === sid) totals = r;
        },
        () => {}
      );
    }
    prevStreaming = active;
  });

  /** Token caching savings derivation. Returns null when there's
   * nothing meaningful to render (no totals fetched yet, or this
   * session has zero cached tokens). */
  function savings(t: api.TokenTotals | null): {
    pct: number;
    cached: number;
    potential: number;
  } | null {
    if (!t) return null;
    if (t.cache_read_tokens <= 0) return null;
    const potential = t.input_tokens + t.cache_creation_tokens + t.cache_read_tokens;
    if (potential <= 0) return null;
    const saved = t.cache_read_tokens * 0.9;
    const pct = Math.round((saved / potential) * 100);
    return { pct, cached: t.cache_read_tokens, potential };
  }

  /** Compact human-friendly token count: 2_100_000 → "2.1M",
   * 12_800 → "12.8k", 950 → "950". Mirrors the format the mockup
   * uses on the Session Metrics card. */
  function fmt(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k';
    return String(n);
  }

  let saved = $derived(savings(totals));
</script>

{#if sessions.selected}
  <div
    class="flex flex-wrap gap-2 border-b border-slate-800 px-4 py-2 {saved ? '' : 'justify-center'}"
    data-testid="accent-cards"
    aria-label="Session summary highlights"
  >
    {#if saved}
      <div
        class="flex min-w-[14rem] flex-1 items-center gap-3 rounded-md border
          border-slate-800 bg-slate-900 px-3 py-2"
        data-testid="accent-card-saved"
      >
        <span
          class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full
            bg-emerald-900/60 text-emerald-300"
          aria-hidden="true">✓</span
        >
        <div class="min-w-0">
          <div class="text-xs font-medium text-slate-200">
            Saved {saved.pct}% tokens
          </div>
          <div class="font-mono text-[11px] text-slate-500">
            {fmt(saved.cached)} of {fmt(saved.potential)} cached
          </div>
        </div>
      </div>
    {/if}

    <div
      class="flex min-w-[14rem] items-center gap-3 rounded-md border
        border-slate-800 bg-slate-900 px-3 py-2 {saved ? 'flex-1' : 'max-w-md'}"
      data-testid="accent-card-recovery"
    >
      <span
        class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full
          bg-indigo-900/60 text-indigo-300"
        aria-hidden="true"
      >
        <!--
          Inline shield SVG. The previous glyph ⛨ (U+26E8) rendered as
          a tofu box on font stacks without a Symbola/Noto Symbols
          fallback (Hyprland with Inter as the default sans). The 14×14
          path traces a kite-shaped shield in `currentColor` so the
          existing indigo tint flows through unchanged and the icon
          stays crisp at any DPR.
        -->
        <svg
          viewBox="0 0 24 24"
          width="14"
          height="14"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M12 3 L20 6 L20 12 C20 17 16 20.5 12 21.5 C8 20.5 4 17 4 12 L4 6 Z" />
        </svg>
      </span>
      <div class="min-w-0">
        <div class="text-xs font-medium text-slate-200">Recovery armed</div>
        <div class="text-[11px] text-slate-500">Up to 5,000 events buffered for replay</div>
      </div>
    </div>
  </div>
{/if}
