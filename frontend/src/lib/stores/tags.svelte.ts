/**
 * Tag store — global tag list + the three-section sidebar filter sets.
 *
 * Per arch §2.2 the canonical store for tags is a single Svelte 5
 * runes module exporting a ``$state`` proxy plus a small imperative
 * API. Two responsibilities live here:
 *
 * 1. Cache the tag list so the sidebar's filter panel + each session
 *    row's tag chips render against the same source of truth.
 * 2. Own the **three active filter sets** — one per tag class
 *    (project / severity / other). Selections within a class apply
 *    OR semantics; selections across classes apply AND. An empty
 *    section means "no constraint from this class" (NOT "exclude
 *    everything") — the filter panel renders an empty section and
 *    the resulting query omits the matching `tag_ids_<class>=` param
 *    so the backend leaves it unconstrained.
 *
 * Per ``docs/behavior/chat.md`` the sidebar's tag-chip clicks call
 * :func:`toggleTag` (passing the tag's class) to flip the chip in
 * or out of its section's set. The :mod:`stores/sessions.svelte.ts`
 * store forwards the three sets to ``GET /api/sessions`` as
 * ``tag_ids_project=`` / ``tag_ids_severity=`` / ``tag_ids_other=``.
 *
 * Pinned + sort_order rendering: :data:`byClass` returns each
 * class-bucket sorted ``(pinned DESC, sort_order ASC, name ASC)``
 * so the filter panel doesn't have to re-sort at render time.
 */
import {
  listTags,
  TAG_CLASS_PROJECT,
  TAG_CLASS_SEVERITY,
  type TagClass,
  type TagOut,
} from "../api/tags";

interface TagsState {
  /** Last successful response from ``GET /api/tags``. */
  all: TagOut[];
  /** Selected project-class tag ids. OR within; AND with other sections. */
  selectedProjectIds: ReadonlySet<number>;
  /** Selected severity-class tag ids. OR within; AND with other sections. */
  selectedSeverityIds: ReadonlySet<number>;
  /** Selected general-class tag ids. OR within; AND with other sections. */
  selectedOtherIds: ReadonlySet<number>;
  /** ``true`` while a refresh is in flight. */
  loading: boolean;
  /** Last error from a refresh attempt (cleared on success). */
  error: Error | null;
}

const state: TagsState = $state({
  all: [],
  selectedProjectIds: new Set<number>(),
  selectedSeverityIds: new Set<number>(),
  selectedOtherIds: new Set<number>(),
  loading: false,
  error: null,
});

/**
 * The reactive ``$state`` proxy. Components destructure from it via
 * Svelte's ``$derived`` rather than reaching into another store
 * directly (per arch §2.2's invariant).
 */
export const tagsStore = state;

/**
 * Refresh the global tag list from ``GET /api/tags``.
 *
 * The store is single-tenant — calling :func:`refresh` while a
 * previous request is in flight cancels the older one via the
 * tracked ``AbortController``.
 */
let refreshController: AbortController | null = null;

export async function refreshTags(): Promise<void> {
  refreshController?.abort();
  const controller = new AbortController();
  refreshController = controller;
  state.loading = true;
  try {
    const tags = await listTags({ signal: controller.signal });
    if (controller.signal.aborted) {
      return;
    }
    state.all = tags;
    state.error = null;
  } catch (error) {
    if (controller.signal.aborted || isAbortError(error)) {
      return;
    }
    state.error = error instanceof Error ? error : new Error(String(error));
  } finally {
    if (refreshController === controller) {
      refreshController = null;
    }
    state.loading = false;
  }
}

/**
 * Flip ``tagId`` in or out of its class-section's filter set.
 *
 * The class is required (not inferred) so the caller is forced to
 * be explicit about which section the chip belongs to — re-reading
 * the tag from :data:`tagsStore.all` to look up the class would
 * couple every chip click to a list traversal and would silently
 * drop clicks for tags not yet in the cache.
 *
 * Replaces the set wholesale (rather than mutating in place) so any
 * component bound to the section's ``selected*Ids`` via Svelte 5's
 * reactivity sees a fresh reference and re-renders.
 */
export function toggleTag(tagId: number, klass: TagClass): void {
  const current = _selectionForClass(klass);
  const next = new Set(current);
  if (next.has(tagId)) {
    next.delete(tagId);
  } else {
    next.add(tagId);
  }
  _setSelectionForClass(klass, next);
}

/**
 * Clear every section's filter set (sidebar's "Clear filter" button
 * + the user's Esc-while-filter-focused path per
 * ``keyboard-shortcuts.md`` §"Esc cascade" once that wiring lands).
 */
export function clearTagFilter(): void {
  if (
    state.selectedProjectIds.size === 0 &&
    state.selectedSeverityIds.size === 0 &&
    state.selectedOtherIds.size === 0
  ) {
    return;
  }
  state.selectedProjectIds = new Set<number>();
  state.selectedSeverityIds = new Set<number>();
  state.selectedOtherIds = new Set<number>();
}

/**
 * The three-section filter snapshot — one ``ReadonlySet<number>``
 * per class. Components forward this to
 * :func:`refreshSessions` instead of accessing the store's three
 * fields independently (which would also work, but couples every
 * call site to the field names).
 */
export function currentFilter(): {
  project: ReadonlySet<number>;
  severity: ReadonlySet<number>;
  other: ReadonlySet<number>;
} {
  return {
    project: state.selectedProjectIds,
    severity: state.selectedSeverityIds,
    other: state.selectedOtherIds,
  };
}

/**
 * Tag list bucketed by class, each bucket pre-sorted
 * ``(pinned DESC, sort_order ASC, name ASC)``. The filter panel and
 * the ``/tags`` management page both read this — neither has to
 * re-sort at render time.
 *
 * Re-derived imperatively so consumers can call it from a
 * ``$derived`` block without spinning up a runtime cost on every
 * read (the function does one O(n log n) sort per call). For the
 * worst-case tag count Bearings supports (≤ 200 tags) this is
 * trivial — but keep it pure so the function is easy to reason
 * about under reactivity.
 */
export function tagsByClass(tags: readonly TagOut[]): {
  project: TagOut[];
  severity: TagOut[];
  other: TagOut[];
} {
  const project: TagOut[] = [];
  const severity: TagOut[] = [];
  const other: TagOut[] = [];
  for (const tag of tags) {
    if (tag.class_ === TAG_CLASS_PROJECT) {
      project.push(tag);
    } else if (tag.class_ === TAG_CLASS_SEVERITY) {
      severity.push(tag);
    } else {
      other.push(tag);
    }
  }
  const cmp = (a: TagOut, b: TagOut): number => {
    if (a.pinned !== b.pinned) {
      return a.pinned ? -1 : 1;
    }
    if (a.sort_order !== b.sort_order) {
      return a.sort_order - b.sort_order;
    }
    return a.name.localeCompare(b.name);
  };
  project.sort(cmp);
  severity.sort(cmp);
  other.sort(cmp);
  return { project, severity, other };
}

/**
 * Reset the store to its initial values. Test-only — production code
 * never tears the store down (the page reload does that). Exported as
 * a named function so unit tests can call it explicitly rather than
 * mutating state through a backdoor.
 */
export function _resetForTests(): void {
  state.all = [];
  state.selectedProjectIds = new Set<number>();
  state.selectedSeverityIds = new Set<number>();
  state.selectedOtherIds = new Set<number>();
  state.loading = false;
  state.error = null;
  refreshController?.abort();
  refreshController = null;
}

function _selectionForClass(klass: TagClass): ReadonlySet<number> {
  if (klass === TAG_CLASS_PROJECT) {
    return state.selectedProjectIds;
  }
  if (klass === TAG_CLASS_SEVERITY) {
    return state.selectedSeverityIds;
  }
  return state.selectedOtherIds;
}

function _setSelectionForClass(klass: TagClass, value: ReadonlySet<number>): void {
  if (klass === TAG_CLASS_PROJECT) {
    state.selectedProjectIds = value;
  } else if (klass === TAG_CLASS_SEVERITY) {
    state.selectedSeverityIds = value;
  } else {
    state.selectedOtherIds = value;
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
