<script lang="ts">
  /**
   * Sidebar navigation rail — Phase 2c of the v1.0.0 dashboard
   * redesign. Five vertical nav items below the brand + New Session
   * pill, mirroring the mockup:
   *
   *   ☰ Sessions   (always-on; routes to /, the sessions surface)
   *   ⌳ Tags       (placeholder route; tag manager lands later)
   *   ✦ Memories   (Phase 4 placeholder)
   *   ▎ Analytics  (Phase 6 placeholder)
   *   ⚙ Settings   (opens the existing Settings modal)
   *
   * Settings stays a modal rather than a route because the rest of
   * the app already deep-links to it via `?settings=<id>`; routing
   * it would invalidate every shareable settings link in the wild.
   *
   * Active state is computed from `$page.url.pathname`. Sessions is
   * active for `/` and any `/sessions/*` URL — the dashboard view
   * is the canonical "Sessions" surface; clicking the nav item from
   * inside a session takes you back to the dashboard root, which
   * matches the user's intuition that a top-level nav item should
   * feel like "go to the section landing page".
   *
   * Inline SVG icons (no lucide-svelte dep). 18×18 viewBox, stroke
   * 2, currentColor — they tint via the surrounding `text-*` class
   * so active vs idle vs hover all flow through Tailwind.
   *
   * Projects was deliberately omitted (decided 2026-04-29 — Tags
   * subsume the cross-cutting grouping use-case).
   */
  import { page } from '$app/stores';
  import { uiActions } from '$lib/stores/ui_actions.svelte';

  let pathname = $derived($page.url.pathname);

  /** Active rule: a nav item lights up when its href matches the
   * current path. Sessions is special — it's also active for any
   * `/sessions/*` URL because the dashboard *is* the sessions view. */
  function isActive(href: string): boolean {
    if (href === '/') return pathname === '/' || pathname.startsWith('/sessions');
    return pathname === href || pathname.startsWith(href + '/');
  }
</script>

<nav class="flex flex-col gap-0.5 px-1 py-1" aria-label="Primary" data-testid="sidebar-nav">
  <a
    href="/"
    data-testid="sidebar-nav-sessions"
    class="flex items-center gap-2 rounded px-2 py-1.5 text-sm transition-colors
      {isActive('/')
      ? 'bg-accent-brand-soft/40 text-accent-brand'
      : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}"
  >
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <line x1="8" y1="6" x2="21" y2="6"></line>
      <line x1="8" y1="12" x2="21" y2="12"></line>
      <line x1="8" y1="18" x2="21" y2="18"></line>
      <circle cx="3.5" cy="6" r="1.2" />
      <circle cx="3.5" cy="12" r="1.2" />
      <circle cx="3.5" cy="18" r="1.2" />
    </svg>
    Sessions
  </a>

  <a
    href="/tags"
    data-testid="sidebar-nav-tags"
    class="flex items-center gap-2 rounded px-2 py-1.5 text-sm transition-colors
      {isActive('/tags')
      ? 'bg-accent-brand-soft/40 text-accent-brand'
      : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}"
  >
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" />
      <circle cx="7" cy="7" r="1.2" fill="currentColor" stroke="none" />
    </svg>
    Tags
  </a>

  <a
    href="/memories"
    data-testid="sidebar-nav-memories"
    class="flex items-center gap-2 rounded px-2 py-1.5 text-sm transition-colors
      {isActive('/memories')
      ? 'bg-accent-brand-soft/40 text-accent-brand'
      : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}"
  >
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
    </svg>
    Memories
  </a>

  <a
    href="/analytics"
    data-testid="sidebar-nav-analytics"
    class="flex items-center gap-2 rounded px-2 py-1.5 text-sm transition-colors
      {isActive('/analytics')
      ? 'bg-accent-brand-soft/40 text-accent-brand'
      : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}"
  >
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <line x1="6" y1="20" x2="6" y2="14" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="18" y1="20" x2="18" y2="10" />
    </svg>
    Analytics
  </a>

  <button
    type="button"
    data-testid="sidebar-nav-settings"
    class="flex items-center gap-2 rounded px-2 py-1.5 text-left text-sm
      text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-200
      focus:outline-none focus:ring-2 focus:ring-sky-500"
    onclick={() => (uiActions.settingsOpen = true)}
    aria-haspopup="dialog"
  >
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="3" />
      <path
        d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3
          1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.8.3l-.1.1
          a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1
          A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3
          h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1
          a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1
          a1.7 1.7 0 0 0-1.5 1z"
      />
    </svg>
    Settings
  </button>
</nav>
