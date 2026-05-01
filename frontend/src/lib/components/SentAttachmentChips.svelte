<script lang="ts">
  // Persistent attachment chips rendered below a sent user message.
  //
  // Symmetry with the composer: ConversationComposer renders chips
  // ABOVE the textarea while the user is staging files; once the
  // message is sent those chips clear, and there's no on-screen
  // signal that files were attached. This component closes the loop
  // by re-rendering the same chips inside the user-bubble in
  // MessageTurn so the transcript shows what was sent.
  //
  // Visual style mirrors the composer's own chip styling so the user
  // recognizes them on sight. No remove button (read-only — the
  // message is already sent), no contextmenu hookup (out of scope
  // for v1; future polish could wire "Re-attach" / "Open in finder").
  //
  // Type alignment is end-to-end: messages.attachments column (JSON
  // list, migration 0027) → MessageOut.attachments Pydantic-decoded
  // → MessageAttachment[] in sessions.ts → this component's prop.
  import type { MessageAttachment } from '$lib/api/sessions';
  import { formatBytes } from '$lib/attachments';

  let { attachments = [] }: { attachments?: MessageAttachment[] | null } = $props();
  // Normalize null to empty so the {#if} below can use a single check.
  const list = $derived(attachments ?? []);
</script>

{#if list.length > 0}
  <div class="mt-2 flex flex-wrap gap-1.5" data-testid="sent-attachments">
    {#each list as att (att.n)}
      <span
        class="inline-flex items-center gap-1.5 rounded border border-slate-700
          bg-slate-900 px-2 py-0.5 text-[11px] text-slate-300"
        title={`${att.path}${att.size_bytes ? ' · ' + formatBytes(att.size_bytes) : ''}`}
        data-testid="sent-attachment-chip"
      >
        <span class="text-slate-500">[File {att.n}]</span>
        <span class="max-w-[220px] truncate">{att.filename}</span>
        {#if att.size_bytes}
          <span class="text-slate-500">·</span>
          <span class="text-slate-500">{formatBytes(att.size_bytes)}</span>
        {/if}
      </span>
    {/each}
  </div>
{/if}
