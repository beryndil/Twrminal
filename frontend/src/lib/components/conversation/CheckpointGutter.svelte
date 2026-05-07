<script lang="ts">
  /**
   * Vertical gutter rendering checkpoint chips alongside the conversation
   * pane (G6).
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/chat.md`` §"Slash commands in the composer" —
   *   ``/checkpoint`` creates a labelled gutter mark at the latest
   *   message; the chip rendered here is the result.
   * - ``docs/behavior/context-menus.md`` §"Checkpoint (gutter chip)" —
   *   right-click opens ``MENU_TARGET_CHECKPOINT`` with fork /
   *   copy-label / copy-id / delete handlers.
   * - Click a chip → scroll the anchor message into view (mirrors the
   *   message-turn ``jump_to_turn`` action).
   *
   * The gutter renders as an absolutely-positioned column inside the
   * conversation body so each chip can be vertically aligned to its
   * anchor message via a JS layout pass: we measure each
   * ``[data-turn-id="<message_id>"]`` element and set the chip's ``top``
   * to that element's offsetTop. The pass re-runs on:
   *
   * - mount,
   * - the checkpoint list changing (after a create / delete),
   * - the conversation body resizing (ResizeObserver — handles tool
   *   drawer expansion + new message arrivals).
   *
   * Component is presentational + lifecycle: receives the session id +
   * the body element to position against; fetches the checkpoint list
   * itself; handles right-click menu via the global context-menu store.
   */
  import { onMount, untrack } from "svelte";
  import {
    createCheckpoint,
    deleteCheckpoint,
    forkCheckpoint,
    listCheckpoints,
    type CheckpointOut,
  } from "../../api/checkpoints";
  import { contextMenu } from "../../actions/contextMenu";
  import {
    CHECKPOINT_GUTTER_STRINGS,
    MENU_ACTION_CHECKPOINT_COPY_ID,
    MENU_ACTION_CHECKPOINT_COPY_LABEL,
    MENU_ACTION_CHECKPOINT_DELETE,
    MENU_ACTION_CHECKPOINT_FORK,
    MENU_TARGET_CHECKPOINT,
    UNDO_TOAST_STRINGS,
  } from "../../config";
  import { goto } from "$app/navigation";
  import { undoStore } from "../../stores/undo.svelte";

  interface Props {
    /** Active session id; ``null`` clears the gutter. */
    sessionId: string | null;
    /** Body element each chip aligns its top against. */
    bodyEl: HTMLElement | null;
    /** Refresh tick — bumped by the parent after sending a /checkpoint slash. */
    refreshKey?: number;
  }

  const { sessionId, bodyEl, refreshKey = 0 }: Props = $props();

  let checkpoints = $state<CheckpointOut[]>([]);
  /** Pixel-position of each chip, keyed by checkpoint id. */
  let chipTops = $state<Record<string, number>>({});

  // Re-fetch whenever session or refresh tick changes.
  $effect(() => {
    const sid = sessionId;
    const _tick = refreshKey;
    void _tick; // tracked dep
    if (sid === null) {
      checkpoints = [];
      chipTops = {};
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const rows = await listCheckpoints(sid);
        if (cancelled) return;
        // Defensive copy + array guard — if the response shape is
        // unexpectedly non-array (e.g. an unmocked test endpoint
        // returned an object) treat it as empty rather than throwing
        // an iteration error inside the reactive effect.
        checkpoints = Array.isArray(rows) ? [...rows] : [];
      } catch (err) {
        if (cancelled) return;
        console.error("listCheckpoints failed:", err);
        checkpoints = [];
      }
    })();
    return () => {
      cancelled = true;
    };
  });

  /**
   * Reposition every chip so its ``top`` matches the offsetTop of the
   * anchor turn element. Skips checkpoints whose anchor is no longer
   * rendered (the chip disappears until the user scrolls / loads the
   * older page that contains it).
   */
  function recomputeTops(): void {
    if (bodyEl === null) {
      chipTops = {};
      return;
    }
    const next: Record<string, number> = {};
    for (const cp of checkpoints) {
      const el = bodyEl.querySelector(
        `[data-turn-id="${CSS.escape(cp.message_id)}"]`,
      ) as HTMLElement | null;
      if (el !== null) {
        next[cp.id] = el.offsetTop;
      }
    }
    chipTops = next;
  }

  // Recompute whenever the checkpoint list, body element, or session changes.
  $effect(() => {
    void checkpoints.length;
    void bodyEl;
    untrack(() => recomputeTops());
  });

  // Watch for body resizes (tool drawer expansion, new messages, etc.).
  // ``ResizeObserver`` is unavailable in jsdom (vitest) so we guard the
  // observer creation; the gutter still functions in tests, just
  // without the live re-position pass.
  let resizeObserver: ResizeObserver | null = null;
  $effect(() => {
    if (bodyEl === null) return;
    if (typeof ResizeObserver === "undefined") return;
    resizeObserver?.disconnect();
    resizeObserver = new ResizeObserver(() => {
      recomputeTops();
    });
    resizeObserver.observe(bodyEl);
    return () => {
      resizeObserver?.disconnect();
      resizeObserver = null;
    };
  });

  onMount(() => {
    recomputeTops();
  });

  /** Scroll the chip's anchor message into view. */
  function jumpToAnchor(messageId: string): void {
    if (bodyEl === null) return;
    const el = bodyEl.querySelector(
      `[data-turn-id="${CSS.escape(messageId)}"]`,
    ) as HTMLElement | null;
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function makeMenuHandlers(cp: CheckpointOut): Record<string, () => void> {
    return {
      [MENU_ACTION_CHECKPOINT_FORK]: () => {
        void (async () => {
          try {
            const result = await forkCheckpoint(cp.id);
            // Navigate to the new session — mirrors SessionRow.duplicate.
            await goto(`/sessions/${encodeURIComponent(result.new_session_id)}`);
          } catch (err) {
            console.error("forkCheckpoint failed:", err);
          }
        })();
      },
      [MENU_ACTION_CHECKPOINT_COPY_LABEL]: () => {
        void navigator.clipboard.writeText(cp.label);
      },
      [MENU_ACTION_CHECKPOINT_COPY_ID]: () => {
        void navigator.clipboard.writeText(cp.id);
      },
      [MENU_ACTION_CHECKPOINT_DELETE]: () => {
        // Capture snapshot before deletion so the inverse can recreate it.
        const snapshot: CheckpointOut = { ...cp };
        void (async () => {
          try {
            await deleteCheckpoint(snapshot.id);
            checkpoints = checkpoints.filter((row) => row.id !== snapshot.id);
            undoStore.push({
              message: UNDO_TOAST_STRINGS.checkpointDeleted,
              inverse: async () => {
                const restored = await createCheckpoint({
                  sessionId: snapshot.session_id,
                  messageId: snapshot.message_id,
                  label: snapshot.label,
                });
                checkpoints = [...checkpoints, restored];
              },
            });
          } catch (err) {
            console.error("deleteCheckpoint failed:", err);
          }
        })();
      },
    };
  }
</script>

<aside
  class="checkpoint-gutter pointer-events-none absolute right-1 top-0 z-10 h-full w-32"
  data-testid="checkpoint-gutter"
  aria-label={CHECKPOINT_GUTTER_STRINGS.gutterAriaLabel}
>
  {#each checkpoints as cp (cp.id)}
    {#if chipTops[cp.id] !== undefined}
      <button
        type="button"
        class="checkpoint-gutter__chip pointer-events-auto absolute right-0 max-w-[8rem] truncate rounded border border-accent/60 bg-surface-1 px-2 py-0.5 text-xs text-fg-strong shadow hover:bg-accent/20"
        style:top="{chipTops[cp.id]}px"
        data-testid="checkpoint-chip"
        data-checkpoint-id={cp.id}
        title={cp.label}
        onclick={() => jumpToAnchor(cp.message_id)}
        use:contextMenu={{
          target: MENU_TARGET_CHECKPOINT,
          handlers: makeMenuHandlers(cp),
          data: { checkpointId: cp.id, sessionId: cp.session_id },
        }}
      >
        <span aria-hidden="true">⚑</span>
        {cp.label}
      </button>
    {/if}
  {/each}
</aside>
