<script lang="ts">
  import { billing } from '$lib/stores/billing.svelte';
  import { conversation } from '$lib/stores/conversation.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { agent } from '$lib/agent.svelte';
  import * as api from '$lib/api';
  import ApprovalModal from '$lib/components/ApprovalModal.svelte';
  import BulkActionBar from '$lib/components/BulkActionBar.svelte';
  import CommandMenu from '$lib/components/CommandMenu.svelte';
  import MessageTurn from '$lib/components/MessageTurn.svelte';
  import PermissionModeSelector from '$lib/components/PermissionModeSelector.svelte';
  import ReorgAuditDivider from '$lib/components/ReorgAuditDivider.svelte';
  import ReorgUndoToast from '$lib/components/ReorgUndoToast.svelte';
  import SessionEdit from '$lib/components/SessionEdit.svelte';
  import SessionPickerModal from '$lib/components/SessionPickerModal.svelte';
  import ContextMeter from '$lib/components/ContextMeter.svelte';
  import TokenMeter from '$lib/components/TokenMeter.svelte';
  import { buildTurns } from '$lib/turns';
  import {
    connectionLabel,
    copyText,
    messagesAsMarkdown,
    pressureClass
  } from '$lib/utils/conversation-ui';

  const turns = $derived(
    buildTurns({
      messages: conversation.messages,
      toolCalls: conversation.toolCalls,
      streamingActive: conversation.streamingActive,
      streamingMessageId: conversation.streamingMessageId,
      streamingThinking: conversation.streamingThinking,
      streamingText: conversation.streamingText
    })
  );

  // Slice 5: merge turns + reorg audit dividers into one chronological
  // timeline so the dividers land in the right spot instead of always
  // being tacked on at the end. Sort stably by ISO timestamp — turns
  // without a message (streaming placeholder) sink with empty string.
  type TimelineItem =
    | { kind: 'turn'; key: string; when: string; turn: (typeof turns)[number] }
    | { kind: 'audit'; key: string; when: string; audit: api.ReorgAudit };

  const timeline = $derived.by((): TimelineItem[] => {
    const items: TimelineItem[] = [];
    for (const t of turns) {
      const when = t.user?.created_at ?? t.assistant?.created_at ?? '';
      items.push({ kind: 'turn', key: `turn:${t.key}`, when, turn: t });
    }
    for (const a of audits) {
      items.push({ kind: 'audit', key: `audit:${a.id}`, when: a.created_at, audit: a });
    }
    items.sort((a, b) => {
      if (a.when === b.when) return 0;
      // Empty (streaming turn, no message yet) always lands last.
      if (a.when === '') return 1;
      if (b.when === '') return -1;
      return a.when < b.when ? -1 : 1;
    });
    return items;
  });

  function onJumpToAuditTarget(targetId: string) {
    sessions.select(targetId);
  }

  let promptText = $state('');
  let scrollContainer: HTMLDivElement | undefined = $state();
  let editingSession = $state(false);
  let exporting = $state(false);
  let copiedMsgId = $state<string | null>(null);
  let copiedSession = $state(false);
  let textareaEl: HTMLTextAreaElement | undefined = $state();

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
  // timeline stays truthful without waiting for a reload.
  let audits = $state<api.ReorgAudit[]>([]);

  async function refreshAudits(): Promise<void> {
    const sid = sessions.selectedId;
    if (!sid) {
      audits = [];
      return;
    }
    try {
      const rows = await api.listReorgAudits(sid);
      if (sessions.selectedId === sid) audits = rows;
    } catch {
      // Non-fatal — the conversation still renders without dividers.
    }
  }

  $effect(() => {
    const sid = sessions.selected?.id ?? null;
    if (!sid) {
      audits = [];
      return;
    }
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
    if (!agent.send(text)) return;
    promptText = '';
  }

  function onKeydown(e: KeyboardEvent) {
    // The command menu claims arrow/Enter/Tab/Escape while open so the
    // user can navigate without leaving the textarea. It returns false
    // for other keys so normal typing still flows through.
    if (commandMenu?.handleKey(e)) return;
    // Enter sends; Shift+Enter falls through so the textarea inserts
    // a newline. Skip while the user is mid-IME composition.
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      onSend();
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
  <ApprovalModal
    request={conversation.pendingApproval}
    connected={agent.state === 'open'}
    onRespond={(id, decision, reason) => agent.respondToApproval(id, decision, reason)}
  />
{/if}

<section class="bg-slate-900 overflow-hidden flex flex-col min-w-0">
  <header class="border-b border-slate-800 px-4 py-3 flex items-baseline justify-between">
    <div class="min-w-0">
      <h1 class="text-lg font-medium flex items-center gap-2">
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
        <button
          type="button"
          class="text-[10px] uppercase tracking-wider px-2 py-1 rounded
            bg-rose-900 text-rose-200 hover:bg-rose-800"
          onclick={() => agent.stop()}
          title="Stop the in-flight stream"
        >
          Stop
        </button>
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

  <div bind:this={scrollContainer} class="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4">
    {#if conversation.hasMore}
      <p class="text-[10px] text-slate-600 text-center">
        {conversation.loadingOlder ? 'Loading older…' : 'Scroll up to load older messages'}
      </p>
    {/if}
    {#if !sessions.selectedId}
      <p class="text-slate-500 text-sm">No session selected.</p>
    {:else if conversation.messages.length === 0 && !conversation.streamingActive && audits.length === 0}
      <p class="text-slate-500 text-sm">
        No messages yet. Send a prompt to start the conversation.
      </p>
    {:else}
      {#each timeline as item (item.key)}
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
            onMoveMessage={openMoveFor}
            onSplitAfter={openSplitFor}
            {bulkMode}
            {selectedIds}
            onToggleSelect={onBulkToggleSelect}
          />
        {:else}
          <ReorgAuditDivider audit={item.audit} onJumpTo={onJumpToAuditTarget} />
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

  <form
    class="relative border-t border-slate-800 px-4 py-3 flex gap-2 items-end"
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
    <textarea
      class="flex-1 rounded bg-slate-950 border border-slate-800 px-3 py-2 text-sm
        resize-none focus:outline-none focus:border-slate-600 disabled:opacity-50"
      rows="2"
      placeholder={sessions.selectedId
        ? 'Send a prompt (Enter · Shift+Enter for newline · / for commands)'
        : 'Select a session first'}
      bind:value={promptText}
      bind:this={textareaEl}
      onkeydown={onKeydown}
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
