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
  import { closeMenu, contextMenuStore, isActionSuppressed, suppressAction } from "./store.svelte";
  import { isCoarsePointer } from "./touch";
  import { placeAtCursor } from "./positioning";
  import ConfirmDialog from "../components/sidebar/ConfirmDialog.svelte";

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
   * Pending destructive confirmation — set by :func:`activate` when a
   * destructive action fires and the consumer has not opted out of the
   * central bridge (``skipMenuConfirm !== true``). The menu is already
   * closed at this point; the ConfirmDialog renders in its place.
   * ``null`` when no confirmation is pending.
   */
  interface PendingConfirm {
    handler: () => void;
    message: string;
    confirmLabel: string;
    /** Action id — used to record a suppression when the user ticks the checkbox. */
    actionId: string;
  }
  let pendingConfirm: PendingConfirm | null = $state(null);

  /**
   * The element that held DOM focus when the menu opened. Restored on
   * close (best-effort — only HTMLElement targets can receive focus).
   */
  let savedFocus: Element | null = null;

  /**
   * True when the menu was opened on a coarse-pointer device (touch /
   * pen). Latched at open time via :func:`isCoarsePointer` so the
   * layout stays stable for the duration the menu is visible.
   * Resets to ``false`` on close.
   */
  let coarse: boolean = $state(false);

  /**
   * Fallback menu dimensions for first-frame placement before the
   * browser has laid out the element and ``menuContainerRef`` is
   * populated.  Values match v17's defaults and cover a typical
   * action list comfortably.
   */
  const MENU_DEFAULT_WIDTH = 220;
  const MENU_DEFAULT_HEIGHT = 48;

  /**
   * Clamped ``position: fixed`` origin for the fine-pointer floating
   * panel.  Reads ``menuContainerRef`` so the derived re-runs after
   * the menu element mounts — the second pass uses the actual rendered
   * dimensions rather than the first-frame defaults.
   *
   * Coarse (bottom-sheet) layout is exempt: its position is governed
   * by CSS, not by this derived.
   */
  const menuPosition = $derived.by(() => {
    if (open === null || coarse) return { left: 0, top: 0 };
    const el = menuContainerRef;
    const menuWidth = el !== null && el.offsetWidth > 0 ? el.offsetWidth : MENU_DEFAULT_WIDTH;
    const menuHeight = el !== null && el.offsetHeight > 0 ? el.offsetHeight : MENU_DEFAULT_HEIGHT;
    return placeAtCursor({
      x: open.x,
      y: open.y,
      menuWidth,
      menuHeight,
      viewportWidth: typeof window !== "undefined" ? window.innerWidth : 1920,
      viewportHeight: typeof window !== "undefined" ? window.innerHeight : 1080,
    });
  });

  $effect(() => {
    if (open !== null) {
      savedFocus = document.activeElement;
      highlightIndex = 0;
      coarse = isCoarsePointer();
      syncFocus(0);
    } else {
      if (savedFocus instanceof HTMLElement) {
        savedFocus.focus();
      }
      savedFocus = null;
      coarse = false;
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
    const entry = open.handlers[action.id];
    if (typeof entry === "function") return true;
    // Object entries with a `handler` field are enabled; `{ disabledReason }`
    // entries and absent keys are disabled.
    if (entry !== undefined && typeof entry === "object" && "handler" in entry) return true;
    return false;
  }

  /**
   * Returns the disabled-reason tooltip string for ``action``, or
   * ``undefined`` when no reason is available.  Only populated for
   * actions that are disabled because the consumer explicitly mapped
   * them to a ``{ disabledReason }`` entry (as opposed to simply
   * omitting them from the handler map).  Stale menus suppress
   * per-row reasons — the stale caption already explains the state.
   */
  function actionDisabledReason(action: MenuActionDescriptor): string | undefined {
    if (open === null || open.stale) return undefined;
    const entry = open.handlers[action.id];
    if (entry === undefined || typeof entry === "function") return undefined;
    // Only { disabledReason } entries carry a tooltip; handler-object entries do not.
    if (!("disabledReason" in entry)) return undefined;
    return entry.disabledReason;
  }

  /**
   * Central activation bridge — implements the v17 contract restored by
   * gap-cycle-05-003:
   *
   * - Non-destructive actions: fire the handler and close the menu.
   * - Destructive actions (``action.destructive === true``):
   *   - If the consumer has set ``skipMenuConfirm: true`` on the entry the
   *     handler is called directly (consumer manages its own dialog).
   *   - Otherwise: close the menu and show :component:`ConfirmDialog`.
   *     The handler fires only when the user clicks Confirm; Cancel /
   *     Esc skips it.
   *
   * Behaviour anchor: ``docs/behavior/context-menus.md`` §"Common
   * behavior — Destructive entries".
   */
  function activate(action: MenuActionDescriptor): void {
    if (!isActionEnabled(action)) return;
    if (open === null) return;

    const entry = open.handlers[action.id];

    // Extract the raw handler and any bridge metadata.
    let handler: () => void;
    let skipMenuConfirm = false;
    let confirmMessage: string | undefined;
    let confirmLabel: string | undefined;

    if (typeof entry === "function") {
      handler = entry;
    } else if (entry !== undefined && typeof entry === "object" && "handler" in entry) {
      const obj = entry as {
        handler: () => void;
        skipMenuConfirm?: boolean;
        confirmMessage?: string;
        confirmLabel?: string;
      };
      handler = obj.handler;
      skipMenuConfirm = obj.skipMenuConfirm === true;
      confirmMessage = obj.confirmMessage;
      confirmLabel = obj.confirmLabel;
    } else {
      return;
    }

    if (action.destructive === true && !skipMenuConfirm) {
      // If the user previously ticked "Don't ask again this session" for
      // this action, skip the dialog and fire the handler directly.
      if (isActionSuppressed(action.id)) {
        handler();
        closeMenu();
        return;
      }
      // Close the menu first (matching v17: "every destructive click closed
      // the menu, then called confirmStore.request(...)").
      closeMenu();
      pendingConfirm = {
        handler,
        message: confirmMessage ?? `${actionLabel(action.id)}?`,
        confirmLabel: confirmLabel ?? "Confirm",
        actionId: action.id,
      };
    } else {
      handler();
      closeMenu();
    }
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
    } else if (event.key === "ArrowRight") {
      const action = flatActions[highlightIndex];
      if (action !== undefined && action.submenu === true) {
        event.preventDefault();
        // Forward-compat: v18 has no submenu rendering host yet. Activating
        // the action lets the consumer's handler open whatever picker / modal
        // the submenu entry would surface (e.g. the model picker for
        // ``session.change_model``). When the submenu component lands, this
        // branch will open the child menu rather than activating immediately.
        activate(action);
      }
      // Non-submenu rows: ArrowRight is intentionally a no-op — no
      // preventDefault so browser horizontal scroll / focus trap is preserved.
    } else if (event.key === "ArrowLeft") {
      // Forward-compat stub: when a child submenu is open, ArrowLeft should
      // close it and return highlight to the parent row. v18 has no submenu
      // rendering host, so this is a no-op. preventDefault prevents
      // horizontal scroll while the root menu is open.
      event.preventDefault();
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

{#if pendingConfirm !== null}
  <!--
    Central destructive-confirmation bridge (gap-cycle-05-003).
    The menu has already been closed; this dialog sits on top.
  -->
  <ConfirmDialog
    message={pendingConfirm.message}
    confirmLabel={pendingConfirm.confirmLabel}
    showSuppressCheckbox={true}
    onConfirm={() => {
      const { handler } = pendingConfirm!;
      pendingConfirm = null;
      handler();
    }}
    onConfirmAndSuppress={() => {
      const { handler, actionId } = pendingConfirm!;
      pendingConfirm = null;
      suppressAction(actionId);
      handler();
    }}
    onCancel={() => {
      pendingConfirm = null;
    }}
  />
{/if}

{#snippet menuBody()}
  {#if open !== null}
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
          title={actionDisabledReason(action)}
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
  {/if}
{/snippet}

{#if open !== null}
  <!--
    Backdrop — clicking outside closes the menu.
    In coarse (touch) mode the backdrop is opaque (slate-950/60) to
    visually separate the bottom sheet from the page content beneath.
  -->
  <div
    class="context-menu-backdrop"
    class:context-menu-backdrop--coarse={coarse}
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

  {#if coarse}
    <!--
      Coarse (touch / pen) layout: full-width bottom sheet with a
      drag-handle affordance and 44 px minimum touch-target rows.
      iOS/Android HIG compliant for thumb interaction.
    -->
    <div class="context-menu-sheet">
      <div
        class="context-menu-sheet__handle"
        data-testid="context-menu-drag-handle"
        aria-hidden="true"
      ></div>
      <ul
        bind:this={menuContainerRef}
        class="context-menu context-menu--sheet"
        role="menu"
        aria-label={CONTEXT_MENU_STRINGS.rootAriaLabel}
        data-testid="context-menu"
        data-target={open.target}
        data-coarse="true"
        tabindex="-1"
        onclick={(event) => event.stopPropagation()}
        oncontextmenu={(event) => event.preventDefault()}
        onkeydown={(event) => {
          handleKeyDown(event);
          event.stopPropagation();
        }}
      >
        {@render menuBody()}
      </ul>
    </div>
  {:else}
    <!--
      Fine (mouse / trackpad) layout: cursor-anchored floating panel.
      Preserves the existing v18 layout verbatim.
    -->
    <ul
      bind:this={menuContainerRef}
      class="context-menu"
      role="menu"
      aria-label={CONTEXT_MENU_STRINGS.rootAriaLabel}
      data-testid="context-menu"
      data-target={open.target}
      data-coarse="false"
      tabindex="-1"
      style:left="{menuPosition.left}px"
      style:top="{menuPosition.top}px"
      onclick={(event) => event.stopPropagation()}
      oncontextmenu={(event) => event.preventDefault()}
      onkeydown={(event) => {
        handleKeyDown(event);
        event.stopPropagation();
      }}
    >
      {@render menuBody()}
    </ul>
  {/if}
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

  /* ---- Coarse (touch / pen) backdrop ---- */
  .context-menu-backdrop--coarse {
    /* Opaque backdrop per iOS/Android HIG for modal bottom sheets. */
    background: rgba(2, 6, 23, 0.6); /* slate-950 / 60 % */
  }

  /* ---- Coarse bottom-sheet container ---- */
  .context-menu-sheet {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 120;
    background: rgb(var(--bearings-surface-1));
    border-radius: 1rem 1rem 0 0;
    box-shadow: 0 -4px 24px rgba(0, 0, 0, 0.35);
    max-height: 75vh;
    overflow-y: auto;
  }

  /* Drag-handle affordance — centered pill at the top of the sheet. */
  .context-menu-sheet__handle {
    width: 2.5rem;
    height: 0.25rem;
    background: rgb(var(--bearings-border));
    border-radius: 0.125rem;
    margin: 0.75rem auto 0.5rem;
  }

  /* Bottom-sheet menu list — no border / shadow (handled by the wrapper). */
  .context-menu--sheet {
    position: static;
    box-shadow: none;
    border: none;
    border-radius: 0;
    min-width: 0;
    width: 100%;
  }

  /* 44 px minimum touch-target for coarse-mode rows (Apple / Material HIG). */
  [data-coarse="true"] [role="menuitem"] {
    min-height: 44px;
    padding: 0.625rem 0.75rem;
  }
</style>
