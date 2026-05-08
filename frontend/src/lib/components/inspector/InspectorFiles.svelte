<script lang="ts">
  /**
   * Files subsection — aggregated view of every file path the agent
   * has touched in the active session.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/chat.md`` §"Inspector pane" §"Files" documents
   *   the data source (``conversationStore.turns``), path-key
   *   precedence, and empty-state copy.
   * - gap-cycle-09-003 specifies the path-extraction rules and the
   *   row shape: home-shortened path, last action verb, touch count,
   *   and last-touch time.
   *
   * Path extraction reads three input keys per tool call:
   * ``Read`` / ``Write`` / ``Edit`` → ``file_path``;
   * ``NotebookEdit`` → ``notebook_path``;
   * ``Grep`` → ``path``.
   * ``Bash`` and ``Glob`` tool calls are skipped entirely.
   *
   * Rows are sorted most-recent first. Paths starting with
   * ``/home/<user>/`` are shortened to ``~/`` for column fit.
   *
   * The ``turns`` prop is a test seam — production callers pass
   * nothing and the component reads from :data:`conversationStore`.
   */
  import { INSPECTOR_STRINGS } from "../../config";
  import { conversationStore, type MessageTurnView } from "../../stores/conversation.svelte";
  import { formatAbsolute } from "../../utils/datetime";
  import type { SessionOut } from "../../api/sessions";

  /**
   * Aggregated row shape. One row per distinct file path, sorted
   * most-recent touch first.
   */
  interface FileRow {
    /** Original unshortened path — used as the dedup key and title tooltip. */
    path: string;
    /** ``/home/<user>/…`` shortened to ``~/…``; other paths unchanged. */
    shortPath: string;
    /** Verb of the most-recent touch: ``Read``, ``Write``, ``Edit``, ``NotebookEdit``, or ``Grep``. */
    lastVerb: string;
    /** Total number of times this path was touched in the session. */
    touchCount: number;
    /** Epoch-ms timestamp of the most-recent touch; ``null`` when unavailable. */
    lastTouchMs: number | null;
  }

  interface Props {
    /**
     * Active session row. Accepted for interface parity with the other
     * inspector subsections — the Files tab derives its data from
     * :data:`conversationStore`, not from the session row directly.
     */
    session: SessionOut;
    /**
     * Test seam. Production callers pass nothing; the component reads
     * :data:`conversationStore.turns`. Tests inject a fixture list so
     * each test owns its state without touching the module-singleton
     * store.
     */
    turns?: readonly MessageTurnView[];
  }

  // ``_session`` alias: the value is unused inside the body — accepted
  // only so the Inspector shell can pass ``{session}`` uniformly to
  // every subsection (a future per-session file filter would drop the
  // underscore).
  const { session: _session, turns: turnsProp = undefined }: Props = $props();

  /** Tools whose output is never a specific file path — skip entirely. */
  const SKIP_TOOLS = new Set(["Bash", "Glob"]);

  /**
   * Extract the file path from a tool call's ``inputJson``.
   *
   * Key precedence (mirrors v17 FilesTab logic):
   * 1. ``file_path``    — Read, Write, Edit
   * 2. ``notebook_path`` — NotebookEdit
   * 3. ``path``         — Grep
   *
   * Returns ``null`` when the tool is in the skip list, when
   * ``inputJson`` cannot be parsed, or when none of the three keys
   * resolves to a non-empty string.
   */
  function extractPath(name: string, inputJson: string): string | null {
    if (SKIP_TOOLS.has(name)) return null;
    try {
      const parsed = JSON.parse(inputJson) as Record<string, unknown>;
      if (typeof parsed.file_path === "string" && parsed.file_path.length > 0) {
        return parsed.file_path;
      }
      if (typeof parsed.notebook_path === "string" && parsed.notebook_path.length > 0) {
        return parsed.notebook_path;
      }
      if (typeof parsed.path === "string" && parsed.path.length > 0) {
        return parsed.path;
      }
    } catch {
      // Malformed inputJson — skip silently.
    }
    return null;
  }

  /**
   * Shorten ``/home/<user>/…`` to ``~/…`` for column fit.
   *
   * Matches exactly one path segment after ``/home/`` so nested home
   * directories (``/home/a/b/c``) collapse to ``~/b/c``.
   */
  function shortenHome(path: string): string {
    return path.replace(/^\/home\/[^/]+\//, "~/");
  }

  /** Active turns: the test-injected list when provided, else the store. */
  const activeTurns = $derived(turnsProp ?? conversationStore.turns);

  /**
   * Aggregated file rows, sorted most-recent first.
   *
   * For each tool call the timestamp is derived as:
   * 1. ``startedAt`` (from :interface:`ToolCallView`) if non-zero —
   *    set to ``Date.now()`` when the live ``tool_call_start`` event
   *    arrives.
   * 2. Parsed ``createdAt`` of the parent turn — used for calls
   *    hydrated from the DB (where ``startedAt`` is always 0).
   * 3. ``null`` when neither is available.
   *
   * Entries without a timestamp sort after all timestamped rows.
   */
  const fileRows = $derived.by<FileRow[]>(() => {
    const map = new Map<string, FileRow>();

    for (const turn of activeTurns) {
      for (const tc of turn.toolCalls) {
        const path = extractPath(tc.name, tc.inputJson);
        if (path === null) continue;

        let touchMs: number | null = null;
        if (tc.startedAt !== 0) {
          touchMs = tc.startedAt;
        } else if (turn.createdAt !== null) {
          touchMs = new Date(turn.createdAt).getTime();
        }

        const existing = map.get(path);
        if (existing === undefined) {
          map.set(path, {
            path,
            shortPath: shortenHome(path),
            lastVerb: tc.name,
            touchCount: 1,
            lastTouchMs: touchMs,
          });
        } else {
          // Update lastVerb / lastTouchMs when this touch is at least as
          // recent as the recorded one — ``>=`` so equal timestamps (e.g.
          // two hydrated calls within the same DB-persisted turn) also
          // advance the verb to reflect the later call in iteration order.
          const isNewer =
            touchMs !== null && (existing.lastTouchMs === null || touchMs >= existing.lastTouchMs);
          map.set(path, {
            ...existing,
            touchCount: existing.touchCount + 1,
            lastVerb: isNewer ? tc.name : existing.lastVerb,
            lastTouchMs: isNewer ? touchMs : existing.lastTouchMs,
          });
        }
      }
    }

    return [...map.values()].sort((a, b) => {
      if (a.lastTouchMs === null && b.lastTouchMs === null) return 0;
      if (a.lastTouchMs === null) return 1;
      if (b.lastTouchMs === null) return -1;
      return b.lastTouchMs - a.lastTouchMs;
    });
  });
</script>

<section class="inspector-files flex flex-col gap-3" data-testid="inspector-files">
  <h3 class="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-fg-muted">
    {INSPECTOR_STRINGS.filesHeading}
    {#if fileRows.length > 0}
      <span
        class="rounded bg-surface-2 px-1.5 py-0.5 text-xs font-medium tabular-nums text-fg"
        data-testid="inspector-files-count"
      >
        {fileRows.length}
      </span>
    {/if}
  </h3>

  {#if fileRows.length === 0}
    <div data-testid="inspector-files-empty">
      <p class="text-sm text-fg-muted">{INSPECTOR_STRINGS.filesEmptyHeading}</p>
      <p class="mt-1 text-xs text-fg-muted">{INSPECTOR_STRINGS.filesEmptyBody}</p>
    </div>
  {:else}
    <ul class="flex flex-col gap-1" data-testid="inspector-files-list">
      {#each fileRows as row (row.path)}
        <li class="flex min-w-0 items-baseline gap-2 text-xs" data-testid="inspector-files-row">
          <span
            class="min-w-0 flex-1 truncate font-mono text-fg"
            title={row.path}
            data-testid="inspector-files-path"
          >
            {row.shortPath}
          </span>
          <span class="shrink-0 text-fg-muted" data-testid="inspector-files-verb">
            {row.lastVerb}
          </span>
          {#if row.touchCount > 1}
            <span
              class="shrink-0 tabular-nums text-fg-muted"
              data-testid="inspector-files-count-badge"
            >
              × {row.touchCount}
            </span>
          {/if}
          <span class="shrink-0 tabular-nums text-fg-muted" data-testid="inspector-files-time">
            {row.lastTouchMs !== null ? formatAbsolute(row.lastTouchMs) : "—"}
          </span>
        </li>
      {/each}
    </ul>
  {/if}
</section>
