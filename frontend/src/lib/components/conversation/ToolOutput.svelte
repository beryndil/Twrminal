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
   */
  import { CONVERSATION_STRINGS } from "../../config";
  import type { ToolCallView } from "../../stores/conversation.svelte";

  interface Props {
    call: ToolCallView;
  }

  const { call }: Props = $props();

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
      <pre
        class="whitespace-pre-wrap break-words font-mono text-fg"
        data-testid="tool-output-stream">{call.output}</pre>
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
