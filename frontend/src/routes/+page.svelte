<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import AuthGate from '$lib/components/AuthGate.svelte';
  import CheatSheet from '$lib/components/CheatSheet.svelte';
  import ChecklistView from '$lib/components/ChecklistView.svelte';
  import Conversation from '$lib/components/Conversation.svelte';
  import Inspector from '$lib/components/Inspector.svelte';
  import SessionList from '$lib/components/SessionList.svelte';
  import { agent } from '$lib/agent.svelte';
  import { auth } from '$lib/stores/auth.svelte';
  import { billing } from '$lib/stores/billing.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { sessionsWs } from '$lib/stores/ws_sessions.svelte';
  import { tags } from '$lib/stores/tags.svelte';

  let booted = $state(false);
  let showCheatSheet = $state(false);

  async function boot() {
    if (booted) return;
    booted = true;
    // billing.init fetches /ui-config so the header and session cards
    // know whether to render dollars (PAYG) or token totals
    // (subscription). Run alongside the other boot fetches — a
    // failure here leaves the PAYG default in place, it does not
    // block boot.
    await Promise.all([billing.init(), sessions.refresh(), tags.refresh()]);
    // Start the background runner poll so session rows flag which
    // sessions are still working even when you're on a different one.
    sessions.startRunningPoll();
    // Open the sessions-list broadcast channel. The poll above stays
    // in place as a belt-and-suspenders reconcile (slow subscriber
    // drops, broker hiccups) — this socket is the live path that
    // delivers upserts / deletes / runner-state transitions in
    // sub-second time. On connect / reconnect the WS fires one
    // softRefresh so nothing missed while the socket was down escapes.
    sessionsWs.connect();
    // v0.5.2: checklist sessions also connect — the ChecklistView
    // hosts an embedded chat panel and the backend runner accepts
    // kind='checklist' since the `checklist_overview` prompt layer
    // landed. No more kind-skip; both kinds take the same boot path.
    if (sessions.selectedId) {
      await agent.connect(sessions.selectedId);
    }
  }

  onMount(async () => {
    await auth.check();
    if (auth.status === 'open' || auth.status === 'ok') await boot();
  });

  // Re-trigger once the user clears the gate.
  $effect(() => {
    if ((auth.status === 'open' || auth.status === 'ok') && !booted) boot();
  });

  // Tab regained focus while a session is selected → stamp
  // `last_viewed_at` so the amber "finished but unviewed" dot clears
  // for the session the user just came back to. Gated on
  // `document.visibilityState` so a re-fire while the tab is still
  // hidden (some browsers emit a second event on certain transitions)
  // doesn't mark-viewed in the background.
  $effect(() => {
    function onVisibility() {
      if (document.visibilityState !== 'visible') return;
      const id = sessions.selectedId;
      if (!id) return;
      void sessions.markViewed(id);
    }
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  });

  // `?` toggles the cheat-sheet, but only when focus isn't in a form
  // field (so typing a literal "?" in the prompt still works). Esc
  // closes whether or not focus is in a field.
  $effect(() => {
    function onKey(e: KeyboardEvent) {
      const active = document.activeElement;
      const inField =
        active?.tagName === 'TEXTAREA' || active?.tagName === 'INPUT';
      if (e.key === '?' && !inField) {
        e.preventDefault();
        showCheatSheet = !showCheatSheet;
        return;
      }
      if (e.key === 'Escape' && showCheatSheet) {
        e.preventDefault();
        showCheatSheet = false;
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  });

  // Pane layout: draggable widths + collapse per side, persisted to
  // localStorage. Width=0 means collapsed; the handle stays visible so
  // the user can expand again. `lastLeft` / `lastRight` remember the
  // pre-collapse width so toggle restores it.
  const MIN_PANE_PX = 200;
  const DEFAULT_LEFT_PX = 280;
  const DEFAULT_RIGHT_PX = 320;
  const PANE_STORAGE_KEY = 'bearings:panes';

  type PaneState = {
    left: number;
    right: number;
    lastLeft: number;
    lastRight: number;
  };

  function loadPanes(): PaneState {
    // Inspector starts collapsed — `lastRight` seeds the toggle so the
    // first click opens to the default width instead of the minimum.
    const fallback: PaneState = {
      left: DEFAULT_LEFT_PX,
      right: 0,
      lastLeft: DEFAULT_LEFT_PX,
      lastRight: DEFAULT_RIGHT_PX
    };
    if (typeof localStorage === 'undefined') return fallback;
    try {
      const raw = localStorage.getItem(PANE_STORAGE_KEY);
      if (!raw) return fallback;
      const p = JSON.parse(raw) as Partial<PaneState>;
      return {
        left: typeof p.left === 'number' ? p.left : fallback.left,
        right: typeof p.right === 'number' ? p.right : fallback.right,
        lastLeft:
          typeof p.lastLeft === 'number' && p.lastLeft >= MIN_PANE_PX
            ? p.lastLeft
            : fallback.lastLeft,
        lastRight:
          typeof p.lastRight === 'number' && p.lastRight >= MIN_PANE_PX
            ? p.lastRight
            : fallback.lastRight
      };
    } catch {
      return fallback;
    }
  }

  const panes = $state<PaneState>(loadPanes());

  function savePanes() {
    try {
      localStorage.setItem(PANE_STORAGE_KEY, JSON.stringify(panes));
    } catch {
      // localStorage may be unavailable or quota'd; widths just don't persist.
    }
  }

  function startDrag(which: 'left' | 'right', e: MouseEvent) {
    e.preventDefault();
    const startX = e.clientX;
    const startW = which === 'left' ? panes.left : panes.right;
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';
    function onMove(ev: MouseEvent) {
      const dx = ev.clientX - startX;
      const raw = which === 'left' ? startW + dx : startW - dx;
      const maxW = Math.max(MIN_PANE_PX, Math.floor(window.innerWidth * 0.5));
      const clamped = Math.max(0, Math.min(maxW, raw));
      // Snap to collapsed below the minimum so the handle can't sit in
      // a half-visible dead zone.
      const next = clamped < MIN_PANE_PX ? 0 : clamped;
      if (which === 'left') panes.left = next;
      else panes.right = next;
    }
    function onUp() {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
      if (which === 'left' && panes.left > 0) panes.lastLeft = panes.left;
      if (which === 'right' && panes.right > 0) panes.lastRight = panes.right;
      savePanes();
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }

  function nudge(which: 'left' | 'right', deltaPx: number) {
    const maxW = Math.max(MIN_PANE_PX, Math.floor(window.innerWidth * 0.5));
    const current = which === 'left' ? panes.left : panes.right;
    // When collapsed, Arrow-Left/Right first expands to the minimum
    // rather than jumping the user into a partially-dragged state.
    const base = current === 0 ? MIN_PANE_PX - deltaPx : current;
    const raw = base + deltaPx;
    const clamped = Math.max(0, Math.min(maxW, raw));
    const next = clamped > 0 && clamped < MIN_PANE_PX ? MIN_PANE_PX : clamped;
    if (which === 'left') panes.left = next;
    else panes.right = next;
    if (next > 0) {
      if (which === 'left') panes.lastLeft = next;
      else panes.lastRight = next;
    }
    savePanes();
  }

  function onHandleKey(which: 'left' | 'right', e: KeyboardEvent) {
    // For the left handle, ArrowRight widens the sidebar; for the right
    // handle, ArrowLeft widens the inspector. Mirror the semantics so
    // the arrow always points toward "more space for the near pane".
    const widen = which === 'left' ? 'ArrowRight' : 'ArrowLeft';
    const narrow = which === 'left' ? 'ArrowLeft' : 'ArrowRight';
    const step = e.shiftKey ? 48 : 16;
    if (e.key === widen) {
      e.preventDefault();
      nudge(which, step);
    } else if (e.key === narrow) {
      e.preventDefault();
      nudge(which, -step);
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      togglePane(which);
    }
  }

  function togglePane(which: 'left' | 'right') {
    if (which === 'left') {
      if (panes.left > 0) {
        panes.lastLeft = panes.left;
        panes.left = 0;
      } else {
        panes.left = panes.lastLeft || DEFAULT_LEFT_PX;
      }
    } else {
      if (panes.right > 0) {
        panes.lastRight = panes.right;
        panes.right = 0;
      } else {
        panes.right = panes.lastRight || DEFAULT_RIGHT_PX;
      }
    }
    savePanes();
  }
</script>

<AuthGate />
<CheatSheet bind:open={showCheatSheet} />
<main
  class="grid h-full"
  style="grid-template-columns: {panes.left}px 6px minmax(0,1fr) 6px {panes.right}px"
>
  <div class="overflow-hidden">
    <SessionList />
  </div>
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div
    role="separator"
    aria-label="Resize sidebar"
    aria-orientation="vertical"
    tabindex="0"
    class="group relative cursor-col-resize bg-slate-800 hover:bg-slate-600 focus:outline-none focus:ring-2 focus:ring-sky-500"
    onmousedown={(e) => startDrag('left', e)}
    onkeydown={(e) => onHandleKey('left', e)}
  >
    <button
      type="button"
      class="absolute left-1/2 top-3 z-10 flex h-6 w-6 -translate-x-1/2 items-center justify-center rounded bg-slate-700 text-xs text-slate-200 opacity-60 hover:bg-slate-600 hover:opacity-100 group-hover:opacity-100"
      title={panes.left > 0 ? 'Collapse sidebar' : 'Expand sidebar'}
      onmousedown={(e) => e.stopPropagation()}
      onclick={() => togglePane('left')}
    >
      {panes.left > 0 ? '◂' : '▸'}
    </button>
  </div>
  {#if sessions.selected?.kind === 'checklist'}
    <ChecklistView />
  {:else}
    <Conversation />
  {/if}
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div
    role="separator"
    aria-label="Resize inspector"
    aria-orientation="vertical"
    tabindex="0"
    class="group relative cursor-col-resize bg-slate-800 hover:bg-slate-600 focus:outline-none focus:ring-2 focus:ring-sky-500"
    onmousedown={(e) => startDrag('right', e)}
    onkeydown={(e) => onHandleKey('right', e)}
  >
    <button
      type="button"
      class="absolute left-1/2 top-3 z-10 flex h-6 w-6 -translate-x-1/2 items-center justify-center rounded bg-slate-700 text-xs text-slate-200 opacity-60 hover:bg-slate-600 hover:opacity-100 group-hover:opacity-100"
      title={panes.right > 0 ? 'Collapse inspector' : 'Expand inspector'}
      onmousedown={(e) => e.stopPropagation()}
      onclick={() => togglePane('right')}
    >
      {panes.right > 0 ? '▸' : '◂'}
    </button>
  </div>
  <div class="overflow-hidden">
    <Inspector />
  </div>
</main>
