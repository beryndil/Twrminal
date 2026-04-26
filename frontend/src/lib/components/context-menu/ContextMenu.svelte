<script lang="ts">
  import { contextMenu } from '$lib/context-menu/store.svelte';
  import { placeAtCursor } from '$lib/context-menu/positioning';
  import { resolveMenu } from '$lib/context-menu/registry';
  import { isCoarsePointer } from '$lib/context-menu/touch';
  import type { Action, ActionContext } from '$lib/context-menu/types';
  import {
    INITIAL_STATE,
    reduce,
    type FSMEvent,
    type FSMItem,
    type ItemsSnapshot,
    type KeyboardState
  } from '$lib/context-menu/keyboard';
  import ContextMenuItem from './ContextMenuItem.svelte';

  // Default menu size used before the real container is measured.
  // Picked to match the Phase 1/2 action labels; Phase 2's anchored +
  // submenu flip math kicks in automatically once a real rect is
  // measured post-mount (future phases will re-place after measure).
  const DEFAULT_WIDTH_PX = 220;
  const DEFAULT_HEIGHT_PX = 48;

  let menuEl: HTMLElement | undefined = $state();
  let kbState = $state<KeyboardState>({ ...INITIAL_STATE });

  /** Bottom-sheet rendering for coarse pointers (spec §6.4). Latched
   * when the menu opens rather than re-checked on every render so a
   * late layout shift (virtual keyboard dismissing, etc.) doesn't
   * flicker the menu between cursor-anchored and sheet layouts mid-
   * session. Reset on close so a second open on a different device
   * (e.g. attached keyboard arrives) picks up the new pointer class. */
  let coarse = $state(false);
  $effect(() => {
    if (contextMenu.state.open) {
      coarse = isCoarsePointer();
    } else {
      coarse = false;
    }
  });

  // Resolve the menu spec only while open. Calling resolveMenu on a
  // null target is pointless and would force defensive branches below.
  const rendered = $derived.by(() => {
    const s = contextMenu.state;
    if (!s.open || s.target === null) return null;
    return resolveMenu(s.target, s.advanced);
  });

  /** Flat, section-order list of actions — indexes here match the
   * `data-flat-index` attribute on each ContextMenuItem. The FSM
   * operates on this flat list; sections are a visual grouping only. */
  const flat = $derived.by<Action[]>(() => {
    if (!rendered) return [];
    return rendered.groups.flatMap((g) => g.actions);
  });

  /** Items snapshot handed to the FSM reducer. Phase 2 menus have no
   * submenus, so the submenu list is empty — the FSM's submenu
   * branches stay fully tested but inactive until later phases wire
   * real submenu actions. */
  const itemsSnapshot = $derived.by<ItemsSnapshot>(() => ({
    main: flat.map(
      (a): FSMItem => ({
        mnemonic: a.mnemonic,
        disabled:
          contextMenu.state.target !== null &&
          a.disabled?.(contextMenu.state.target) !== null &&
          a.disabled?.(contextMenu.state.target) !== undefined,
        hasSubmenu: a.submenu !== undefined
      })
    ),
    submenu: []
  }));

  const placement = $derived.by(() => {
    const s = contextMenu.state;
    if (!s.open) return { left: 0, top: 0 };
    // Bottom-sheet layout anchors to the viewport edges via CSS; the
    // placement math only matters for cursor-anchored (mouse) menus.
    // Returning zeros here keeps the inline style harmless when the
    // coarse branch wins in the template below.
    if (coarse) return { left: 0, top: 0 };
    return placeAtCursor({
      x: s.x,
      y: s.y,
      menuWidth: menuEl?.offsetWidth ?? DEFAULT_WIDTH_PX,
      menuHeight: menuEl?.offsetHeight ?? DEFAULT_HEIGHT_PX,
      viewportWidth: typeof window === 'undefined' ? 0 : window.innerWidth,
      viewportHeight: typeof window === 'undefined' ? 0 : window.innerHeight
    });
  });

  // Reset keyboard state whenever the menu opens so stale focus from
  // a previous opening doesn't leak across sessions. Also focuses the
  // menu container so document keydown lands here first.
  $effect(() => {
    if (contextMenu.state.open) {
      kbState = { ...INITIAL_STATE };
      // Defer focus to the next frame so the DOM has mounted.
      queueMicrotask(() => menuEl?.focus());
    }
  });

  /** Apply the DOM-focus side effect after a state update. Uses
   * querySelector on a `data-flat-index` attr so we don't need a
   * ref map. */
  function syncFocus(next: KeyboardState): void {
    if (!menuEl) return;
    const idx = next.focusedIndex;
    if (idx < 0) {
      menuEl.focus();
      return;
    }
    const row = menuEl.querySelector<HTMLElement>(
      `[data-flat-index="${idx}"]`
    );
    row?.focus();
  }

  function ctxFor(): ActionContext {
    const s = contextMenu.state;
    return {
      target: s.target!,
      event: null,
      advanced: s.advanced
    };
  }

  async function activateIndex(idx: number): Promise<void> {
    const action = flat[idx];
    if (!action) return;
    const target = contextMenu.state.target;
    if (target === null) return;
    if (action.disabled?.(target)) return;
    try {
      await action.handler(ctxFor());
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('[context-menu] handler threw', action.id, err);
    } finally {
      contextMenu.close();
    }
  }

  /** Maps a DOM keydown to an FSM event. Returns null for keys the
   * reducer doesn't care about, so the caller can decide whether to
   * preventDefault. */
  function toEvent(e: KeyboardEvent): FSMEvent | null {
    switch (e.key) {
      case 'ArrowUp':
        return { type: 'ArrowUp' };
      case 'ArrowDown':
        return { type: 'ArrowDown' };
      case 'ArrowLeft':
        return { type: 'ArrowLeft' };
      case 'ArrowRight':
        return { type: 'ArrowRight' };
      case 'Home':
        return { type: 'Home' };
      case 'End':
        return { type: 'End' };
      case 'Enter':
        return { type: 'Enter' };
      case 'Escape':
        return { type: 'Escape' };
      default:
        if (e.key.length === 1 && /^[a-zA-Z0-9]$/.test(e.key)) {
          return { type: 'Mnemonic', char: e.key };
        }
        return null;
    }
  }

  /** True when the active element is an input/textarea/contentEditable
   * element OUTSIDE this menu. We use this to keep the menu's keyboard
   * handler from swallowing keystrokes that the user is clearly aiming
   * at a text field (the composer textarea after a slash-pick or
   * regenerate prefill, an open NewSessionForm input, the search box,
   * etc.). Without this guard, alphanumeric keystrokes hit the menu's
   * document-capture-phase preventDefault/stopPropagation and never
   * reach the field — the "text input dead until hard refresh" wedge
   * reported 2026-04-26. The visible-menu mitigation is paired with
   * the focusin listener below, which auto-closes the menu when focus
   * moves into one of these fields so the listener tears down. */
  function isEditableOutsideMenu(target: EventTarget | null): boolean {
    const el =
      (target instanceof HTMLElement ? target : null) ??
      (typeof document !== 'undefined'
        ? (document.activeElement as HTMLElement | null)
        : null);
    if (!el) return false;
    if (menuEl && menuEl.contains(el)) return false;
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') return true;
    if (el.isContentEditable) return true;
    return false;
  }

  $effect(() => {
    if (!contextMenu.state.open) return;
    function onKey(e: KeyboardEvent): void {
      // Defer to a focused text field outside the menu — see
      // `isEditableOutsideMenu`. The menu can still be dismissed via
      // Esc (handled by the keyboard registry's `handleEscape`, which
      // checks `contextMenu.state.open` first) or mousedown outside.
      if (isEditableOutsideMenu(e.target)) return;
      const event = toEvent(e);
      if (!event) return;
      e.preventDefault();
      e.stopPropagation();
      const result = reduce(kbState, event, itemsSnapshot);
      kbState = result.state;
      if (result.effect?.type === 'activate') {
        void activateIndex(result.effect.index);
        return;
      }
      if (result.effect?.type === 'close') {
        contextMenu.close();
        return;
      }
      // Phase 2 has no submenus wired — openSubmenu/closeSubmenu
      // effects are unreachable from the reducer given the current
      // snapshot (hasSubmenu is always false). They remain tested in
      // keyboard.test.ts for future phases.
      syncFocus(result.state);
    }
    function onClick(e: MouseEvent): void {
      const target = e.target as Node | null;
      if (target && menuEl && menuEl.contains(target)) return;
      contextMenu.close();
    }
    /** Auto-close on focus shift to an editable field outside the
     * menu. Programmatic `.focus()` calls (slash-command pick,
     * `bearings:composer-prefill` from the regenerate flow,
     * `attachFileAtCursor`, etc.) don't fire mousedown, so the
     * outside-mousedown close path above doesn't catch them. Without
     * this, the menu would remain open in the background with its
     * capture-phase keydown listener still installed — even with the
     * `isEditableOutsideMenu` guard above keeping the keystrokes
     * alive, leaving an invisible-to-the-user menu open is a UX trap.
     * Closing here tears down the listener entirely. */
    function onFocusIn(e: FocusEvent): void {
      if (isEditableOutsideMenu(e.target)) {
        contextMenu.close();
      }
    }
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('mousedown', onClick);
    document.addEventListener('focusin', onFocusIn);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('focusin', onFocusIn);
    };
  });

  function onDone(): void {
    contextMenu.close();
  }

  // Suppress the browser's native menu on the menu itself — §spec
  // "No context menu on the menu itself."
  function onOwnContextMenu(e: MouseEvent): void {
    e.preventDefault();
  }

  /** Sections are flattened for the FSM, but the template still
   * groups them visually. This helper turns (groupIndex, itemIndex)
   * into the flat index that `data-flat-index` uses. */
  function flatIndex(groups: typeof rendered extends null ? never : NonNullable<typeof rendered>['groups'], gi: number, ii: number): number {
    let n = 0;
    for (let i = 0; i < gi; i++) n += groups[i]!.actions.length;
    return n + ii;
  }
</script>

<style>
  /* 44px minimum touch target per spec §6.4 / iOS HIG. Tailwind's
     default row padding is `py-1.5` which clocks in around 28px with
     the `text-xs` row label — too small for reliable thumb accuracy.
     Scope the bump to bottom-sheet mode so the desktop menu keeps its
     compact density. */
  :global([data-testid='context-menu'][data-coarse='true'] button[role='menuitem']) {
    min-height: 44px;
    padding-top: 0.625rem;
    padding-bottom: 0.625rem;
    font-size: 0.875rem; /* Tailwind `text-sm` — easier to read at arm's length. */
  }
</style>

{#if rendered}
  {#if coarse}
    <!-- Bottom-sheet backdrop — tapping outside the sheet closes the
         menu (same contract as the mouse menu's document-mousedown
         handler, but clearer on touch because the backdrop is opaque
         enough to signal that it's interactive). -->
    <button
      type="button"
      aria-label="Close menu"
      class="fixed inset-0 z-40 bg-slate-950/60"
      onclick={() => contextMenu.close()}
      oncontextmenu={onOwnContextMenu}
    ></button>
  {/if}
  <div
    bind:this={menuEl}
    role="menu"
    aria-label="Context menu"
    tabindex="-1"
    data-testid="context-menu"
    data-target-type={rendered.target.type}
    data-advanced={rendered.advanced}
    data-coarse={coarse}
    class={coarse
      ? 'fixed inset-x-0 bottom-0 z-50 max-h-[75vh] overflow-y-auto rounded-t-2xl border-t border-slate-700 bg-slate-900 py-2 text-slate-200 shadow-2xl touch-manipulation'
      : 'fixed z-50 min-w-[12rem] max-w-xs rounded border border-slate-700 bg-slate-900 shadow-xl py-1 text-slate-200'}
    style={coarse ? '' : `left: ${placement.left}px; top: ${placement.top}px;`}
    oncontextmenu={onOwnContextMenu}
  >
    {#if coarse}
      <!-- Drag handle affordance — purely decorative, the backdrop
           handles close. Keeps the sheet visually consistent with
           Android / iOS conventions. -->
      <div
        aria-hidden="true"
        class="mx-auto mb-2 h-1.5 w-12 rounded-full bg-slate-600"
      ></div>
    {/if}
    {#each rendered.groups as group, gi (group.section)}
      {#if gi > 0}
        <div class="my-1 h-px bg-slate-800" role="separator"></div>
      {/if}
      {#each group.actions as action, ii (action.id)}
        <ContextMenuItem
          {action}
          ctx={ctxFor()}
          {onDone}
          flatIndex={flatIndex(rendered.groups, gi, ii)}
        />
      {/each}
    {/each}
  </div>
{/if}
