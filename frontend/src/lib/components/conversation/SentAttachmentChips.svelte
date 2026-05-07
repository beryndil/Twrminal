<script lang="ts">
  /**
   * Row of attachment chips shown at the bottom of a sent user bubble.
   *
   * Renders one chip per entry in ``attachments``; renders nothing when the
   * array is empty. Each chip is right-clickable via ``use:contextMenu``
   * into the attachment context menu per
   * ``docs/behavior/context-menus.md`` §"Attachment".
   *
   * ``attachment.remove`` is deliberately absent from the handler map:
   * the message is already sent, so the action renders greyed with its
   * normal label. The other four actions (copy-path, copy-filename,
   * open-in-editor, reveal-in-file-explorer) are all live; the two
   * "open" variants are no-op stubs until the editor/explorer API lands.
   *
   * Behavior anchor: ``docs/behavior/chat.md`` §"What a message turn
   * looks like" — "attachment chips at the bottom (``[File 1] foo.log``-style
   * chips opened from context-menus → attachment)."
   */
  import {
    MENU_ACTION_ATTACHMENT_COPY_FILENAME,
    MENU_ACTION_ATTACHMENT_COPY_PATH,
    MENU_ACTION_ATTACHMENT_OPEN_IN_EDITOR,
    MENU_ACTION_ATTACHMENT_OPEN_IN_FILE_EXPLORER,
    MENU_TARGET_ATTACHMENT,
    SENT_ATTACHMENT_STRINGS,
  } from "../../config";
  import { contextMenu } from "../../actions/contextMenu";
  import type { SentAttachment } from "../../stores/conversation.svelte";

  interface Props {
    attachments: readonly SentAttachment[];
  }

  const { attachments }: Props = $props();

  /**
   * Extract the filename from an absolute path (everything after the
   * last ``/``). Falls back to the full path when no separator is found.
   */
  function basename(path: string): string {
    return path.split("/").pop() ?? path;
  }
</script>

{#if attachments.length > 0}
  <div
    class="mt-1 flex flex-wrap gap-1"
    data-testid="sent-attachment-chips"
    aria-label={SENT_ATTACHMENT_STRINGS.chipsAreaAriaLabel}
  >
    {#each attachments as attachment (attachment.id)}
      <span
        class="inline-flex items-center rounded border border-border bg-surface-1 px-2 py-0.5 text-xs text-fg-muted cursor-default"
        data-testid="sent-attachment-chip"
        data-attachment-id={attachment.id}
        use:contextMenu={{
          target: MENU_TARGET_ATTACHMENT,
          handlers: {
            [MENU_ACTION_ATTACHMENT_COPY_PATH]: () => {
              void navigator.clipboard.writeText(attachment.path);
            },
            [MENU_ACTION_ATTACHMENT_COPY_FILENAME]: () => {
              void navigator.clipboard.writeText(basename(attachment.path));
            },
            // Open-in-editor: no-op stub until the editor-open API lands.
            [MENU_ACTION_ATTACHMENT_OPEN_IN_EDITOR]: () => {
              // intentionally empty — action is enabled (not absent) so the
              // menu entry renders live rather than greyed.
            },
            // Reveal-in-file-explorer: likewise a no-op stub.
            [MENU_ACTION_ATTACHMENT_OPEN_IN_FILE_EXPLORER]: () => {
              // intentionally empty stub
            },
            // MENU_ACTION_ATTACHMENT_REMOVE is absent: the message is already
            // sent. The menu entry renders greyed per the behavior doc.
          },
          data: { attachmentId: attachment.id, path: attachment.path },
        }}
      >
        {attachment.label}
      </span>
    {/each}
  </div>
{/if}
