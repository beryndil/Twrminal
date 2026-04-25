<script lang="ts">
  import { billing } from '$lib/stores/billing.svelte';
  import { conversation } from '$lib/stores/conversation.svelte';
  import { drafts } from '$lib/stores/drafts.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { agent } from '$lib/agent.svelte';
  import {
    caretOnFirstLine,
    caretOnLastLine,
    emptyHistoryState,
    nextHistory,
    prevHistory,
    resetHistory,
    type HistoryState
  } from '$lib/input-history';
  import * as api from '$lib/api';
  import type { MessageAttachment } from '$lib/api/sessions';
  import * as fsApi from '$lib/api/fs';
  import * as uploadsApi from '$lib/api/uploads';
  import {
    ATTACHMENT_TOKEN_REGEX,
    formatAttachmentToken,
    formatBytes
  } from '$lib/attachments';
  import ApprovalModal from '$lib/components/ApprovalModal.svelte';
  import AskUserQuestionModal from '$lib/components/AskUserQuestionModal.svelte';
  import BearingsMark from '$lib/components/icons/BearingsMark.svelte';
  import BulkActionBar from '$lib/components/BulkActionBar.svelte';
  import CheckpointGutter from '$lib/components/CheckpointGutter.svelte';
  import CommandMenu from '$lib/components/CommandMenu.svelte';
  import MessageTurn from '$lib/components/MessageTurn.svelte';
  import PermissionModeSelector from '$lib/components/PermissionModeSelector.svelte';
  import StopUndoInline from '$lib/components/StopUndoInline.svelte';
  import ReorgAuditDivider from '$lib/components/ReorgAuditDivider.svelte';
  import ReorgUndoToast from '$lib/components/ReorgUndoToast.svelte';
  import SessionEdit from '$lib/components/SessionEdit.svelte';
  import SessionPickerModal from '$lib/components/SessionPickerModal.svelte';
  import { reorgStore } from '$lib/context-menu/reorg.svelte';
  import ContextMeter from '$lib/components/ContextMeter.svelte';
  import LiveTodos from '$lib/components/LiveTodos.svelte';
  import TokenMeter from '$lib/components/TokenMeter.svelte';
  import VirtualItem from '$lib/components/VirtualItem.svelte';
  import {
    connectionLabel,
    copyText,
    messagesAsMarkdown,
    pressureClass
  } from '$lib/utils/conversation-ui';

  // Item 29 / perf audit 2026-04-21 (refactor 2026-04-24):
  // `turns` and `timeline` now live on `ConversationStore`; the
  // reducer keeps them in sync via in-place tail mutation so the
  // Conversation pane no longer recomputes either array on every WS
  // event. `audits` similarly moved into the store so `setAudits`
  // owns the timeline merge. See `reducer.ts` module docstring.
  const turns = $derived(conversation.turns);
  const timeline = $derived(conversation.timeline);
  const audits = $derived(conversation.audits);

  // Item 34 / perf audit 2026-04-21: timeline virtualization. The DB
  // probe found 3 of 41 sessions already exceed 300 timeline items
  // and the largest is 580. Below the threshold the cost of pinning
  // an IntersectionObserver per item isn't worth recovering — keep
  // the simple {#each} render. Above it, wrap each entry in
  // `VirtualItem` so only items near the viewport mount their full
  // MessageTurn (markdown + shiki + tool-call rendering). 200 picked
  // as the floor: well above the 14-msg average session, well below
  // the 580-item ceiling, and round.
  const VIRTUALIZE_THRESHOLD = 200;
  // Number of items at the bottom of the timeline that always mount
  // unconditionally. The streaming tail mutates in place during a
  // turn (reducer relies on the existing DOM), and auto-scroll uses
  // the bottom items as its anchor — both must stay real, never
  // placeholders. 30 items covers a typical user-prompt + assistant
  // + several tool calls without bringing in the long-history tail.
  const ALWAYS_WARM_TAIL = 30;
  const useVirtualization = $derived(timeline.length > VIRTUALIZE_THRESHOLD);

  function onJumpToAuditTarget(targetId: string) {
    sessions.select(targetId);
  }

  /** Turn key of the chronologically last turn that has a finished
   * (non-streaming) assistant message. The "ℹ MORE" button only
   * renders on this turn — see decision 2026-04-22 in TODO.md
   * "Feature: More info button". A streaming turn doesn't qualify
   * (asking for "more detail on your previous response" before that
   * response finishes is incoherent), but the in-place tail mutation
   * leaves a streaming tail's `assistant` field null until
   * `message_complete` finalizes it, so the backwards scan naturally
   * skips it without needing a separate "settled-only" array.
   */
  const latestAssistantTurnKey = $derived.by((): string | null => {
    for (let i = turns.length - 1; i >= 0; i -= 1) {
      const t = turns[i];
      if (t.assistant !== null) return t.key;
    }
    return null;
  });

  let promptText = $state('');
  let scrollContainer: HTMLDivElement | undefined = $state();
  let editingSession = $state(false);
  let exporting = $state(false);
  let copiedMsgId = $state<string | null>(null);
  let copiedSession = $state(false);
  let textareaEl: HTMLTextAreaElement | undefined = $state();

  // Per-session draft persistence: when the user types and navigates
  // away without sending, the text survives reloads and session
  // switches. The two effects below are split so loading on session
  // change doesn't retrigger on every keystroke. `lastLoadedSessionId`
  // also drives the pre-switch flush in `onSend` and cleanup — without
  // it we'd read the wrong session's id once selection has already
  // moved on.
  let lastLoadedSessionId = $state<string | null>(null);

  $effect(() => {
    const sid = sessions.selected?.id ?? null;
    if (sid === lastLoadedSessionId) return;
    // Commit the outgoing session's in-flight debounced write before
    // hydrating the incoming one. Otherwise the last few characters
    // typed just before the switch would be lost.
    if (lastLoadedSessionId !== null) drafts.flush(lastLoadedSessionId);
    lastLoadedSessionId = sid;
    promptText = sid === null ? '' : drafts.get(sid);
  });

  $effect(() => {
    const sid = lastLoadedSessionId;
    const text = promptText;
    if (sid === null) return;
    drafts.set(sid, text);
  });

  // Flush the pending debounced write on page hide so the tail end
  // of the user's typing survives an abrupt tab close or reload.
  // `beforeunload` covers full navigation; `pagehide` catches
  // bfcache-restored tabs and mobile suspensions the former misses.
  $effect(() => {
    if (typeof window === 'undefined') return;
    const flushNow = () => {
      const sid = lastLoadedSessionId;
      if (sid !== null) drafts.flush(sid);
    };
    window.addEventListener('beforeunload', flushNow);
    window.addEventListener('pagehide', flushNow);
    return () => {
      window.removeEventListener('beforeunload', flushNow);
      window.removeEventListener('pagehide', flushNow);
    };
  });

  // Shell-style Up/Down arrow history over prior user prompts for the
  // current session. Entries are derived from the client-side message
  // cache — no new API, and "recent history" (whatever's paginated in)
  // is an acceptable scope. Reset on session switch so walking doesn't
  // leak across sessions.
  let historyState = $state<HistoryState>(emptyHistoryState());
  const historyEntries = $derived(
    conversation.messages.filter((m) => m.role === 'user').map((m) => m.content)
  );
  $effect(() => {
    void sessions.selectedId;
    historyState = emptyHistoryState();
  });

  /** Move caret to the end of the textarea after a history swap.
   * queueMicrotask lets Svelte push the new `promptText` into the DOM
   * before we read `.value.length`, otherwise the range would target
   * the pre-update contents. */
  function setCaretToEnd() {
    const el = textareaEl;
    if (!el) return;
    queueMicrotask(() => {
      const end = el.value.length;
      el.selectionStart = end;
      el.selectionEnd = end;
    });
  }

  // Slash-command palette. Entries are fetched once per session
  // (keyed by id) so opening the menu doesn't restart the filesystem
  // walk every keystroke. The menu opens only when the first character
  // is `/` and there's no whitespace yet — matches the CLI, and means
  // adding args (`/fad:ship --dry`) dismisses it.
  let commandEntries = $state<api.CommandEntry[]>([]);
  let commandEntriesSessionId = $state<string | null>(null);
  let commandMenu: { handleKey: (e: KeyboardEvent) => boolean } | undefined = $state();

  const commandMenuOpen = $derived(
    promptText.startsWith('/') && !/\s/.test(promptText)
  );
  const commandQuery = $derived(
    commandMenuOpen ? promptText.slice(1) : ''
  );

  $effect(() => {
    const sid = sessions.selected?.id ?? null;
    if (sid === null || sid === commandEntriesSessionId) return;
    commandEntriesSessionId = sid;
    const cwd = sessions.selected?.working_dir ?? null;
    api.listCommands(cwd).then(
      (r) => {
        // Guard against session switch during the round-trip.
        if (commandEntriesSessionId === sid) commandEntries = r.entries;
      },
      () => {
        // Palette is a convenience; a failed fetch just means no menu,
        // not an error the user needs to see.
      }
    );
  });

  function onSelectCommand(slug: string) {
    promptText = `/${slug} `;
    // Return focus to the textarea so the user can keep typing args.
    queueMicrotask(() => textareaEl?.focus());
  }

  function onCloseCommandMenu() {
    // Insert a space after the slash so the menu closes without
    // dropping what the user already typed.
    if (promptText.startsWith('/') && !/\s/.test(promptText)) {
      promptText = `${promptText} `;
    }
  }

  async function onCopyMessage(msg: api.Message) {
    if (!(await copyText(msg.content))) return;
    copiedMsgId = msg.id;
    setTimeout(() => {
      if (copiedMsgId === msg.id) copiedMsgId = null;
    }, 1500);
  }

  /** "More info" button on the most-recent assistant turn (decision
   * 2026-04-22 in TODO.md): pre-fill composer with the elaborate
   * prompt and focus it — no auto-send. Dave can append a qualifier
   * ("…especially about X") and Enter, or Esc-clear and back out.
   * The prompt is intentionally minimal because the reply is already
   * in context for the model; a richer quoted template would waste
   * tokens and ambiguate "which version am I elaborating on?" */
  const MORE_INFO_PROMPT = 'Please go into more detail on your previous response.';
  function onMoreInfo(_msg: api.Message) {
    promptText = MORE_INFO_PROMPT;
    queueMicrotask(() => textareaEl?.focus());
  }

  // Slice 3: Session Reorg — Move + Split ops driven from the per-
  // message ⋯ menu. `pickerOp` flips the picker's confirm label; the
  // anchor is the message the menu was opened from. Slice 4 added the
  // bulk variants: `bulk-move` moves the current selection to an
  // existing or new target, `bulk-split` moves the selection into a
  // fresh session (picker opens on the create form). Slice 5 added
  // `merge`: folds the entire source into an existing target (no
  // create-new path, no per-message anchor).
  type PickerOp = 'move' | 'split' | 'bulk-move' | 'bulk-split' | 'merge';
  let pickerOpen = $state(false);
  let pickerOp = $state<PickerOp>('move');
  let pickerAnchor = $state<api.Message | null>(null);
  // Snapshot of the ids at picker-open for bulk ops — keeps the op
  // stable if the user happens to tweak the selection after opening.
  let pickerBulkIds = $state<string[]>([]);

  // Pending undo toast — one at a time. A new reorg op replaces it,
  // which is the desired behavior: the UI only guarantees Undo for
  // the most-recent op. Undo closures are pure per-op; the parent
  // clears them on dismiss/undo.
  //
  // Slice 7: `warnings` carries any tool-call-group split flags the
  // server surfaced for this op. Rendered above the message in the
  // toast so the user sees them before tapping Undo. Empty or absent
  // on successful well-formed ops (the common case).
  type UndoState = {
    message: string;
    warnings: api.ReorgWarning[];
    run: () => Promise<void>;
  };
  let undo = $state<UndoState | null>(null);

  // Slice 4: bulk-select mode. A lightweight parallel lane on top of
  // the existing reorg flows — checkboxes on each row, a floating
  // action bar, shift-click range selection. When active, the per-
  // message ⋯ menu is hidden in MessageTurn so the two surfaces
  // don't compete.
  let bulkMode = $state(false);
  let selectedIds = $state<Set<string>>(new Set());
  let lastSelectedId = $state<string | null>(null);

  function toggleBulkMode() {
    bulkMode = !bulkMode;
    if (!bulkMode) {
      selectedIds = new Set();
      lastSelectedId = null;
    }
  }

  function onBulkToggleSelect(msg: api.Message, shiftKey: boolean) {
    const all = conversation.messages;
    if (shiftKey && lastSelectedId) {
      const a = all.findIndex((m) => m.id === lastSelectedId);
      const b = all.findIndex((m) => m.id === msg.id);
      if (a >= 0 && b >= 0) {
        const [lo, hi] = a < b ? [a, b] : [b, a];
        const next = new Set(selectedIds);
        for (let i = lo; i <= hi; i++) next.add(all[i].id);
        selectedIds = next;
        lastSelectedId = msg.id;
        return;
      }
    }
    const next = new Set(selectedIds);
    if (next.has(msg.id)) next.delete(msg.id);
    else next.add(msg.id);
    selectedIds = next;
    lastSelectedId = msg.id;
  }

  function openMoveFor(msg: api.Message) {
    pickerOp = 'move';
    pickerAnchor = msg;
    pickerBulkIds = [];
    pickerOpen = true;
  }

  function openSplitFor(msg: api.Message) {
    pickerOp = 'split';
    pickerAnchor = msg;
    pickerBulkIds = [];
    pickerOpen = true;
  }

  // Phase 5 bridge: `actions/message.ts` publishes move/split requests
  // to `reorgStore`; this effect picks them up and opens the picker for
  // the active session. Requests for other sessions are ignored — if
  // the user right-clicks a message in a background tab (e.g. via the
  // palette while on a different session), the Conversation mounted
  // against that session handles it, not this one.
  $effect(() => {
    const req = reorgStore.pending;
    if (!req) return;
    if (req.sessionId !== sessions.selectedId) return;
    const msg = conversation.messages.find((m) => m.id === req.messageId);
    if (!msg) return;
    reorgStore.clear();
    if (req.kind === 'move') openMoveFor(msg);
    else openSplitFor(msg);
  });

  function onBulkMove() {
    if (selectedIds.size === 0) return;
    pickerOp = 'bulk-move';
    pickerAnchor = null;
    pickerBulkIds = [...selectedIds];
    pickerOpen = true;
  }

  function onBulkSplit() {
    if (selectedIds.size === 0) return;
    pickerOp = 'bulk-split';
    pickerAnchor = null;
    pickerBulkIds = [...selectedIds];
    pickerOpen = true;
  }

  function openMerge() {
    pickerOp = 'merge';
    pickerAnchor = null;
    pickerBulkIds = [];
    pickerOpen = true;
  }

  /** Toggle the active session's closed flag. No confirmation dialog —
   * a closed session is trivially reopenable and lives one click away
   * in the sidebar's "Closed" group. */
  async function onToggleClosed() {
    const sid = sessions.selectedId;
    if (!sid) return;
    const current = sessions.selected;
    if (!current) return;
    if (current.closed_at) {
      await sessions.reopen(sid);
    } else {
      await sessions.close(sid);
    }
  }

  function closePicker() {
    pickerOpen = false;
    pickerAnchor = null;
    pickerBulkIds = [];
  }

  function pickerTitle(op: PickerOp, bulkCount: number): string {
    if (op === 'split') return 'Split remaining messages into…';
    if (op === 'bulk-move') {
      return `Move ${bulkCount} selected message${bulkCount === 1 ? '' : 's'} to…`;
    }
    if (op === 'bulk-split') {
      return `Split ${bulkCount} selected message${bulkCount === 1 ? '' : 's'} into a new session`;
    }
    if (op === 'merge') return 'Merge this session into…';
    return 'Move message to…';
  }

  function pickerConfirmLabel(op: PickerOp): string {
    if (op === 'split' || op === 'bulk-split') return 'Split here';
    if (op === 'merge') return 'Merge here';
    return 'Move here';
  }

  // Slice 5: persistent reorg-audit dividers. Fetched on session
  // switch, refreshed after every reorg op (including undos) so the
  // timeline stays truthful without waiting for a reload. The list
  // itself lives on `ConversationStore` (item 29 / 2026-04-24 refactor)
  // so `setAudits` can re-merge it into the store-owned timeline; the
  // pane still owns the fetch trigger.
  async function refreshAudits(): Promise<void> {
    const sid = sessions.selectedId;
    if (!sid) return;
    try {
      const rows = await api.listReorgAudits(sid);
      if (sessions.selectedId === sid) conversation.setAudits(sid, rows);
    } catch {
      // Non-fatal — the conversation still renders without dividers.
    }
  }

  $effect(() => {
    const sid = sessions.selected?.id ?? null;
    if (!sid) return;
    // Track updated_at so a server-side bump (e.g., a move from the
    // other end) also invalidates the audit list on refocus.
    void sessions.selected?.updated_at;
    void refreshAudits();
  });

  /** Run after a successful Move so the view reconciles against the
   * server. Refreshes the sidebar + active conversation so the moved
   * rows disappear immediately instead of waiting for the next event.
   * Also re-pulls the audit list when the current session is on either
   * end of the op — new/undone dividers surface without a reload. */
  async function reconcileAfterReorg(affectedIds: string[]) {
    await sessions.refresh(sessions.filter);
    const currentSid = sessions.selectedId;
    if (currentSid && affectedIds.includes(currentSid)) {
      await conversation.load(currentSid);
      await refreshAudits();
    }
  }

  /** Wrap an undo closure with audit-row cleanup. If the server
   * returned an `audit_id`, the divider is removed as part of the
   * undo so the user doesn't see a stale "Moved N messages to X"
   * line for an op that was reversed. The delete is scoped to
   * `sourceId` and swallows 404s — a second-click race against the
   * user manually deleting the divider should not blow up the undo. */
  async function deleteAuditSafe(sourceId: string, auditId: number | null) {
    if (auditId == null) return;
    try {
      await api.deleteReorgAudit(sourceId, auditId);
    } catch {
      // Row was already gone — fine, undo still succeeded.
    }
  }

  async function doMove(
    sourceId: string,
    msgId: string,
    targetSessionId: string,
    label: string
  ) {
    try {
      const result = await api.reorgMove(sourceId, {
        target_session_id: targetSessionId,
        message_ids: [msgId]
      });
      await reconcileAfterReorg([sourceId, targetSessionId]);
      const auditId = result.audit_id;
      undo = {
        message: `Moved ${result.moved} message to ${label}.`,
        warnings: result.warnings,
        run: async () => {
          await api.reorgMove(targetSessionId, {
            target_session_id: sourceId,
            message_ids: [msgId]
          });
          await deleteAuditSafe(sourceId, auditId);
          await reconcileAfterReorg([sourceId, targetSessionId]);
        }
      };
    } catch (e) {
      conversation.error = e instanceof Error ? e.message : String(e);
    }
  }

  /** Slice 4: bulk move of an explicit id list into an existing target.
   * Undo is a straight reverse move — no session cleanup needed since
   * the target already existed before the op. */
  async function doBulkMove(
    sourceId: string,
    msgIds: string[],
    targetSessionId: string,
    label: string,
    deleteTargetOnUndo = false
  ) {
    try {
      const result = await api.reorgMove(sourceId, {
        target_session_id: targetSessionId,
        message_ids: msgIds
      });
      await reconcileAfterReorg([sourceId, targetSessionId]);
      // Exit bulk mode on success — the rows the user was selecting
      // are gone from this view, so the checkboxes would dangle.
      bulkMode = false;
      selectedIds = new Set();
      lastSelectedId = null;
      const plural = result.moved === 1 ? '' : 's';
      const auditId = result.audit_id;
      undo = {
        message: `Moved ${result.moved} message${plural} to ${label}.`,
        warnings: result.warnings,
        run: async () => {
          await api.reorgMove(targetSessionId, {
            target_session_id: sourceId,
            message_ids: msgIds
          });
          if (deleteTargetOnUndo) {
            // Deleting the target cascades the audit row automatically,
            // so we skip the explicit delete in that branch.
            await api.deleteSession(targetSessionId);
          } else {
            await deleteAuditSafe(sourceId, auditId);
          }
          await reconcileAfterReorg([sourceId, targetSessionId]);
        }
      };
    } catch (e) {
      conversation.error = e instanceof Error ? e.message : String(e);
    }
  }

  async function doSplit(
    sourceId: string,
    anchorMsgId: string,
    draft: { title: string; tag_ids: number[] }
  ) {
    try {
      const result = await api.reorgSplit(sourceId, {
        after_message_id: anchorMsgId,
        new_session: { title: draft.title, tag_ids: draft.tag_ids }
      });
      await reconcileAfterReorg([sourceId, result.session.id]);
      const newId = result.session.id;
      const movedCount = result.result.moved;
      // Inverse is "move everything back + delete the new session";
      // deleting the new session cascades its audit row, so no
      // explicit deleteReorgAudit call here.
      undo = {
        message: `Split off ${movedCount} message${movedCount === 1 ? '' : 's'} into "${
          result.session.title ?? '(untitled)'
        }".`,
        warnings: result.result.warnings,
        run: async () => {
          const rows = await api.listMessages(newId);
          if (rows.length > 0) {
            await api.reorgMove(newId, {
              target_session_id: sourceId,
              message_ids: rows.map((m) => m.id)
            });
          }
          await api.deleteSession(newId);
          await reconcileAfterReorg([sourceId, newId]);
        }
      };
    } catch (e) {
      conversation.error = e instanceof Error ? e.message : String(e);
    }
  }

  /** Slice 5: fold the entire source into `targetSessionId`. The
   * frontend always passes `delete_source=false` — keeping the source
   * alive so the user has somewhere to render the audit divider and
   * hit Undo from. If they really want the source gone they can
   * delete it by hand after the undo window lapses.
   *
   * We snapshot the source's message ids BEFORE the merge so the
   * undo knows exactly which rows to move back — `move_messages_tx`
   * preserves `created_at`, so "the N newest rows on the target"
   * isn't necessarily "the ones we just moved over."
   */
  async function doMerge(sourceId: string, targetSessionId: string, label: string) {
    try {
      const sourceRows = await api.listMessages(sourceId);
      const sourceIds = sourceRows.map((m) => m.id);
      const result = await api.reorgMerge(sourceId, {
        target_session_id: targetSessionId,
        delete_source: false
      });
      await reconcileAfterReorg([sourceId, targetSessionId]);
      const auditId = result.audit_id;
      const movedCount = result.moved;
      const plural = movedCount === 1 ? '' : 's';
      undo = {
        message:
          movedCount === 0
            ? `No messages to merge into ${label}.`
            : `Merged ${movedCount} message${plural} into ${label}.`,
        warnings: result.warnings,
        run: async () => {
          if (sourceIds.length > 0) {
            await api.reorgMove(targetSessionId, {
              target_session_id: sourceId,
              message_ids: sourceIds
            });
          }
          await deleteAuditSafe(sourceId, auditId);
          await reconcileAfterReorg([sourceId, targetSessionId]);
        }
      };
    } catch (e) {
      conversation.error = e instanceof Error ? e.message : String(e);
    }
  }

  async function onPickerPickExisting(targetId: string) {
    const sourceId = sessions.selectedId;
    if (!sourceId) {
      closePicker();
      return;
    }
    const targetLabel =
      sessions.list.find((s) => s.id === targetId)?.title ?? 'session';
    const op = pickerOp;
    const msg = pickerAnchor;
    const bulkIds = pickerBulkIds;
    closePicker();

    if (op === 'bulk-move') {
      if (bulkIds.length === 0) return;
      await doBulkMove(sourceId, bulkIds, targetId, `"${targetLabel}"`);
      return;
    }
    if (op === 'bulk-split') {
      // Split-into-existing collapses to a bulk move against the
      // chosen target. The user opened the picker in "split into
      // new" mode but backed out to pick an existing row — that's
      // semantically a bulk move, so treat it that way.
      if (bulkIds.length === 0) return;
      await doBulkMove(sourceId, bulkIds, targetId, `"${targetLabel}"`);
      return;
    }
    if (op === 'merge') {
      await doMerge(sourceId, targetId, `"${targetLabel}"`);
      return;
    }
    if (!msg) return;
    if (op === 'move') {
      await doMove(sourceId, msg.id, targetId, `"${targetLabel}"`);
      return;
    }
    // Split into an EXISTING session = "move everything after anchor
    // over there." No new session created, so we reuse the move route
    // with the collected post-anchor ids.
    const all = conversation.messages;
    const idx = all.findIndex((m) => m.id === msg.id);
    if (idx < 0) return;
    const toMove = all.slice(idx + 1).map((m) => m.id);
    if (toMove.length === 0) {
      conversation.error = 'No messages after the anchor to split.';
      return;
    }
    await doBulkMove(sourceId, toMove, targetId, `"${targetLabel}"`);
  }

  async function onPickerPickNew(draft: { title: string; tag_ids: number[] }) {
    const sourceId = sessions.selectedId;
    if (!sourceId) {
      closePicker();
      return;
    }
    const op = pickerOp;
    const msg = pickerAnchor;
    const bulkIds = pickerBulkIds;
    closePicker();

    if (op === 'split' && msg) {
      await doSplit(sourceId, msg.id, draft);
      return;
    }
    if (op === 'bulk-move' || op === 'bulk-split') {
      if (bulkIds.length === 0) return;
      const created = await createEmptySession(sourceId, draft);
      if (!created) return;
      await doBulkMove(
        sourceId,
        bulkIds,
        created.id,
        `"${created.title ?? '(untitled)'}"`,
        true
      );
      return;
    }
    if (!msg) return;
    // Single-message move to a brand-new session: create the row,
    // then move. Use the api call directly (not sessions.create) so
    // we don't flip the selected session out from under the user
    // mid-triage. `reconcileAfterReorg` refreshes the sidebar list.
    const created = await createEmptySession(sourceId, draft);
    if (!created) return;
    await doMove(sourceId, msg.id, created.id, `"${created.title ?? '(untitled)'}"`);
  }

  async function createEmptySession(
    sourceId: string,
    draft: { title: string; tag_ids: number[] }
  ): Promise<api.Session | null> {
    const source = sessions.list.find((s) => s.id === sourceId);
    if (!source) return null;
    try {
      return await api.createSession({
        working_dir: source.working_dir,
        model: source.model,
        title: draft.title,
        tag_ids: draft.tag_ids
      });
    } catch (e) {
      conversation.error = e instanceof Error ? e.message : String(e);
      return null;
    }
  }

  function onUndoDismiss() {
    undo = null;
  }

  async function onCopySession() {
    const sid = sessions.selectedId;
    if (!sid || copiedSession) return;
    // Pull the full list so the copy isn't limited to what's paged in.
    const dump = await api.exportSession(sid);
    if (!(await copyText(messagesAsMarkdown(dump.messages)))) return;
    copiedSession = true;
    setTimeout(() => (copiedSession = false), 1500);
  }

  // Header session-description clamp. Long plugs (multi-paragraph
  // design briefs, bug-report pastes) would otherwise eat half the
  // viewport above the conversation — we collapse to 3 lines with a
  // "show more" toggle and re-measure whenever the session or its
  // description changes.
  let descriptionEl: HTMLParagraphElement | undefined = $state();
  let descriptionExpanded = $state(false);
  let descriptionOverflows = $state(false);

  $effect(() => {
    // Re-run when the selected session or its description text flips.
    const sid = sessions.selected?.id ?? null;
    const text = sessions.selected?.description ?? '';
    descriptionExpanded = false;
    if (!sid || !text || !descriptionEl) {
      descriptionOverflows = false;
      return;
    }
    // Measure on the next microtask so the clamp class has applied
    // before we compare scroll vs client height.
    const el = descriptionEl;
    queueMicrotask(() => {
      descriptionOverflows = el.scrollHeight > el.clientHeight + 1;
    });
  });

  // Paired-chat breadcrumb (v0.5.0, Slice 4 of nimble-checking-heron).
  // When the selected session was spawned from a checklist item, we
  // resolve the item + parent title so the header can render a
  // clickable "📋 parent-title › item-label" trail back to the source.
  // Refetches on session change; silent on 404 because the pairing
  // may have been severed (checklist or item deleted) between renders.
  type PairedChatCrumb = {
    parentId: string;
    parentTitle: string;
    itemId: number;
    itemLabel: string;
  };
  let pairedCrumb = $state<PairedChatCrumb | null>(null);

  $effect(() => {
    const current = sessions.selected;
    if (!current || current.checklist_item_id == null) {
      pairedCrumb = null;
      return;
    }
    const sid = current.id;
    const itemId = current.checklist_item_id;
    // The item's parent checklist id is whichever session ids we
    // already have in the sidebar store — scan for the one whose
    // `kind === 'checklist'` with a matching item. The lookup is
    // cheap (sidebar list is typically <100 entries) and avoids
    // adding a dedicated reverse-lookup endpoint. If the parent
    // isn't in the store (e.g. fresh page load, sidebar still
    // loading), skip this pass and the effect reruns when the list
    // updates.
    const parent = sessions.list.find(
      (s) => s.kind === 'checklist' && s.id !== sid
    );
    // Fallback path: fetch the item + checklist so the breadcrumb
    // still renders even when the parent isn't in the sidebar yet.
    // Use the item's `checklist_id` (== parent session id) so we
    // don't need to guess.
    (async () => {
      // Probe every candidate checklist until one returns the item
      // we care about. In practice the sidebar carries the parent
      // for any recently-opened paired chat, so this rarely fans
      // out beyond one call.
      const candidates = parent ? [parent] : sessions.list.filter((s) => s.kind === 'checklist');
      for (const cand of candidates) {
        try {
          const checklist = await api.getChecklist(cand.id);
          const match = checklist.items.find((i) => i.id === itemId);
          if (match && sessions.selected?.id === sid) {
            pairedCrumb = {
              parentId: cand.id,
              parentTitle: cand.title ?? '(untitled checklist)',
              itemId: match.id,
              itemLabel: match.label
            };
            return;
          }
        } catch {
          // Deleted or inaccessible — try the next candidate.
        }
      }
      if (sessions.selected?.id === sid) pairedCrumb = null;
    })();
  });

  // Tag chips in the header. Refetch on session change and on
  // `updated_at` bumps (SessionEdit attach/detach bumps the server).
  let sessionTags = $state<api.Tag[]>([]);

  $effect(() => {
    const sid = sessions.selected?.id ?? null;
    void sessions.selected?.updated_at;
    if (!sid) {
      sessionTags = [];
      return;
    }
    api.listSessionTags(sid).then((r) => (sessionTags = r), () => {});
  });

  // Subscription-mode token totals for the header. Only fetched when
  // billing mode is `subscription` — PAYG users never hit the endpoint
  // and the meter is not rendered. Refreshed on session change and
  // whenever a streaming turn completes (streamingActive true → false),
  // which is the same cadence at which `total_cost_usd` would move.
  let tokenTotals = $state<api.TokenTotals | null>(null);
  let prevStreaming = false;

  $effect(() => {
    const sid = sessions.selected?.id ?? null;
    if (!sid || !billing.showTokens) {
      tokenTotals = null;
      return;
    }
    // Fetch once on session change. The completion effect below
    // handles subsequent refreshes.
    api.getSessionTokens(sid).then(
      (r) => {
        if (sessions.selected?.id === sid) tokenTotals = r;
      },
      () => {
        // Non-fatal — leave the prior totals (or null placeholder) in
        // place. /tokens failing does not warrant a visible error.
      }
    );
  });

  $effect(() => {
    const active = conversation.streamingActive;
    const sid = sessions.selected?.id ?? null;
    if (!sid || !billing.showTokens) {
      prevStreaming = active;
      return;
    }
    // Trailing edge: a turn just finished. Refresh the aggregate so
    // the meter reflects the new per-turn usage. Using an edge trigger
    // (rather than a timer) keeps this cheap — one fetch per turn.
    if (prevStreaming && !active) {
      api.getSessionTokens(sid).then(
        (r) => {
          if (sessions.selected?.id === sid) tokenTotals = r;
        },
        () => {}
      );
    }
    prevStreaming = active;
  });

  async function onExport() {
    const sid = sessions.selectedId;
    if (!sid || exporting) return;
    exporting = true;
    try {
      const dump = await api.exportSession(sid);
      const blob = new Blob([JSON.stringify(dump, null, 2)], {
        type: 'application/json'
      });
      const url = URL.createObjectURL(blob);
      const day = new Date().toISOString().slice(0, 10).replaceAll('-', '');
      const name = `session-${sid.slice(0, 8)}-${day}.json`;
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } finally {
      exporting = false;
    }
  }

  $effect(() => {
    void conversation.messages;
    void conversation.streamingText;
    if (scrollContainer) {
      queueMicrotask(() => {
        if (scrollContainer) scrollContainer.scrollTop = scrollContainer.scrollHeight;
      });
    }
  });

  const SCROLL_TOP_THRESHOLD = 40;

  $effect(() => {
    const el = scrollContainer;
    if (!el) return;
    async function onScroll() {
      if (!el) return;
      if (el.scrollTop > SCROLL_TOP_THRESHOLD) return;
      if (!conversation.hasMore || conversation.loadingOlder) return;
      const prevHeight = el.scrollHeight;
      await conversation.loadOlder();
      // Preserve viewport: after prepend, keep the first-previously-
      // visible message in the same screen position.
      if (el) el.scrollTop = el.scrollHeight - prevHeight;
    }
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  });

  function onSend() {
    const text = promptText.trim();
    if (!text) return;
    // Filter the sidecar to attachments the user actually kept
    // referenced in the prompt — if they deleted `[File 2]` after
    // dropping it, we don't send its path along. The backend applies
    // the same pruning rule (`referenced_ns` in
    // `bearings/agent/_attachments.py`); we mirror it here so the
    // optimistic user bubble matches what the server will persist.
    const referenced = new Set<number>();
    const re = new RegExp(ATTACHMENT_TOKEN_REGEX.source, 'g');
    let match: RegExpExecArray | null;
    while ((match = re.exec(text)) !== null) referenced.add(Number(match[1]));
    const activeAttachments = composerAttachments.filter((a) => referenced.has(a.n));
    if (!agent.send(text, activeAttachments)) return;
    // Clear the persisted draft before resetting `promptText` so the
    // debounced writer in the save effect doesn't race the clear and
    // re-persist an empty string (harmless but pointless I/O).
    const sid = lastLoadedSessionId;
    if (sid !== null) drafts.clear(sid);
    promptText = '';
    composerAttachments = [];
    nextAttachmentN = 1;
    // A successful send is an implicit "leave history mode" — the
    // next Up should stash the (empty) draft and walk back through
    // the newly-extended history.
    historyState = emptyHistoryState();
  }

  function onKeydown(e: KeyboardEvent) {
    // The command menu claims arrow/Enter/Tab/Escape while open so the
    // user can navigate without leaving the textarea. It returns false
    // for other keys so normal typing still flows through.
    if (commandMenu?.handleKey(e)) return;
    // Shell-style history on Up/Down. Guards mirror readline: no
    // modifiers (so Shift-select and Ctrl-shortcuts are untouched),
    // no IME composition, caret must be at the first/last visual
    // line with no active selection (so multi-line editing still
    // works the obvious way).
    if (
      (e.key === 'ArrowUp' || e.key === 'ArrowDown') &&
      !e.shiftKey &&
      !e.ctrlKey &&
      !e.altKey &&
      !e.metaKey &&
      !e.isComposing
    ) {
      const el = textareaEl;
      if (el) {
        const start = el.selectionStart ?? 0;
        const end = el.selectionEnd ?? 0;
        if (e.key === 'ArrowUp' && caretOnFirstLine(promptText, start, end)) {
          const step = prevHistory(historyState, historyEntries, promptText);
          if (step.changed) {
            e.preventDefault();
            historyState = step.state;
            promptText = step.text;
            setCaretToEnd();
            return;
          }
        } else if (
          e.key === 'ArrowDown' &&
          caretOnLastLine(promptText, start, end)
        ) {
          const step = nextHistory(historyState, historyEntries);
          if (step.changed) {
            e.preventDefault();
            historyState = step.state;
            promptText = step.text;
            setCaretToEnd();
            return;
          }
        }
      }
    }
    // Enter sends; Shift+Enter falls through so the textarea inserts
    // a newline. Skip while the user is mid-IME composition.
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      onSend();
    }
  }

  /** Called on textarea `input`. If the user edits the text after
   * walking into history, exit history mode so the next Up treats
   * the edited text as the new baseline and stashes it. Programmatic
   * updates (history swap, slash-insert, paste) shouldn't trigger
   * the reset — those set `promptText` directly without firing
   * `input`, or are handled elsewhere. */
  function onInput() {
    historyState = resetHistory(historyState);
  }

  // Prompt textarea auto-grow. Starts at a single row and stretches
  // as the user types until the content height hits PROMPT_MAX_PX;
  // past that, `overflow-y: auto` takes over so the rest scrolls
  // inside a fixed-height box. Recomputed on every value change —
  // cheap because `scrollHeight` is O(1) for a textarea.
  const PROMPT_MAX_PX = 240;

  function autosizeTextarea() {
    const el = textareaEl;
    if (!el) return;
    // Reset first so the measurement isn't capped by the previous
    // height. The `auto` pass lets scrollHeight report the content's
    // natural height even when it would shrink.
    el.style.height = 'auto';
    const next = Math.min(el.scrollHeight, PROMPT_MAX_PX);
    el.style.height = `${next}px`;
    el.style.overflowY = el.scrollHeight > PROMPT_MAX_PX ? 'auto' : 'hidden';
  }

  // Runs on every promptText change (including programmatic updates
  // from drop / upload / slash-command insertion). `queueMicrotask`
  // defers until Svelte has pushed the new value into the DOM.
  $effect(() => {
    void promptText;
    queueMicrotask(autosizeTextarea);
  });

  /** Insert a literal string at the cursor, with whitespace padding so
   * the insertion doesn't glue onto surrounding text. Used by both the
   * path-shaped fallback (`insertPathAtCursor`) and the terminal-style
   * attachment flow (`attachFileAtCursor`). Moves the caret to just
   * after the inserted text so typing continues naturally. */
  function insertAtCursor(literal: string) {
    const el = textareaEl;
    if (!el) {
      promptText = promptText ? `${promptText} ${literal}` : literal;
      return;
    }
    const start = el.selectionStart ?? promptText.length;
    const end = el.selectionEnd ?? promptText.length;
    const before = promptText.slice(0, start);
    const after = promptText.slice(end);
    const leftPad = before && !/\s$/.test(before) ? ' ' : '';
    const rightPad = after && !/^\s/.test(after) ? ' ' : '';
    const insertion = `${leftPad}${literal}${rightPad}`;
    promptText = before + insertion + after;
    queueMicrotask(() => {
      if (!textareaEl) return;
      const pos = before.length + insertion.length;
      textareaEl.setSelectionRange(pos, pos);
      textareaEl.focus();
    });
  }

  /** Kept for compatibility with any future caller that wants a
   * literal quoted path dropped into the prompt (slash commands, etc.).
   * The drop / upload / picker flows all use `attachFileAtCursor`
   * instead — that path inserts a `[File N]` token and tracks the
   * real path in a sidecar so the transcript stays tidy. */
  function insertPathAtCursor(path: string) {
    const needsQuote = /\s/.test(path);
    insertAtCursor(needsQuote ? `"${path}"` : path);
  }

  /** Composer sidecar for terminal-style `[File N]` attachments. The
   * textarea carries only the token literals — the real path + display
   * metadata live here until send, where we forward both to the agent
   * so the SDK sees the path and the DB keeps the tokenised content.
   *
   * `nextAttachmentN` is monotonically increasing across the life of a
   * single compose-and-send. Deleting a token from the text does NOT
   * renumber the remaining ones; the send-time prune filters orphans
   * by referenced-N instead. This matches the terminal Claude Code
   * behaviour where `[File 1]` stays `[File 1]` even after edits. */
  let composerAttachments = $state<MessageAttachment[]>([]);
  let nextAttachmentN = $state(1);

  /** Attach a file to the composer: push a sidecar entry with a fresh
   * `n` and insert the matching `[File N]` token at the cursor.
   *
   * All three drop paths (URI, bytes-upload, native-picker) funnel
   * through here. When the caller doesn't know `filename` or
   * `sizeBytes` (URI / picker don't include them), we derive the
   * filename from the path's basename and default size to 0; the
   * chip renderer falls back to showing just the name in that case. */
  function attachFileAtCursor(path: string, filename?: string, sizeBytes?: number): void {
    const n = nextAttachmentN;
    nextAttachmentN += 1;
    const baseName = filename ?? path.split('/').filter(Boolean).pop() ?? 'file';
    composerAttachments = [
      ...composerAttachments,
      { n, path, filename: baseName, size_bytes: sizeBytes ?? 0 }
    ];
    insertAtCursor(formatAttachmentToken(n));
  }

  /** Remove a composer attachment: drop the sidecar row AND strip every
   * `[File N]` occurrence from the textarea. Called from the chip
   * strip's `×` button. We don't renumber the surviving attachments —
   * keeping `n` stable matches the terminal Claude Code behaviour, and
   * the send-time prune already filters orphans so stray sidecar rows
   * never leak to the server. */
  function removeAttachment(n: number): void {
    composerAttachments = composerAttachments.filter((a) => a.n !== n);
    promptText = promptText.split(formatAttachmentToken(n)).join('');
  }

  /** Active sidecar chips — filter to attachments whose token is
   * actually still present in the text, so the composer chip strip
   * matches what the user can see above it. Kept as a derived value
   * so deletes update the strip without needing a manual sync on
   * every keystroke. */
  const activeComposerAttachments = $derived.by(() => {
    if (composerAttachments.length === 0) return [] as MessageAttachment[];
    const referenced = new Set<number>();
    const re = new RegExp(ATTACHMENT_TOKEN_REGEX.source, 'g');
    let m: RegExpExecArray | null;
    while ((m = re.exec(promptText)) !== null) referenced.add(Number(m[1]));
    return composerAttachments.filter((a) => referenced.has(a.n));
  });

  // Drag-and-drop file path injection. Linux file managers (Dolphin,
  // Nautilus, Thunar, the KDE dolphin-from-Hyprland combo Dave uses)
  // expose dragged files as `text/uri-list` with absolute `file://`
  // URIs — we parse those out and drop the local path into the
  // prompt. We deliberately don't read file bytes: Dave's instruction
  // was "all it has to do is give you the link so that you know where
  // the file is."
  //
  // Pattern mirrors SessionList.svelte (the working left-pane JSON
  // drop zone). Handlers are bound to the outermost `<section>` so the
  // whole pane — header, messages, textarea footer — accepts drops,
  // and the `relatedTarget`/`contains` trick handles child-flicker
  // without needing a depth counter.
  let dragging = $state(false);

  // Document-level dragover/drop default-suppression. Without this the
  // browser's default handler navigates the tab to `file://…` whenever
  // the user misses the section (or, on some compositors, always). The
  // listeners only preventDefault — the section's own `ondrop` still
  // does the real work.
  //
  // Scoping note: only suppress when the event target is OUTSIDE the
  // section. Inside-section events go through the section's own
  // ondragover/ondrop; suppressing at the document level too was
  // plausibly the reason Chrome+Wayland stopped delivering drop events
  // to our handlers on some DOM trees (the double-preventDefault
  // confused the drop-target chain). SessionList.svelte — the working
  // reference in this same codebase — has NO document-level listeners
  // and its drop zone works reliably. Matching that pattern.
  let sectionEl: HTMLElement | null = $state(null);
  $effect(() => {
    function swallow(e: DragEvent) {
      // Only suppress when the event target is OUTSIDE the section —
      // inside-section events go through the section's own handlers,
      // and double-preventDefault at both document and section level
      // was observed to confuse Chrome+Wayland's drop-target chain
      // during the v0.10.0 DnD debug. Keep the outside-of-section
      // swallow because without it a misplaced drop navigates the
      // tab to `file://…`.
      const inside =
        !!sectionEl && e.target instanceof Node && sectionEl.contains(e.target);
      if (!inside) e.preventDefault();
    }
    document.addEventListener('dragover', swallow);
    document.addEventListener('drop', swallow);
    return () => {
      document.removeEventListener('dragover', swallow);
      document.removeEventListener('drop', swallow);
    };
  });

  function hasFiles(e: DragEvent): boolean {
    return e.dataTransfer?.types.includes('Files') ?? false;
  }

  function parseUriList(text: string): string[] {
    // RFC 2483: lines starting with `#` are comments. Blank lines are
    // separators. Each remaining line is one URI.
    const out: string[] = [];
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;
      if (!line.startsWith('file://')) continue;
      try {
        const url = new URL(line);
        if (url.hostname && url.hostname !== 'localhost') continue;
        out.push(decodeURIComponent(url.pathname));
      } catch {
        // Malformed URI — skip rather than inject garbage.
      }
    }
    return out;
  }

  function onDragEnter(e: DragEvent) {
    if (hasFiles(e)) dragging = true;
  }

  function onDragOver(e: DragEvent) {
    // preventDefault UNCONDITIONALLY whenever a drag is in flight.
    // Chrome on Wayland exposes an EMPTY `types` list during dragover
    // (types only arrive reliably on dragenter/drop), so gating this
    // on hasFiles(e) would fall through without preventDefault and
    // Chrome would then refuse to dispatch `drop` to this target —
    // verified live against the server access log during the v0.10.0
    // DnD shakeout. Firefox accepts unconditional preventDefault
    // fine; Chrome (on supported compositors) needs it.
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'link';
  }

  function onDragLeave(e: DragEvent) {
    // Only clear when leaving the section entirely, not when crossing
    // into a child element.
    const related = e.relatedTarget as Node | null;
    if (!related || !(e.currentTarget as Node).contains(related)) {
      dragging = false;
    }
  }

  /** Pull candidate absolute paths out of every DataTransfer format the
   * browser/OS combo might expose. Chromium on Linux is inconsistent:
   * Nautilus/Thunar usually set `text/uri-list`, Dolphin sometimes sets
   * only `text/plain` with a `file://` URI, and some Wayland setups
   * strip URIs entirely for security. We try everything and dedupe. */
  function extractPaths(dt: DataTransfer): { paths: string[]; formats: string[] } {
    const formats: string[] = [];
    const paths = new Set<string>();
    const tryFormat = (fmt: string) => {
      const raw = dt.getData(fmt);
      if (!raw) return;
      formats.push(`${fmt}=${raw.slice(0, 200)}`);
      for (const p of parseUriList(raw)) paths.add(p);
      // Raw-path fallback: some sources (KDE, xdg, plain-text drags)
      // put the absolute path directly, no file:// prefix.
      for (const line of raw.split(/\r?\n/)) {
        const trimmed = line.trim();
        if (trimmed.startsWith('/') && !trimmed.includes(' ')) paths.add(trimmed);
      }
    };
    tryFormat('text/uri-list');
    tryFormat('text/x-moz-url');
    tryFormat('application/x-kde4-urilist');
    tryFormat('text/plain');
    return { paths: [...paths], formats };
  }

  // Drop diagnostic state lives OUTSIDE `conversation.error` because that
  // store only renders at the tail of the message list — invisible when
  // scrolled up or when the session has no messages. We surface this as
  // a dedicated banner above the text entry so the user always sees it.
  let dropDiagnostic = $state<string | null>(null);

  // Upload-in-flight state. Drives a small "Uploading N file(s)…" status
  // pill next to the attach-file button so the user gets feedback during
  // the bytes-upload fallback path (multi-MB files can take a beat over
  // localhost, and a silent freeze would look like the drop failed).
  let uploading = $state(false);

  /** Bytes-upload fallback path for drops that exposed no filesystem
   * path. Chrome on Wayland strips `text/uri-list` and `text/plain`
   * even when the File objects are fully readable — so we read the
   * bytes with file.arrayBuffer(), POST each to `/api/uploads`, and
   * inject the resulting absolute path at the cursor. Order is
   * preserved by awaiting each upload in sequence rather than firing
   * parallel POSTs whose `insertPathAtCursor` calls would race the
   * textarea selection. */
  async function uploadDroppedFiles(files: FileList): Promise<void> {
    if (uploading) return;
    uploading = true;
    try {
      for (const file of Array.from(files)) {
        try {
          const result = await uploadsApi.uploadFile(file);
          attachFileAtCursor(result.path, result.filename, result.size_bytes);
        } catch (e) {
          // Surface the specific reason (413 over-size, 415 blocked
          // extension, 500 disk full) so the user can act. The banner
          // replaces any prior diagnostic — a mid-batch reject is the
          // most relevant thing to see.
          const msg = e instanceof Error ? e.message : String(e);
          dropDiagnostic = `Upload failed for "${file.name}": ${msg}`;
          return;
        }
      }
      dropDiagnostic = null;
    } finally {
      uploading = false;
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    dragging = false;
    if (!e.dataTransfer) return;
    const { paths, formats } = extractPaths(e.dataTransfer);
    if (paths.length > 0) {
      // Happy path — the OS handed us URIs, no upload needed. Preserves
      // the original "all it has to do is give you the link" behavior
      // from file managers that still expose text/uri-list. URIs don't
      // carry size; the chip falls back to showing just the basename.
      dropDiagnostic = null;
      for (const p of paths) attachFileAtCursor(p);
      return;
    }
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      // Fallback: the browser stripped path metadata (Chrome/Wayland
      // tab-sandboxing) but the File objects are still readable. Stream
      // the bytes through `/api/uploads` and inject the server path.
      // Kick off async without awaiting — the DragEvent handler returns
      // synchronously and the upload progresses in the background.
      void uploadDroppedFiles(files);
      return;
    }
    // Nothing to work with — neither URIs nor File objects. Keep the
    // diagnostic banner so the failure mode stays visible; it's the
    // instrumentation that'll tell us about future compositor/browser
    // regressions.
    const typesInfo = `types=[${(e.dataTransfer.types ?? []).join(', ')}]`;
    dropDiagnostic =
      'Drop received, but the browser exposed neither a path nor file bytes. ' +
      `${typesInfo} ` +
      (formats.length ? formats.join(' | ') : '(no text formats exposed)') +
      ' — use the Attach-file button instead.';
  }

  /** Paste handler — Chrome-on-Wayland compatible alternative to the
   * broken drop-dispatch path. Clipboard uses a different Wayland
   * protocol than DnD and works reliably when drag-and-drop silently
   * fails on Hyprland/Chromium. Workflow: copy a file in the file
   * manager (Dolphin, Nautilus) → focus the textarea → Ctrl+V. The
   * clipboard exposes File objects with readable bytes, so we feed
   * them straight into the same `/api/uploads` pipeline the drop path
   * uses.
   *
   * Only preventDefault when files are present — a paste of plain text
   * (the common case) must still land in the textarea normally. */
  function onPaste(e: ClipboardEvent): void {
    const files = e.clipboardData?.files;
    if (!files || files.length === 0) return;
    e.preventDefault();
    void uploadDroppedFiles(files);
  }

  /** Browser-native file picker — a second affordance that doesn't
   * depend on the server's zenity/kdialog bridge OR the compositor's
   * drag-and-drop bridge. Works identically in every Chromium and
   * Firefox build, Wayland or X11. Complements the zenity button,
   * which is still useful because it honors `working_dir`. */
  let fileInputEl: HTMLInputElement | null = $state(null);

  function onBrowseClick(): void {
    fileInputEl?.click();
  }

  async function onFileInputChange(e: Event): Promise<void> {
    const target = e.currentTarget as HTMLInputElement;
    if (!target.files || target.files.length === 0) return;
    await uploadDroppedFiles(target.files);
    // Reset so picking the SAME file twice in a row re-fires `change`.
    // Without this the input's value is sticky and a repeat selection
    // is silently ignored.
    target.value = '';
  }

  // Upload button → native picker via `POST /api/fs/pick` (zenity on
  // GTK, kdialog on KDE). Bearings runs on the user's own machine, so
  // popping a dialog on their desktop is fair game and gives us the
  // absolute path directly — no sandboxing, no upload, no custom modal
  // to maintain. Multi-select: zenity supports it; paths come back
  // NUL-delimited and we inject them in order at the cursor.
  let picking = $state(false);

  async function onPickFile() {
    if (picking) return;
    picking = true;
    try {
      const start = sessions.selected?.working_dir ?? null;
      const result = await fsApi.pickFile({
        start,
        multiple: true,
        title: 'Attach a file to the prompt'
      });
      if (result.cancelled) return;
      for (const p of result.paths) attachFileAtCursor(p);
    } catch (e) {
      conversation.error = e instanceof Error ? e.message : String(e);
    } finally {
      picking = false;
    }
  }

  // Document-level Esc clears an active search highlight. Scoped to
  // this component so it only binds while a session is open; the
  // textarea keeps its own Esc handling via browser defaults.
  $effect(() => {
    function onDocKey(e: KeyboardEvent) {
      if (e.key !== 'Escape') return;
      if (!conversation.highlightQuery) return;
      // Don't hijack Esc while the user is typing a prompt.
      const active = document.activeElement;
      const inTextarea = active?.tagName === 'TEXTAREA' || active?.tagName === 'INPUT';
      if (inTextarea) return;
      conversation.highlightQuery = '';
    }
    document.addEventListener('keydown', onDocKey);
    return () => document.removeEventListener('keydown', onDocKey);
  });

</script>

<SessionEdit
  bind:open={editingSession}
  sessionId={sessions.selectedId}
/>

<SessionPickerModal
  open={pickerOpen}
  excludeIds={sessions.selectedId ? [sessions.selectedId] : []}
  title={pickerTitle(pickerOp, pickerBulkIds.length)}
  confirmLabel={pickerConfirmLabel(pickerOp)}
  defaultCreating={pickerOp === 'bulk-split'}
  allowCreate={pickerOp !== 'merge'}
  onPickExisting={onPickerPickExisting}
  onPickNew={onPickerPickNew}
  onCancel={closePicker}
/>

{#if undo}
  <ReorgUndoToast
    message={undo.message}
    warnings={undo.warnings}
    onUndo={undo.run}
    onDismiss={onUndoDismiss}
  />
{/if}

{#if bulkMode}
  <BulkActionBar
    count={selectedIds.size}
    onMove={onBulkMove}
    onSplit={onBulkSplit}
    onCancel={toggleBulkMode}
  />
{/if}

{#if conversation.pendingApproval}
  {#if conversation.pendingApproval.tool_name === 'AskUserQuestion'}
    <!-- AskUserQuestion is a Claude Code built-in whose answers are
         collected by the permission component and handed to the SDK
         via `PermissionResultAllow.updated_input`. The generic
         ApprovalModal's approve/deny gate can't express that, so we
         route it to a dedicated picker that renders options and
         builds the `answers` payload. -->
    <AskUserQuestionModal
      request={conversation.pendingApproval}
      connected={agent.state === 'open'}
      onRespond={(id, decision, reason, updatedInput) =>
        agent.respondToApproval(id, decision, reason, updatedInput)}
    />
  {:else}
    <ApprovalModal
      request={conversation.pendingApproval}
      connected={agent.state === 'open'}
      onRespond={(id, decision, reason) => agent.respondToApproval(id, decision, reason)}
    />
  {/if}
{/if}

<!-- svelte-ignore a11y_no_static_element_interactions -->
<section
  bind:this={sectionEl}
  class="relative bg-slate-900 overflow-hidden flex flex-col min-w-0
    {dragging ? 'ring-2 ring-emerald-500/60 ring-inset' : ''}"
  ondragenter={onDragEnter}
  ondragover={onDragOver}
  ondragleave={onDragLeave}
  ondrop={onDrop}
>
  {#if dragging}
    <div
      class="pointer-events-none absolute inset-2 rounded border-2 border-dashed
        border-emerald-500/70 bg-slate-950/60 flex items-center justify-center z-20"
      data-testid="conversation-drop-hint"
    >
      <p class="text-sm text-emerald-300">Drop to attach file to the prompt</p>
    </div>
  {/if}
  {#if uploading}
    <div
      class="pointer-events-none absolute inset-2 rounded border-2 border-dashed
        border-sky-500/60 bg-slate-950/70 flex items-center justify-center z-20"
      data-testid="conversation-upload-hint"
    >
      <div class="flex flex-col items-center gap-3 text-sky-300">
        <BearingsMark size={56} spin label="Uploading file" />
        <p class="text-sm">Uploading dropped file…</p>
      </div>
    </div>
  {/if}
  {#if conversation.loadingInitial}
    <!-- Full-pane overlay spinner. Painted in the same frame as the
         click (agent.connect yields a paint frame right after flipping
         loadingInitial), so it's visible BEFORE the REST fetch +
         MessageTurn re-render pin the main thread. Without this the
         user sees the whole app freeze on click and only after the
         hang does the new session appear. pointer-events-none so it
         doesn't block keyboard focus on the textarea below; z-30 puts
         it above drag + upload hints but below the approval modal. -->
    <div
      class="pointer-events-none absolute inset-0 flex items-center justify-center
        bg-slate-950/60 backdrop-blur-sm z-30"
      data-testid="conversation-initial-loading"
    >
      <div class="flex flex-col items-center gap-3 text-sky-300">
        <BearingsMark size={80} spin label="Loading session" />
        <p class="text-xs uppercase tracking-wider text-slate-400">Loading session…</p>
      </div>
    </div>
  {/if}
  <header class="border-b border-slate-800 px-4 py-3 flex items-baseline justify-between">
    <div class="min-w-0">
      {#if pairedCrumb}
        <nav
          class="mb-1 flex items-center gap-1 text-xs text-slate-500"
          aria-label="Paired checklist item"
        >
          <button
            type="button"
            class="inline-flex items-center gap-1 hover:text-sky-400"
            onclick={() => sessions.select(pairedCrumb!.parentId)}
            title="Back to checklist"
          >
            <span aria-hidden="true">📋</span>
            <span class="max-w-[16ch] truncate">{pairedCrumb.parentTitle}</span>
          </button>
          <span aria-hidden="true">›</span>
          <span class="max-w-[24ch] truncate text-slate-300">{pairedCrumb.itemLabel}</span>
        </nav>
      {/if}
      <h1 class="text-lg font-medium flex items-center gap-2">
        <!-- Permanent brand mark. Spins reactively while the agent is
             connecting, a response is streaming, or the per-session
             REST bundle is still in flight after a click. The logo IS
             the work indicator, so loading states read as the app
             coming alive rather than as bolted-on spinners.
             `loadingInitial` is what catches the "session clicked, big
             transcript still loading" case — WS replay usually paints
             messages before REST finishes, so the centered-pane
             spinner below rarely gets a chance to render; this header
             mark keeps a steady signal while tool calls / audits /
             tags / tokens are still streaming in behind the scenes. -->
        <BearingsMark
          size={20}
          spin={agent.state === 'connecting' ||
            conversation.streamingActive ||
            conversation.loadingInitial}
        />
        {sessions.selected?.title ?? 'Bearings'}
        {#if sessions.selected}
          <button
            type="button"
            class="text-xs text-slate-500 hover:text-slate-300"
            aria-label="Edit session"
            title="Edit title / budget"
            onclick={() => (editingSession = true)}
          >
            ✎
          </button>
          <button
            type="button"
            class="text-xs text-slate-500 hover:text-slate-300 disabled:opacity-50"
            aria-label="Export session"
            title="Download as JSON"
            onclick={onExport}
            disabled={exporting}
          >
            ⇣
          </button>
          <button
            type="button"
            class="text-xs text-slate-500 hover:text-slate-300 disabled:opacity-50"
            aria-label="Copy session to clipboard"
            title={copiedSession ? 'Copied' : 'Copy session as markdown'}
            onclick={onCopySession}
            disabled={copiedSession}
          >
            {copiedSession ? '✓' : '⎘'}
          </button>
          <button
            type="button"
            class="text-xs hover:text-slate-300 {bulkMode ? 'text-emerald-400' : 'text-slate-500'}"
            aria-label="Toggle bulk select mode"
            aria-pressed={bulkMode}
            title={bulkMode ? 'Exit bulk select' : 'Bulk select messages'}
            onclick={toggleBulkMode}
            data-testid="bulk-toggle"
          >
            {bulkMode ? '☑' : '☐'}
          </button>
          <button
            type="button"
            class="text-xs text-slate-500 hover:text-slate-300"
            aria-label="Merge this session into another"
            title="Merge this session into another"
            onclick={openMerge}
            data-testid="merge-session"
          >
            ⇲
          </button>
          <button
            type="button"
            class="text-xs hover:text-slate-300 {sessions.selected.closed_at
              ? 'text-emerald-400'
              : 'text-slate-500'}"
            aria-label={sessions.selected.closed_at ? 'Reopen session' : 'Close session'}
            aria-pressed={!!sessions.selected.closed_at}
            title={sessions.selected.closed_at ? 'Reopen session' : 'Close session'}
            onclick={onToggleClosed}
            data-testid="close-session"
          >
            ✓
          </button>
        {/if}
      </h1>
      <p class="text-xs font-mono truncate text-slate-500">
        {#if sessions.selected}
          {sessions.selected.model} · {sessions.selected.working_dir} ·
          {#if billing.showTokens}
            <!-- Subscription mode: flat-rate billing makes the dollar
                 figure meaningless, so swap in the token aggregate
                 from /sessions/{id}/tokens. No budget cap rendered
                 because `max_budget_usd` is dollar-denominated; a
                 future slice can add a token-denominated cap. -->
            <TokenMeter totals={tokenTotals} />
          {:else}
            <span class={pressureClass(conversation.totalCost, sessions.selected.max_budget_usd)}>
              spent ${conversation.totalCost.toFixed(4)}{sessions.selected.max_budget_usd != null
                ? ` / $${sessions.selected.max_budget_usd.toFixed(2)}`
                : ''}
            </span>
          {/if}
          {#if sessions.selected.message_count > 0}
            · {sessions.selected.message_count} msg{sessions.selected.message_count === 1
              ? ''
              : 's'}
          {/if}
          {#if conversation.contextUsage}
            · <ContextMeter context={conversation.contextUsage} />
          {/if}
        {:else}
          select or create a session to start
        {/if}
      </p>
      {#if sessions.selected && sessionTags.length > 0}
        <ul class="flex flex-wrap gap-1 mt-1.5" aria-label="Session tags">
          {#each sessionTags as tag (tag.id)}
            <li
              class="inline-flex items-center gap-1 rounded bg-slate-800 px-1.5 py-0.5
                text-[10px] font-mono text-slate-300"
              title={tag.default_working_dir || tag.default_model
                ? `defaults: ${tag.default_working_dir ?? ''} ${tag.default_model ?? ''}`.trim()
                : tag.name}
            >
              {#if tag.pinned}
                <span class="text-amber-400" aria-hidden="true">★</span>
              {/if}
              <span>{tag.name}</span>
            </li>
          {/each}
        </ul>
      {/if}
      {#if sessions.selected?.description}
        <p
          bind:this={descriptionEl}
          class="text-xs text-slate-400 mt-1 whitespace-pre-wrap break-words
            {descriptionExpanded ? '' : 'line-clamp-3'}"
          data-testid="session-description"
          data-expanded={descriptionExpanded ? 'true' : 'false'}
        >
          {sessions.selected.description}
        </p>
        {#if descriptionOverflows}
          <button
            type="button"
            class="text-[10px] uppercase tracking-wider text-slate-500
              hover:text-slate-300 mt-0.5"
            onclick={() => (descriptionExpanded = !descriptionExpanded)}
            data-testid="description-toggle"
            aria-expanded={descriptionExpanded}
          >
            {descriptionExpanded ? '⌃ show less' : '⌄ show more'}
          </button>
        {/if}
      {/if}
    </div>
    <div class="flex items-center gap-2">
      <PermissionModeSelector />
      {#if conversation.streamingActive}
        {#if agent.stopPendingStartedAt === null}
          <button
            type="button"
            class="text-[10px] uppercase tracking-wider px-2 py-1 rounded
              bg-rose-900 text-rose-200 hover:bg-rose-800"
            onclick={() => agent.stop()}
            title="Stop the in-flight stream"
          >
            Stop
          </button>
        {:else}
          <StopUndoInline />
        {/if}
      {/if}
      <span
        class="text-[10px] uppercase tracking-wider px-2 py-1 rounded
          {agent.state === 'open'
            ? 'bg-emerald-900 text-emerald-300'
            : agent.state === 'connecting'
              ? 'bg-amber-900 text-amber-300'
              : 'bg-slate-800 text-slate-400'}"
      >
        {connectionLabel(agent.state, agent.reconnectDelayMs, agent.lastCloseCode)}
      </span>
    </div>
  </header>

  {#if conversation.highlightQuery}
    <div
      class="px-4 py-1.5 bg-amber-950/40 border-b border-amber-900/40
        flex items-center justify-between text-xs"
    >
      <span class="text-amber-200">
        Matching <span class="font-mono">«{conversation.highlightQuery}»</span> · Esc to clear
      </span>
      <button
        type="button"
        class="text-amber-400 hover:text-amber-200"
        aria-label="Clear highlight"
        onclick={() => (conversation.highlightQuery = '')}
      >
        ✕
      </button>
    </div>
  {/if}

  {#if sessions.selectedId}
    <CheckpointGutter sessionId={sessions.selectedId} />
  {/if}

  {#if conversation.todos !== null}
    <!-- Sits between the session header (or CheckpointGutter, when
         checkpoints exist) and the scrollable message area. Previously
         nested inside the scroll container with `sticky top-0` and
         negative margins to cancel parent padding — the padding gap
         above the card was too stubborn, and since the widget was
         always pinned to the top anyway, hoisting it out is simpler
         and hugs the element above it cleanly. -->
    <LiveTodos todos={conversation.todos} />
  {/if}

  <div
    bind:this={scrollContainer}
    class="relative flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4"
  >
    {#if conversation.hasMore}
      <p
        class="text-[10px] text-slate-600 text-center inline-flex items-center
          justify-center gap-1 self-center"
      >
        {#if conversation.loadingOlder}
          <BearingsMark size={10} spin label="Loading older messages" />
          Loading older…
        {:else}
          Scroll up to load older messages
        {/if}
      </p>
    {/if}
    {#if !sessions.selectedId}
      <p class="text-slate-500 text-sm">No session selected.</p>
    {:else if conversation.messages.length === 0 && !conversation.streamingActive && audits.length === 0 && !conversation.loadingInitial}
      <p class="text-slate-500 text-sm">
        No messages yet. Send a prompt to start the conversation.
      </p>
    {:else}
      {#snippet timelineEntry(item: (typeof timeline)[number])}
        {#if item.kind === 'turn'}
          <MessageTurn
            user={item.turn.user}
            assistant={item.turn.assistant}
            thinking={item.turn.thinking}
            toolCalls={item.turn.toolCalls}
            streamingContent={item.turn.streamingContent}
            streamingThinking={item.turn.streamingThinking}
            isStreaming={item.turn.isStreaming}
            highlightQuery={conversation.highlightQuery}
            {copiedMsgId}
            {onCopyMessage}
            {onMoreInfo}
            isLatestAssistant={item.turn.key === latestAssistantTurnKey}
            {bulkMode}
            {selectedIds}
            onToggleSelect={onBulkToggleSelect}
          />
        {:else}
          <ReorgAuditDivider audit={item.audit} onJumpTo={onJumpToAuditTarget} />
        {/if}
      {/snippet}

      {#each timeline as item, idx (item.key)}
        {#if useVirtualization}
          {@const isStreamingTail = item.kind === 'turn' && item.turn.isStreaming}
          {@const inWarmTail = idx >= timeline.length - ALWAYS_WARM_TAIL}
          <VirtualItem
            scrollRoot={scrollContainer}
            forceVisible={isStreamingTail || inWarmTail}
          >
            {@render timelineEntry(item)}
          </VirtualItem>
        {:else}
          {@render timelineEntry(item)}
        {/if}
      {/each}

      {#if conversation.error}
        <article class="rounded border border-rose-900/50 px-3 py-2 bg-rose-950/30">
          <header class="text-[10px] uppercase tracking-wider text-rose-400 mb-1">
            error
          </header>
          <pre class="text-xs text-rose-300 whitespace-pre-wrap">{conversation.error}</pre>
        </article>
      {/if}
    {/if}
  </div>

  {#if dropDiagnostic}
    <div
      class="border-t border-amber-900/50 bg-amber-950/40 px-4 py-2 flex items-start gap-2"
      data-testid="drop-diagnostic"
    >
      <pre class="text-[11px] text-amber-200 whitespace-pre-wrap flex-1 font-mono">{dropDiagnostic}</pre>
      <button
        type="button"
        class="text-amber-400 hover:text-amber-200 text-xs"
        aria-label="Dismiss drop diagnostic"
        onclick={() => (dropDiagnostic = null)}
      >
        ✕
      </button>
    </div>
  {/if}

  <form
    class="relative border-t border-slate-800 px-4 py-3 flex flex-col gap-2"
    onsubmit={(e) => {
      e.preventDefault();
      onSend();
    }}
  >
    <CommandMenu
      bind:this={commandMenu}
      entries={commandEntries}
      query={commandQuery}
      open={commandMenuOpen}
      onSelect={onSelectCommand}
      onClose={onCloseCommandMenu}
    />
    <div class="flex gap-2 items-end">
      <textarea
        class="flex-1 rounded bg-slate-950 border border-slate-800 px-3 py-2 text-sm
          resize-none focus:outline-none focus:border-slate-600 disabled:opacity-50"
        rows="1"
        placeholder={sessions.selectedId
          ? 'Send a prompt (Enter · Shift+Enter for newline · / for commands · Ctrl+V to paste files)'
          : 'Select a session first'}
        bind:value={promptText}
        bind:this={textareaEl}
        onkeydown={onKeydown}
        oninput={onInput}
        onpaste={onPaste}
        disabled={!sessions.selectedId || agent.state !== 'open'}
      ></textarea>
      <button
        type="submit"
        class="rounded bg-emerald-600 hover:bg-emerald-500 px-3 py-2 text-sm
          disabled:opacity-50 disabled:cursor-not-allowed"
        disabled={!sessions.selectedId || agent.state !== 'open' || !promptText.trim()}
      >
        Send
      </button>
    </div>
    {#if activeComposerAttachments.length > 0}
      <div class="flex flex-wrap gap-1.5" data-testid="composer-attachments">
        {#each activeComposerAttachments as att (att.n)}
          <span
            class="inline-flex items-center gap-1.5 rounded border border-slate-700
              bg-slate-900 px-2 py-0.5 text-[11px] text-slate-300"
            title={`${att.path}${att.size_bytes ? ' · ' + formatBytes(att.size_bytes) : ''}`}
          >
            <span class="text-slate-500">[File {att.n}]</span>
            <span class="truncate max-w-[220px]">{att.filename}</span>
            {#if att.size_bytes}
              <span class="text-slate-500">·</span>
              <span class="text-slate-500">{formatBytes(att.size_bytes)}</span>
            {/if}
            <button
              type="button"
              class="ml-0.5 text-slate-500 hover:text-slate-200"
              aria-label={`Remove [File ${att.n}]`}
              onclick={() => removeAttachment(att.n)}
            >
              ✕
            </button>
          </span>
        {/each}
      </div>
    {/if}
    <div class="flex items-center gap-2">
      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded border border-slate-800
          bg-slate-900 px-2.5 py-1 text-xs text-slate-300 hover:border-slate-600
          hover:text-slate-100 disabled:opacity-50 disabled:cursor-not-allowed"
        onclick={onPickFile}
        disabled={!sessions.selectedId || picking}
        title="Attach a file path via native dialog (honors session working dir)"
        data-testid="attach-file"
      >
        <span aria-hidden="true">📎</span>
        <span>{picking ? 'Picking…' : 'Attach file'}</span>
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded border border-slate-800
          bg-slate-900 px-2.5 py-1 text-xs text-slate-300 hover:border-slate-600
          hover:text-slate-100 disabled:opacity-50 disabled:cursor-not-allowed"
        onclick={onBrowseClick}
        disabled={!sessions.selectedId || uploading}
        title="Browse via the browser's file picker (no compositor deps)"
        data-testid="browse-file"
      >
        <span aria-hidden="true">📁</span>
        <span>{uploading ? 'Uploading…' : 'Browse'}</span>
      </button>
      <input
        type="file"
        multiple
        bind:this={fileInputEl}
        onchange={onFileInputChange}
        class="hidden"
        data-testid="file-input"
      />
      <span class="text-[10px] text-slate-500">
        or drag · Ctrl+V to paste files
      </span>
    </div>
  </form>
</section>

<style>
  :global(mark.search-mark) {
    background-color: rgb(234 179 8 / 0.35);
    color: rgb(253 224 71);
    border-radius: 0.125rem;
    padding: 0 0.125rem;
  }
</style>
