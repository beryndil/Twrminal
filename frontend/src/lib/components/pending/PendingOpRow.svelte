<script lang="ts">
  /**
   * A single row inside the pending-operations floating card.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/context-menus.md`` §"Pending operation" — right-
   *   click opens the ``MENU_TARGET_PENDING_OPERATION`` menu with
   *   primary ``Mark resolved``, destructive ``Dismiss``, copy and
   *   view advanced actions.
   * - ``docs/behavior/keyboard-shortcuts.md`` §"Help" — the card is
   *   toggled by ``Ctrl+Shift+O``; individual rows have no additional
   *   keyboard bindings beyond the context menu.
   *
   * The row renders: ``name`` (bold), ``description`` (muted), and a
   * live-ticking age derived from ``started_at``. The age ticker
   * updates every second via ``setInterval`` while the row is mounted.
   */
  import {
    MENU_ACTION_PENDING_OPERATION_COPY_COMMAND,
    MENU_ACTION_PENDING_OPERATION_COPY_NAME,
    MENU_ACTION_PENDING_OPERATION_DISMISS,
    MENU_ACTION_PENDING_OPERATION_OPEN_IN_EDITOR,
    MENU_ACTION_PENDING_OPERATION_RESOLVE,
    MENU_TARGET_PENDING_OPERATION,
    PENDING_OPS_CARD_STRINGS,
  } from "../../config";
  import { contextMenu } from "../../actions/contextMenu";
  import type { PendingOp } from "../../stores/pending.svelte";

  interface Props {
    op: PendingOp;
    onResolve: (name: string) => void;
    onDismiss: (name: string) => void;
  }

  const { op, onResolve, onDismiss }: Props = $props();

  // ---- Live age ticker -------------------------------------------------------

  function secondsSince(isoTimestamp: string): number {
    const started = new Date(isoTimestamp).getTime();
    if (isNaN(started)) return 0;
    return Math.max(0, Math.floor((Date.now() - started) / 1000));
  }

  let ageSecs = $state(0);

  $effect(() => {
    // Seed immediately and re-seed whenever started_at changes.
    ageSecs = secondsSince(op.started_at);
    const handle = setInterval(() => {
      ageSecs = secondsSince(op.started_at);
    }, 1000);
    return () => clearInterval(handle);
  });

  // ---- Context-menu handlers -------------------------------------------------

  function handleCopyName(): void {
    void navigator.clipboard.writeText(op.name);
  }

  function handleCopyCommand(): void {
    if (op.command !== undefined) {
      void navigator.clipboard.writeText(op.command);
    }
  }

  function handleOpenInEditor(): void {
    const dir = op.dir ?? "";
    if (dir !== "") {
      // The editor-open action is advisory; no direct API call here.
      // The context-menu action fires the handler registered on this row.
      // The PendingOpsCard is responsible for a richer implementation
      // if the backend shell/exec surface is wired.
      void navigator.clipboard.writeText(dir);
    }
  }

  const menuHandlers = $derived({
    [MENU_ACTION_PENDING_OPERATION_RESOLVE]: () => onResolve(op.name),
    [MENU_ACTION_PENDING_OPERATION_DISMISS]: () => onDismiss(op.name),
    [MENU_ACTION_PENDING_OPERATION_COPY_NAME]: handleCopyName,
    [MENU_ACTION_PENDING_OPERATION_COPY_COMMAND]: handleCopyCommand,
    [MENU_ACTION_PENDING_OPERATION_OPEN_IN_EDITOR]: handleOpenInEditor,
  });
</script>

<li
  class="pending-op-row flex flex-col gap-0.5 rounded px-3 py-2 text-sm hover:bg-surface-2"
  data-testid="pending-op-row"
  data-op-name={op.name}
  use:contextMenu={{
    target: MENU_TARGET_PENDING_OPERATION,
    handlers: menuHandlers,
    data: { name: op.name },
  }}
>
  <!-- Name + age on same line -->
  <div class="flex items-baseline justify-between gap-2">
    <span
      class="truncate font-medium text-fg-strong"
      data-testid="pending-op-name"
    >
      {op.name}
    </span>
    <span
      class="shrink-0 font-mono text-xs text-fg-muted"
      data-testid="pending-op-age"
    >
      {PENDING_OPS_CARD_STRINGS.ageLabel(ageSecs)}
    </span>
  </div>

  <!-- Description -->
  {#if op.description !== ""}
    <p class="line-clamp-2 text-xs text-fg-muted" data-testid="pending-op-description">
      {op.description}
    </p>
  {/if}

  <!-- Quick-action buttons -->
  <div class="mt-1 flex gap-1.5">
    <button
      type="button"
      class="rounded bg-accent px-2 py-0.5 text-xs font-medium text-white hover:bg-accent-muted"
      data-testid="pending-op-resolve-btn"
      onclick={() => onResolve(op.name)}
    >
      Mark resolved
    </button>
    <button
      type="button"
      class="rounded px-2 py-0.5 text-xs font-medium text-fg-muted hover:bg-surface-2 hover:text-red-400"
      data-testid="pending-op-dismiss-btn"
      onclick={() => onDismiss(op.name)}
    >
      Dismiss
    </button>
  </div>
</li>
