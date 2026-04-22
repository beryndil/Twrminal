<script lang="ts">
  import { contextMenu } from '$lib/context-menu/store.svelte';
  import { placeAtCursor } from '$lib/context-menu/positioning';
  import { resolveMenu } from '$lib/context-menu/registry';
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

  $effect(() => {
    if (!contextMenu.state.open) return;
    function onKey(e: KeyboardEvent): void {
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
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('mousedown', onClick);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      document.removeEventListener('mousedown', onClick);
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

{#if rendered}
  <div
    bind:this={menuEl}
    role="menu"
    aria-label="Context menu"
    tabindex="-1"
    data-testid="context-menu"
    data-target-type={rendered.target.type}
    data-advanced={rendered.advanced}
    class="fixed z-50 min-w-[12rem] max-w-xs rounded border border-slate-700
      bg-slate-900 shadow-xl py-1 text-slate-200"
    style="left: {placement.left}px; top: {placement.top}px;"
    oncontextmenu={onOwnContextMenu}
  >
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
