<script lang="ts" module>
  import type { MenuTargetId as ModuleMenuTargetId } from "../config";
  import { actionsForTarget as moduleActionsForTarget } from "./registry";
  import type { MenuActionDescriptor as ModuleMenuActionDescriptor } from "./registry";

  /**
   * Stateless helper — flat-index of an action inside the grouped
   * structure. Used by keyboard-nav highlight.
   */
  export function computeFlatIndex(
    grouped: Array<{ section: string; actions: readonly ModuleMenuActionDescriptor[] }> | null,
    section: string,
    actionIndex: number,
  ): number {
    if (grouped === null) return -1;
    let count = 0;
    for (const group of grouped) {
      if (group.section === section) return count + actionIndex;
      count += group.actions.length;
    }
    return -1;
  }

  /** Stateless helper — whether the per-target list has any advanced rows. */
  export function hasAdvanced(target: ModuleMenuTargetId): boolean {
    return moduleActionsForTarget(target).some((a) => a.advanced === true);
  }
</script>

<script lang="ts">
  /**
   * Floating context-menu component — renders the per-target action
   * list when :data:`contextMenuStore.open` is set.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/context-menus.md`` §"Common behavior" —
   *   sectioning order, advanced reveal, destructive confirmation,
   *   keyboard navigation, Esc / outside-click close.
   * - §"Failure modes" — stale target renders every action greyed
   *   with the "this object no longer exists" caption.
   *
   * Rendered once at the app shell; consumers do not import this —
   * they wire ``use:contextMenu`` from :file:`actions/contextMenu.ts`
   * which dispatches through the store.
   */
  import { onMount } from "svelte";

  import { CONTEXT_MENU_STRINGS, MENU_SECTION_ORDER, type MenuSectionId } from "../config";
  import { ESC_PRIORITY_CONTEXT_MENU, registerEscEntry } from "../keyboard/escCascade";
  import { actionsForTarget, type MenuActionDescriptor } from "./registry";
  import { closeMenu, contextMenuStore } from "./store.svelte";

  const open = $derived(contextMenuStore.open);

  /**
   * The actions to render — filtered by advanced visibility, grouped
   * by section, ordered by :data:`MENU_SECTION_ORDER`. ``null`` when
   * no menu is open.
   */
  const grouped = $derived.by(() => {
    if (open === null) return null;
    const all = actionsForTarget(open.target);
    const visible = all.filter((a) => a.advanced !== true || open.advancedRevealed);
    const buckets = new Map<MenuSectionId, MenuActionDescriptor[]>();
    for (const action of visible) {
      const list = buckets.get(action.section) ?? [];
      list.push(action);
      buckets.set(action.section, list);
    }
    return MENU_SECTION_ORDER.map((section) => ({
      section,
      actions: buckets.get(section) ?? [],
    })).filter((g) => g.actions.length > 0);
  });

  let highlightIndex = $state(0);

  /** Flat list — used for keyboard nav (Up / Down across sections). */
  const flatActions = $derived(grouped?.flatMap((g) => g.actions) ?? []);

  /**
   * Ref to the ``<ul role="menu">`` element — used by :func:`syncFocus`
   * to query ``<li role="menuitem">`` rows and call ``.focus()`` on the
   * target row after each navigation step.
   */
  let menuContainerRef: HTMLUListElement | null = $state(null);

  /**
   * The element that held DOM focus when the menu opened. Restored on
   * close (best-effort — only HTMLElement targets can receive focus).
   */
  let savedFocus: Element | null = null;

  $effect(() => {
    if (open !== null) {
      savedFocus = document.activeElement;
      highlightIndex = 0;
      syncFocus(0);
    } else {
      if (savedFocus instanceof HTMLElement) {
        savedFocus.focus();
      }
      savedFocus = null;
    }
  });

  /**
   * Moves DOM focus to the ``<li role="menuitem">`` at ``index`` inside
   * the open menu. Falls back to the container itself when no action
   * rows exist (e.g. a stale-target menu with every row stripped).
   */
  function syncFocus(index: number): void {
    if (menuContainerRef === null) return;
    const rows = menuContainerRef.querySelectorAll<HTMLElement>('li[role="menuitem"]');
    if (rows.length === 0) {
      menuContainerRef.focus();
      return;
    }
    const row = rows[index];
    if (row !== undefined) row.focus();
  }

  function actionLabel(id: string): string {
    const labels = CONTEXT_MENU_STRINGS.actionLabels as Record<string, string>;
    return labels[id] ?? id;
  }

  /**
   * Returns the mnemonic character for an action (lower-case). Uses the
   * explicit ``action.mnemonic`` when set; otherwise derives from the first
   * alphanumeric character of the localised label.
   */
  function mnemonicChar(action: MenuActionDescriptor): string | null {
    if (action.mnemonic !== undefined) {
      return action.mnemonic.toLowerCase();
    }
    const label = actionLabel(action.id);
    const match = label.match(/[a-zA-Z0-9]/);
    return match ? match[0]!.toLowerCase() : null;
  }

  /**
   * Splits a label into three parts around the mnemonic character so the
   * template can render the mnemonic glyph underlined. Returns ``null`` when
   * no alphanumeric char can be derived.
   */
  function labelParts(
    action: MenuActionDescriptor,
  ): { before: string; char: string; after: string } | null {
    const label = actionLabel(action.id);
    const m = mnemonicChar(action);
    if (m === null) return null;
    const idx = label.toLowerCase().indexOf(m);
    if (idx === -1) return null;
    return { before: label.slice(0, idx), char: label.slice(idx, idx + 1), after: label.slice(idx + 1) };
  }

  function isActionEnabled(action: MenuActionDescriptor): boolean {
    if (open === null) return false;
    if (open.stale) return false;
    return action.id in open.handlers;
  }

  function activate(action: MenuActionDescriptor): void {
    if (!isActionEnabled(action)) return;
    if (open === null) return;
    const handler = open.handlers[action.id];
    if (handler === undefined) return;
    if (action.destructive === true) {
      // The destructive confirmation dialog is the consumer's
      // responsibility — the consumer's handler should open it. The
      // menu only routes the click through; closing the menu here
      // matches the doc §"Common behavior" — "Picking an action
      // closes after the action fires."
      handler();
    } else {
      handler();
    }
    closeMenu();
  }

  /**
   * Returns ``true`` when ``el`` is an editable field — ``INPUT``,
   * ``TEXTAREA``, or a ``contentEditable`` host. Used by the focusin
   * auto-close guard and the keydown intercept guard.
   *
   * Checks the IDL property ``contentEditable`` (``"true"`` /
   * ``"false"`` / ``"inherit"``) rather than ``isContentEditable``
   * because ``isContentEditable`` is a computed property that some
   * environments (notably jsdom) do not populate until layout.  The
   * IDL property is set synchronously on assignment.
   */
  function isEditableElement(el: Element): boolean {
    const tag = el.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA") return true;
    if (el instanceof HTMLElement && el.contentEditable === "true") return true;
    return false;
  }

  /**
   * Returns ``true`` when ``el`` is an editable field that lives
   * **outside** the open menu container. The check is symmetric:
   * elements inside the menu (e.g. a future inline-edit row) are
   * explicitly excluded so typing there still works.
   */
  function isEditableOutsideMenu(el: Element): boolean {
    if (!isEditableElement(el)) return false;
    if (menuContainerRef !== null && menuContainerRef.contains(el)) return false;
    return true;
  }

  /**
   * Auto-close handler for the global ``focusin`` event. If focus
   * moves to an editable element outside the menu while the menu is
   * open, close the menu immediately (within the same event-loop tick).
   * This prevents the ``svelte:window onkeydown`` handler from
   * swallowing subsequent alphanumeric keystrokes destined for the
   * newly focused field — the "composer textarea dead until hard
   * refresh" wedge documented in v0.17's ContextMenu head comment.
   */
  function handleFocusIn(event: FocusEvent): void {
    if (open === null) return;
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (isEditableOutsideMenu(target)) {
      closeMenu();
    }
  }

  function handleKeyDown(event: KeyboardEvent): void {
    if (open === null) return;
    // Guard: if focus has moved to an editable field outside the menu,
    // do not intercept the keystroke. The menu will already be closing
    // (or have closed) via handleFocusIn; skipping here prevents a
    // race where a mnemonic match calls preventDefault on a keystroke
    // that the focused input needs.
    if (event.target instanceof Element && isEditableOutsideMenu(event.target)) {
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      highlightIndex = (highlightIndex + 1) % Math.max(1, flatActions.length);
      syncFocus(highlightIndex);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      highlightIndex =
        (highlightIndex - 1 + Math.max(1, flatActions.length)) % Math.max(1, flatActions.length);
      syncFocus(highlightIndex);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const action = flatActions[highlightIndex];
      if (action !== undefined) activate(action);
    } else if (event.key === "Home") {
      event.preventDefault();
      const firstEnabled = flatActions.findIndex((a) => isActionEnabled(a));
      if (firstEnabled !== -1) {
        highlightIndex = firstEnabled;
        syncFocus(highlightIndex);
      }
    } else if (event.key === "End") {
      event.preventDefault();
      let lastEnabled = -1;
      for (let i = flatActions.length - 1; i >= 0; i--) {
        if (isActionEnabled(flatActions[i]!)) {
          lastEnabled = i;
          break;
        }
      }
      if (lastEnabled !== -1) {
        highlightIndex = lastEnabled;
        syncFocus(highlightIndex);
      }
    } else if (/^[a-zA-Z0-9]$/.test(event.key)) {
      const lowerKey = event.key.toLowerCase();
      const matches: number[] = [];
      for (let i = 0; i < flatActions.length; i++) {
        if (mnemonicChar(flatActions[i]!) === lowerKey) matches.push(i);
      }
      if (matches.length > 0) {
        event.preventDefault();
        const currentPos = matches.indexOf(highlightIndex);
        highlightIndex =
          currentPos >= 0 ? matches[(currentPos + 1) % matches.length]! : matches[0]!;
        syncFocus(highlightIndex);
      }
    }
  }

  onMount(() => {
    return registerEscEntry({
      priority: ESC_PRIORITY_CONTEXT_MENU,
      isOpen: () => contextMenuStore.open !== null,
      close: closeMenu,
    });
  });
</script>

<svelte:window onkeydown={handleKeyDown} onfocusin={handleFocusIn} />

{#if open !== null}
  <!-- Backdrop — clicking outside closes the menu. -->
  <div
    class="context-menu-backdrop"
    role="presentation"
    data-testid="context-menu-backdrop"
    onclick={closeMenu}
    onkeydown={(event) => {
      if (event.key === "Enter" || event.key === " ") closeMenu();
    }}
    oncontextmenu={(event) => {
      // A second right-click outside the menu closes the existing menu.
      // The browser's native menu will not fire because the action's
      // preventDefault path on the host element already runs first.
      event.preventDefault();
      closeMenu();
    }}
  ></div>
  <ul
    bind:this={menuContainerRef}
    class="context-menu"
    role="menu"
    aria-label={CONTEXT_MENU_STRINGS.rootAriaLabel}
    data-testid="context-menu"
    data-target={open.target}
    tabindex="-1"
    style:left="{open.x}px"
    style:top="{open.y}px"
    onclick={(event) => event.stopPropagation()}
    onkeydown={(event) => {
      handleKeyDown(event);
      event.stopPropagation();
    }}
  >
    {#if open.stale}
      <li
        class="context-menu__caption"
        role="presentation"
        data-testid="context-menu-stale-caption"
      >
        {CONTEXT_MENU_STRINGS.staleTargetMessage}
      </li>
    {/if}
    {#each grouped ?? [] as group, gi (group.section)}
      {#if gi > 0}
        <li class="context-menu__divider" role="separator"></li>
      {/if}
      {#each group.actions as action, ai (action.id)}
        {@const flatIdx = computeFlatIndex(grouped, group.section, ai)}
        {@const parts = labelParts(action)}
        <li
          class="context-menu__row"
          class:context-menu__row--disabled={!isActionEnabled(action)}
          class:context-menu__row--destructive={action.destructive === true}
          class:context-menu__row--highlighted={flatIdx === highlightIndex}
          role="menuitem"
          tabindex="-1"
          aria-disabled={!isActionEnabled(action)}
          data-testid="context-menu-row"
          data-action={action.id}
          data-section={action.section}
          data-advanced={action.advanced ? "true" : "false"}
          data-destructive={action.destructive ? "true" : "false"}
          onclick={() => activate(action)}
          onkeydown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              event.stopPropagation();
              activate(action);
            }
          }}
        >
          <span class="context-menu__label">
            {#if parts !== null}
              {parts.before}<u class="context-menu__mnemonic">{parts.char}</u>{parts.after}
            {:else}
              {actionLabel(action.id)}
            {/if}
          </span>
          {#if action.submenu}
            <span class="context-menu__arrow" aria-hidden="true">▸</span>
          {/if}
        </li>
      {/each}
    {/each}
    {#if open.advancedRevealed && hasAdvanced(open.target)}
      <li
        class="context-menu__caption"
        role="presentation"
        data-testid="context-menu-advanced-caption"
      >
        {CONTEXT_MENU_STRINGS.advancedRevealedCaption}
      </li>
    {/if}
  </ul>
{/if}

<style>
  .context-menu-backdrop {
    position: fixed;
    inset: 0;
    z-index: 110;
  }
  .context-menu {
    position: fixed;
    z-index: 120;
    min-width: 14rem;
    background: rgb(var(--bearings-surface-1));
    color: rgb(var(--bearings-fg));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.375rem;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    padding: 0.25rem 0;
    margin: 0;
    list-style: none;
    font-size: 0.875rem;
  }
  .context-menu__row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.25rem 0.75rem;
    cursor: pointer;
  }
  .context-menu__row:hover,
  .context-menu__row--highlighted {
    background: rgb(var(--bearings-surface-2));
  }
  .context-menu__row--disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .context-menu__row--destructive .context-menu__label {
    color: #f87171;
  }
  .context-menu__divider {
    height: 1px;
    background: rgb(var(--bearings-border));
    margin: 0.25rem 0;
  }
  .context-menu__caption {
    padding: 0.25rem 0.75rem;
    color: rgb(var(--bearings-fg-muted));
    font-size: 0.75rem;
    font-style: italic;
  }
  .context-menu__arrow {
    color: rgb(var(--bearings-fg-muted));
    margin-left: 0.5rem;
  }
  .context-menu__mnemonic {
    text-decoration-line: underline;
    text-underline-offset: 2px;
  }
</style>
