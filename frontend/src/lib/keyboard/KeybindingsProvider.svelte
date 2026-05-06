<script lang="ts">
  /**
   * Keybindings provider — installs the window-level keydown listener
   * that drives the dispatcher, and renders the cheat sheet.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/keyboard-shortcuts.md`` §"Help" — ``?`` toggles
   *   the cheat sheet; the cheat sheet's open state lives here.
   * - §"Command palette" — ``Ctrl+Shift+P`` toggles the command
   *   palette; the palette's open state lives here.
   * - §"Focus" — Esc cascade is the lowest-priority "no-op" branch
   *   when no overlay matched and no input owns focus.
   *
   * Action handlers are bound at this level for the actions the
   * provider owns (``KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET``,
   * ``KEYBINDING_ACTION_TOGGLE_COMMAND_PALETTE``,
   * ``KEYBINDING_ACTION_ESC_CASCADE``). Other actions (``c``, ``j``,
   * ``Alt+1``, etc.) are bound by their respective owners (sidebar,
   * new-session dialog) and tracked through :func:`bindHandler`.
   */
  import type { Snippet } from "svelte";
  import { onMount } from "svelte";

  import {
    KEYBINDING_ACTION_ESC_CASCADE,
    KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET,
    KEYBINDING_ACTION_TOGGLE_COMMAND_PALETTE,
    KEYBINDING_ACTION_TOGGLE_PENDING_OPS,
    KEYBINDING_ACTION_TOGGLE_TEMPLATE_PICKER,
  } from "../config";
  import { dispatchKeyEvent } from "./dispatch";
  import { runEscCascade } from "./escCascade";
  import { bindHandler, setComposerFocused, setModalOpen } from "./store.svelte";
  import CheatSheet from "./CheatSheet.svelte";
  import CommandPalette from "./CommandPalette.svelte";
  import TemplatePicker from "../components/menus/TemplatePicker.svelte";
  import PendingOpsCard from "../components/pending/PendingOpsCard.svelte";

  interface Props {
    children?: Snippet;
    /**
     * Working directory of the currently-selected session — threaded
     * down from ``+layout.svelte`` so ``PendingOpsCard`` can fetch
     * the right ``.bearings/pending.toml`` without reading the
     * inspector store directly from inside the keyboard subsystem.
     */
    activeWorkingDir?: string | null;
  }

  const { children, activeWorkingDir = null }: Props = $props();

  let cheatSheetOpen = $state(false);
  let commandPaletteOpen = $state(false);
  let templatePickerOpen = $state(false);

  import { toggleCard as togglePendingOpsCard } from "../stores/pending.svelte";

  // Re-export the modal flag to the dispatch layer so overlays
  // count as "modal context" for chord gating.
  $effect(() => {
    setModalOpen(cheatSheetOpen || commandPaletteOpen || templatePickerOpen);
  });

  function toggleCheatSheet(): void {
    cheatSheetOpen = !cheatSheetOpen;
    if (cheatSheetOpen) {
      commandPaletteOpen = false;
      templatePickerOpen = false;
    }
  }

  function toggleCommandPalette(): void {
    commandPaletteOpen = !commandPaletteOpen;
    if (commandPaletteOpen) {
      cheatSheetOpen = false;
      templatePickerOpen = false;
    }
  }

  function toggleTemplatePicker(): void {
    templatePickerOpen = !templatePickerOpen;
    if (templatePickerOpen) {
      cheatSheetOpen = false;
      commandPaletteOpen = false;
    }
  }

  function handleEsc(): void {
    runEscCascade();
  }

  function isInputElement(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) return false;
    if (target instanceof HTMLInputElement) return true;
    if (target instanceof HTMLTextAreaElement) return true;
    if (target instanceof HTMLSelectElement) return true;
    return target.isContentEditable;
  }

  onMount(() => {
    // Bind the actions the provider owns.
    const releases = [
      bindHandler(KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET, toggleCheatSheet),
      bindHandler(KEYBINDING_ACTION_TOGGLE_COMMAND_PALETTE, toggleCommandPalette),
      bindHandler(KEYBINDING_ACTION_TOGGLE_TEMPLATE_PICKER, toggleTemplatePicker),
      bindHandler(KEYBINDING_ACTION_TOGGLE_PENDING_OPS, togglePendingOpsCard),
      bindHandler(KEYBINDING_ACTION_ESC_CASCADE, handleEsc),
    ];

    function onKeyDown(event: KeyboardEvent): void {
      // Update composer-focus state from the event target so
      // bare-letter chords correctly skip when typing into a textarea.
      // The flag is also driven by focusin/focusout handlers below for
      // changes that don't coincide with a keydown.
      setComposerFocused(isInputElement(event.target));
      dispatchKeyEvent(event);
    }
    function onFocusIn(event: FocusEvent): void {
      setComposerFocused(isInputElement(event.target));
    }
    function onFocusOut(): void {
      setComposerFocused(false);
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("focusin", onFocusIn);
    window.addEventListener("focusout", onFocusOut);

    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("focusin", onFocusIn);
      window.removeEventListener("focusout", onFocusOut);
      for (const release of releases) release();
    };
  });
</script>

{#if children}
  {@render children()}
{/if}

<CheatSheet open={cheatSheetOpen} onClose={() => (cheatSheetOpen = false)} />
<CommandPalette open={commandPaletteOpen} onClose={() => (commandPaletteOpen = false)} />
<TemplatePicker open={templatePickerOpen} onClose={() => (templatePickerOpen = false)} />
<PendingOpsCard workingDir={activeWorkingDir} />
