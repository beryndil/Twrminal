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
  import { pendingOpsStore, type PendingOp } from "../../stores/pending.svelte";
  import { shellOpenInEditor } from "../../api/shell";
  import { showShellOpError } from "../../stores/shellOpNotification.svelte";

  interface Props {
    op: PendingOp;
    onResolve: (name: string) => void;
    onDismiss: (name: string) => void;
  }

  const { op, onResolve, onDismiss }: Props = $props();

  /**
   * True when this op's ``name`` is no longer present in
   * ``pendingOpsStore.ops`` — meaning it was resolved or dismissed
   * (by this or a sister tab) between mouse-down and the
   * ``contextmenu`` event firing. Passed to ``use:contextMenu`` so
   * the menu opens with every action greyed and the stale-target
   * caption per ``docs/behavior/context-menus.md`` §"Failure modes".
   */
  const isOpStale = $derived(!pendingOpsStore.ops.some((o) => o.name === op.name));

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

  // ---- Shell-open handler ---------------------------------------------------

  /**
   * Open the op's ``dir`` in the editor via the backend shell surface.
   * When ``dir`` is absent the action is omitted from the handler map
   * so the menu renders it greyed.
   */
  function handleOpenInEditor(): void {
    const dir = op.dir ?? "";
    if (dir === "") return;
    void shellOpenInEditor(dir).catch((err: unknown) => {
      const detail = err instanceof Error ? err.message : "unknown error";
      showShellOpError(detail);
    });
  }

  const menuHandlers = $derived({
    [MENU_ACTION_PENDING_OPERATION_RESOLVE]: () => onResolve(op.name),
    [MENU_ACTION_PENDING_OPERATION_DISMISS]: {
      handler: () => onDismiss(op.name),
      confirmMessage: `Dismiss "${op.name}"?`,
      confirmLabel: "Dismiss",
    },
    [MENU_ACTION_PENDING_OPERATION_COPY_NAME]: handleCopyName,
    [MENU_ACTION_PENDING_OPERATION_COPY_COMMAND]: handleCopyCommand,
    // Open-in-editor only wired when op.dir is present; absent handler
    // renders the action greyed per context-menu behavior doc §"Pending
    // operation".
    ...(op.dir !== undefined && op.dir !== ""
      ? { [MENU_ACTION_PENDING_OPERATION_OPEN_IN_EDITOR]: handleOpenInEditor }
      : {}),
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
    stale: isOpStale,
  }}
>
  <!-- Name + age on same line -->
  <div class="flex items-baseline justify-between gap-2">
    <span class="truncate font-medium text-fg-strong" data-testid="pending-op-name">
      {op.name}
    </span>
    <span class="shrink-0 font-mono text-xs text-fg-muted" data-testid="pending-op-age">
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
