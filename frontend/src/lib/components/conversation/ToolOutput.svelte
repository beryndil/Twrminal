<script lang="ts">
  /**
   * One tool-call drawer row — header (name + elapsed + status pip)
   * plus the streaming output area.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/chat.md`` §"What a message turn looks like" —
   *   the tool-work drawer enumerates one row per tool call.
   * - ``docs/behavior/tool-output-streaming.md`` §"When output begins
   *   streaming" — output streams in as it arrives; the row never
   *   blocks behind a spinner; the elapsed-time readout is the live
   *   signal.
   * - §"Very-long-output truncation rules" — past the soft cap the
   *   middle is folded inside an inline expander; the head/tail
   *   bookends remain interactive. (The store applies the soft cap on
   *   ``output``; the row exposes ``rawLength`` so the user sees the
   *   elided count.)
   * - §"Partial-output behavior on tool failure" — a failed call
   *   keeps the partial output visible and appends an error block.
   * - §"Long-tool keepalive" — keepalive ticks update
   *   ``liveElapsedMs``; the readout uses it during in-flight, then
   *   freezes on ``durationMs`` once ``done``.
   * - ``docs/behavior/context-menus.md`` §"Tool call" — right-click
   *   opens ``MENU_TARGET_TOOL_CALL`` with copy-name / copy-input /
   *   copy-output / copy-id handlers (G5).
   */
  import {
    CONVERSATION_STRINGS,
    MENU_ACTION_TOOL_CALL_COPY_ID,
    MENU_ACTION_TOOL_CALL_COPY_INPUT,
    MENU_ACTION_TOOL_CALL_COPY_NAME,
    MENU_ACTION_TOOL_CALL_COPY_OUTPUT,
    MENU_TARGET_TOOL_CALL,
  } from "../../config";
  import { contextMenu } from "../../actions/contextMenu";
  import CollapsibleBody from "../common/CollapsibleBody.svelte";
  import type { ToolCallView } from "../../stores/conversation.svelte";

  interface Props {
    call: ToolCallView;
  }

  const { call }: Props = $props();

  // ---- context-menu handlers -------------------------------------------------

  const menuHandlers = $derived({
    /** Copy the tool name (e.g. ``Bash``, ``Read``) to the clipboard. */
    [MENU_ACTION_TOOL_CALL_COPY_NAME]: () => {
      void navigator.clipboard.writeText(call.name);
    },

    /** Copy the raw tool-input JSON to the clipboard. */
    [MENU_ACTION_TOOL_CALL_COPY_INPUT]: () => {
      void navigator.clipboard.writeText(call.inputJson);
    },

    /** Copy the streamed / truncated output text to the clipboard. */
    [MENU_ACTION_TOOL_CALL_COPY_OUTPUT]: () => {
      void navigator.clipboard.writeText(call.output);
    },

    /** Copy the tool-call ID.  Advanced action. */
    [MENU_ACTION_TOOL_CALL_COPY_ID]: () => {
      void navigator.clipboard.writeText(call.id);
    },

    // MENU_ACTION_TOOL_CALL_RETRY — advanced; no backend endpoint in v1.
    // Omitting the handler renders the entry disabled in the menu.
  });

  const elapsedMs = $derived(
    call.done && call.durationMs !== null ? call.durationMs : call.liveElapsedMs,
  );
  const elapsedLabel = $derived(formatElapsed(elapsedMs));
  const elidedCount = $derived(Math.max(0, call.rawLength - call.output.length));
  const statusLabel = $derived(
    call.done
      ? call.ok === false
        ? CONVERSATION_STRINGS.toolStatusError
        : CONVERSATION_STRINGS.toolStatusOk
      : CONVERSATION_STRINGS.toolStatusRunning,
  );

  function formatElapsed(ms: number): string {
    if (ms < 1000) {
      return `00:00`;
    }
    const totalSec = Math.floor(ms / 1000);
    const min = Math.floor(totalSec / 60);
    const sec = totalSec % 60;
    return `${pad2(min)}:${pad2(sec)}`;
  }

  function pad2(n: number): string {
    return n < 10 ? `0${n}` : String(n);
  }
</script>

<details
  class="tool-output mb-2 rounded border border-border bg-surface-0"
  data-testid="tool-output"
  use:contextMenu={{
    target: MENU_TARGET_TOOL_CALL,
    handlers: menuHandlers,
    data: { toolCallId: call.id },
  }}
>
  <summary
    class="flex cursor-pointer items-center gap-2 px-2 py-1.5 font-mono text-xs"
    data-testid="tool-output-summary"
  >
    <span class="text-fg-muted">$</span>
    <span class="font-medium text-fg-strong" data-testid="tool-output-name">{call.name}</span>
    <span
      class="ml-auto inline-flex items-center gap-1.5 font-mono text-fg-muted"
      data-testid="tool-output-elapsed"
    >
      <span
        class="inline-block h-1.5 w-1.5 rounded-full"
        class:bg-accent={call.done && call.ok === true}
        class:bg-red-400={call.done && call.ok === false}
        class:bg-fg-muted={!call.done}
        data-testid="tool-output-status-pip"
        aria-label={statusLabel}
      ></span>
      {elapsedLabel}
    </span>
  </summary>
  <div
    class="tool-output__body border-t border-border px-2 py-2 text-xs"
    data-testid="tool-output-body"
  >
    {#if call.output.length === 0 && !call.done}
      <p class="text-fg-muted" data-testid="tool-output-empty">
        {CONVERSATION_STRINGS.toolStatusRunning}…
      </p>
    {:else}
      <CollapsibleBody>
        <pre
          class="whitespace-pre-wrap break-words font-mono text-fg"
          data-testid="tool-output-stream">{call.output}</pre>
      </CollapsibleBody>
    {/if}
    {#if elidedCount > 0}
      <p class="mt-1 italic text-fg-muted" data-testid="tool-output-truncated">
        {CONVERSATION_STRINGS.truncationLabel} ({elidedCount} chars elided)
      </p>
    {/if}
    {#if call.done && call.ok === false && call.errorMessage !== null}
      <p
        class="mt-2 rounded border border-red-500 px-2 py-1 text-red-400"
        data-testid="tool-output-error"
      >
        Error: {call.errorMessage}
      </p>
    {/if}
  </div>
</details>
