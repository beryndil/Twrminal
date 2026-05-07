<script lang="ts">
  /**
   * Conversation header band (gap-cycle-01-005).
   *
   * Renders the full header surface for the active session per
   * ``docs/behavior/chat.md`` §"When the user opens an existing chat":
   *
   * - **Title** — the session title (truncated with ellipsis on overflow).
   * - **Severity shield** — coloured chip for the attached severity tag;
   *   absent when no severity tag is attached.
   * - **Tag chips** — all non-severity tags attached to the session.
   * - **Paired-checklist breadcrumb** — ``<parent> › <item>`` chip shown
   *   when the session was spawned from a checklist item
   *   (``docs/behavior/paired-chats.md`` §"What 'paired' means
   *   observably"). Clicking the parent segment navigates to the parent
   *   checklist; clicking the item segment navigates there too (same
   *   destination, future scroll-anchor extension possible via URL hash).
   *   When the parent has been deleted the chip renders
   *   ``(checklist deleted)`` and the click handlers are inert per the
   *   behavior doc §"Behavior under one-side-closed".
   * - **Executor model dropdown** — :component:`ModelSelector` (opens
   *   the spec §7 confirmation dialog on model change).
   * - **Permission-mode selector** — :component:`PermissionModeSelector`.
   * - **Total-cost indicator** — ``total_cost_usd`` formatted as ``$X.XX``;
   *   hidden when cost is exactly 0.00 (session not yet billed).
   * - **Context/token meter** — :component:`ContextMeter`; only visible
   *   after the first ``context_usage`` frame arrives for the session.
   * - **Quota bars** — :component:`QuotaBars` (overall + Sonnet, per
   *   spec §10). Snapshot fetched from ``GET /api/quota/current`` on
   *   mount and re-fetched whenever the active session changes.
   *
   * The component renders nothing when ``sessionId`` is null (no active
   * session), so ``Conversation.svelte`` can unconditionally include it.
   *
   * Factored out of ``Conversation.svelte`` per
   * ``docs/architecture-v1.md`` §1.2 to keep that file under the
   * line-count cap.
   *
   * Behavior anchors:
   *   - ``docs/behavior/chat.md`` §"When the user opens an existing chat"
   *   - ``docs/behavior/paired-chats.md`` §"What 'paired' means observably"
   *   - spec §7 mid-session model switch (ModelSelector / ModelSwitchDialog)
   *   - spec §10 quota bars
   */
  import { goto } from "$app/navigation";

  import {
    CONVERSATION_HEADER_STRINGS,
    REORG_BUTTON_STRINGS,
    SESSION_KIND_CHAT,
    apiChecklistItemEndpoint,
  } from "../../config";
  import { getJson } from "../../api/client";
  import { getCurrentQuota } from "../../api/quota";
  import { TAG_CLASS_SEVERITY } from "../../api/tags";
  import { sessionsStore } from "../../stores/sessions.svelte";
  import { conversationStore } from "../../stores/conversation.svelte";
  import type { ChecklistItemOut } from "../../api/checklists";
  import type { QuotaBarsSnapshot } from "../new_session/QuotaBars.svelte";

  import { fetchBillingMode, type BillingMode } from "../../utils/appInfo";

  import ContextMeter from "./ContextMeter.svelte";
  import ModelSelector from "./ModelSelector.svelte";
  import PairedChatIndicator from "./PairedChatIndicator.svelte";
  import PermissionModeSelector from "./PermissionModeSelector.svelte";
  import QuotaBars from "../new_session/QuotaBars.svelte";
  import FeedbackButton from "../feedback/FeedbackButton.svelte";
  import TokenMeter from "../inspector/TokenMeter.svelte";
  import ReorgProposalEditor from "../reorg/ReorgProposalEditor.svelte";

  interface Props {
    sessionId: string | null;
  }

  const { sessionId }: Props = $props();

  /** Active session row driven by the sessions store. */
  const session = $derived(
    sessionId === null
      ? null
      : (sessionsStore.sessions.find((s) => s.id === sessionId) ?? null),
  );

  /** All tags attached to the active session (from the per-session tag cache). */
  const tags = $derived(
    sessionId !== null ? (sessionsStore.tagsBySessionId[sessionId] ?? []) : [],
  );

  /**
   * The attached severity tag (at most one — cardinality enforced at session
   * create). Drives the severity shield chip colour.
   */
  const severityTag = $derived(tags.find((t) => t.class_ === TAG_CLASS_SEVERITY) ?? null);

  /** All non-severity tags — rendered as plain label chips next to the shield. */
  const nonSeverityTags = $derived(tags.filter((t) => t.class_ !== TAG_CLASS_SEVERITY));

  // ---- Paired-chat breadcrumb ------------------------------------------------

  /**
   * Checklist item detail fetched lazily when the session has a
   * ``checklist_item_id``. Provides the item's ``label`` and
   * ``checklist_id`` (parent session id) for breadcrumb text and
   * click-navigation.
   */
  let checklistItem = $state<ChecklistItemOut | null>(null);

  $effect(() => {
    const itemId = session?.checklist_item_id ?? null;
    if (itemId === null) {
      checklistItem = null;
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const item = await getJson<ChecklistItemOut>(apiChecklistItemEndpoint(itemId));
        if (!cancelled) checklistItem = item;
      } catch {
        // Fetch failed — leave null; breadcrumb uses session title as
        // item-label fallback (set below via breadcrumbItemLabel).
        if (!cancelled) checklistItem = null;
      }
    })();
    return () => {
      cancelled = true;
    };
  });

  /**
   * ``true`` when the session is still paired (``checklist_item_id`` set)
   * but its parent checklist has been deleted
   * (``paired_parent_title`` is null).
   * Per paired-chats.md §"Behavior under one-side-closed" → "Parent
   * checklist deleted" row: the breadcrumb renders ``(checklist deleted)``.
   */
  const parentDeleted = $derived(
    (session?.checklist_item_id ?? null) !== null &&
      (session?.paired_parent_title === null || session?.paired_parent_title === undefined),
  );

  /**
   * Title segment of the breadcrumb chip. Null when the parent has been
   * deleted — both inputs being null triggers the "deleted" state inside
   * :component:`PairedChatIndicator`.
   */
  const breadcrumbParentTitle = $derived(parentDeleted ? null : (session?.paired_parent_title ?? null));

  /**
   * Item-label segment of the breadcrumb chip.
   *
   * Priority: fetched ``ChecklistItemOut.label`` → session title
   * (default chat title equals the item label at spawn time) → null.
   * Null when the parent is deleted (both null ⇒ "deleted" chip state).
   */
  const breadcrumbItemLabel = $derived(
    parentDeleted ? null : (checklistItem?.label ?? session?.title ?? null),
  );

  /**
   * Navigate to the parent checklist session. Only wired when
   * ``checklistItem`` has been fetched (so we have the ``checklist_id``).
   */
  function handleSelectParent(): void {
    if (checklistItem !== null) {
      void goto(`/sessions/${encodeURIComponent(checklistItem.checklist_id)}`);
    }
  }

  /**
   * Navigate to the parent checklist session with an anchor that the
   * checklist pane can use to scroll to the specific item.
   */
  function handleScrollToItem(): void {
    if (checklistItem !== null) {
      void goto(
        `/sessions/${encodeURIComponent(checklistItem.checklist_id)}#item-${String(checklistItem.id)}`,
      );
    }
  }

  // ---- Billing mode ----------------------------------------------------------

  /**
   * Resolved billing mode fetched once on mount from
   * ``GET /api/diag/server`` via :func:`fetchBillingMode`. ``null``
   * while the fetch is in flight; defaults to ``"payg"`` on error.
   *
   * Drives the cost-vs-token-meter swap: subscription mode renders
   * :component:`TokenMeter`; PAYG mode renders the dollar figure.
   */
  let billingMode = $state<BillingMode | null>(null);

  $effect(() => {
    let cancelled = false;
    void fetchBillingMode().then((m) => {
      if (!cancelled) billingMode = m;
    });
    return () => {
      cancelled = true;
    };
  });

  // ---- Reorg panel -----------------------------------------------------------

  /**
   * ``true`` when the ReorgProposalEditor panel is open.  The button in
   * the controls row toggles this.  Reset to ``false`` on panel close.
   */
  let reorgPanelOpen = $state(false);

  /**
   * Whether the active session is a plain chat — only chat-kind sessions
   * have message content that can be split.  The button is disabled for
   * all other kinds (e.g. checklist).
   */
  const isChat = $derived(session !== null && session.kind === SESSION_KIND_CHAT);

  // ---- Quota bars ------------------------------------------------------------

  /** Latest quota snapshot fetched from ``GET /api/quota/current``. */
  let quotaSnapshot = $state<QuotaBarsSnapshot | null>(null);

  $effect(() => {
    // Reactive on sessionId — re-fetch when the user switches sessions.
    void sessionId;
    if (sessionId === null) {
      quotaSnapshot = null;
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const q = await getCurrentQuota();
        if (!cancelled) {
          quotaSnapshot = {
            overallUsedPct: q.overall_used_pct,
            sonnetUsedPct: q.sonnet_used_pct,
            overallResetsAt: q.overall_resets_at,
            sonnetResetsAt: q.sonnet_resets_at,
          };
        }
      } catch {
        // Non-fatal — QuotaBars renders an "unavailable" state when
        // snapshot is null. 404 / 503 / 502 are all normal during
        // early setup (no poller configured yet).
        if (!cancelled) quotaSnapshot = null;
      }
    })();
    return () => {
      cancelled = true;
    };
  });
</script>

{#if session !== null}
  <header
    class="conversation-header flex flex-col border-b border-border"
    aria-label={CONVERSATION_HEADER_STRINGS.ariaLabel}
    data-testid="conversation-header"
  >
    <!-- Primary row: title, severity shield, tag chips, breadcrumb -->
    <div class="flex flex-wrap items-center gap-2 px-3 py-1.5">
      <!-- Session title -->
      <span
        class="max-w-xs truncate text-sm font-semibold text-fg-strong"
        data-testid="conversation-header-title"
        title={session.title}
      >
        {session.title}
      </span>

      <!-- Severity shield — coloured chip for the severity tag -->
      {#if severityTag !== null}
        <span
          class="rounded px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-white"
          aria-label={CONVERSATION_HEADER_STRINGS.severityShieldAriaLabel}
          data-testid="conversation-header-severity"
          style:background-color={severityTag.color ?? "rgb(var(--bearings-fg-muted))"}
        >
          {severityTag.name}
        </span>
      {/if}

      <!-- Non-severity tag chips -->
      {#if nonSeverityTags.length > 0}
        <span
          class="flex flex-wrap gap-1"
          aria-label={CONVERSATION_HEADER_STRINGS.tagChipsAriaLabel}
          data-testid="conversation-header-tags"
        >
          {#each nonSeverityTags as tag (tag.id)}
            <span
              class="rounded bg-surface-2 px-1.5 py-0.5 text-xs text-fg-muted"
              data-testid="conversation-header-tag-chip"
              data-tag-id={tag.id}
            >
              {tag.name}
            </span>
          {/each}
        </span>
      {/if}

      <!-- Paired-checklist breadcrumb (only when this session has a paired item) -->
      {#if (session.checklist_item_id ?? null) !== null}
        <PairedChatIndicator
          parentTitle={breadcrumbParentTitle}
          itemLabel={breadcrumbItemLabel}
          onSelectParent={checklistItem !== null ? handleSelectParent : undefined}
          onScrollToItem={checklistItem !== null ? handleScrollToItem : undefined}
        />
      {/if}
    </div>

    <!-- Controls row: model dropdown, permission mode, cost, quota bars -->
    <div class="flex flex-wrap items-center gap-3 px-3 py-1">
      <ModelSelector {sessionId} />
      <PermissionModeSelector {sessionId} />

      <!-- Cost / token-meter swap: subscription mode shows TokenMeter
           (dollar figure is meaningless on a flat-rate plan); PAYG mode
           shows the dollar figure (hidden at exactly $0.00 — no turn yet). -->
      {#if billingMode === "subscription"}
        <TokenMeter
          inputTokens={conversationStore.sessionInputTokens}
          outputTokens={conversationStore.sessionOutputTokens}
          overallUsedPct={quotaSnapshot !== null ? quotaSnapshot.overallUsedPct : null}
        />
      {:else if session.total_cost_usd > 0}
        <span
          class="tabular-nums text-xs text-fg-muted"
          aria-label={CONVERSATION_HEADER_STRINGS.costAriaLabel}
          data-testid="conversation-header-cost"
        >
          {CONVERSATION_HEADER_STRINGS.costPrefix}{session.total_cost_usd.toFixed(2)}
        </span>
      {/if}

      <!-- Quota bars (overall + Sonnet; spec §10) -->
      <QuotaBars snapshot={quotaSnapshot} />

      <!-- Analyze-and-reorg button — scissors glyph; opens the
           ReorgProposalEditor panel (gap-cycle-11-003). Disabled for
           non-chat sessions (checklists have no message content to split). -->
      <button
        type="button"
        class="rounded p-0.5 text-fg-muted hover:bg-surface-2 hover:text-fg disabled:opacity-50"
        aria-label={REORG_BUTTON_STRINGS.ariaLabel}
        title={REORG_BUTTON_STRINGS.tooltip}
        data-testid="analyze-reorg-button"
        disabled={!isChat}
        onclick={() => {
          reorgPanelOpen = true;
        }}
      >
        <!--
          Scissors icon — Heroicons v1 outline ``scissors`` path,
          scaled to 14×14 within a 24×24 viewBox to match sibling
          header icon buttons (FeedbackButton, etc.).
        -->
        <svg
          viewBox="0 0 24 24"
          width="14"
          height="14"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <circle cx="6" cy="6" r="3" />
          <circle cx="6" cy="18" r="3" />
          <line x1="20" y1="4" x2="8.12" y2="15.88" />
          <line x1="14.47" y1="14.48" x2="20" y2="20" />
          <line x1="8.12" y1="8.12" x2="12" y2="12" />
        </svg>
      </button>

      <!-- Feedback button — megaphone glyph; opens GitHub issues/new in a
           new tab pre-filled with env + repro scaffold (gap-cycle-01-008). -->
      <FeedbackButton />
    </div>

    <!-- Reorg proposal editor panel — hidden until the user clicks the
         "Analyze and reorg" button.  Renders below the controls row as an
         inline card.  ReorgProposalEditor self-manages the analyzeReorg()
         call and the accept / dismiss interactions. -->
    {#if reorgPanelOpen && session !== null}
      <div class="px-3 pb-2">
        <ReorgProposalEditor
          sessionId={session.id}
          open={reorgPanelOpen}
          onclose={() => {
            reorgPanelOpen = false;
          }}
        />
      </div>
    {/if}

    <!-- Context / token meter — full-width strip; hidden until the first
         context_usage frame arrives (component self-hides via {#if usage !== null}). -->
    <ContextMeter />
  </header>
{/if}
