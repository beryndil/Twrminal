/**
 * Context-menu action handler factory for ``MENU_TARGET_TAG`` entries.
 *
 * Centralises the per-action business logic that consumers (currently
 * :component:`TagFilterPanel`) bind via ``use:contextMenu``.  Each
 * consumer calls :func:`createTagMenuHandlers` with the tag row and a
 * callback bag; the returned ``Record<string, () => void>`` is passed
 * directly to the ``use:contextMenu`` directive's ``handlers`` prop.
 *
 * Separating the factory from the component keeps the component thin
 * (pure rendering) and makes the handler logic independently testable.
 *
 * Behavior anchor: ``docs/behavior/context-menus.md`` §Tag.
 */
import {
  MENU_ACTION_TAG_COPY_NAME,
  MENU_ACTION_TAG_DELETE,
  MENU_ACTION_TAG_EDIT,
  MENU_ACTION_TAG_PIN,
  MENU_ACTION_TAG_UNPIN,
} from "../../config";
import type { TagOut } from "../../api/tags";
import { deleteTag, patchTagPinned } from "../../api/tags";
import type { HandlerEntry } from "../store.svelte";

/**
 * Callbacks the consumer supplies to :func:`createTagMenuHandlers`.
 *
 * ``onEdit`` receives the tag row so the consumer can open a
 * :component:`TagEdit` modal pre-populated with the tag's current
 * values. ``onRefresh`` is called after pin / unpin / delete so tag
 * chip surfaces stay in sync with the server state.
 * ``onRequestDelete`` is called BEFORE the API call so the consumer
 * can show a confirmation dialog; the consumer then calls the returned
 * ``confirmDelete`` function to proceed.
 */
export interface TagMenuCallbacks {
  /** Open the TagEdit modal for this tag. */
  onEdit: (tag: TagOut) => void;
  /**
   * Trigger a delete-confirmation flow. The consumer shows a dialog;
   * if the user confirms, it calls ``confirmDelete(tag.id)``.
   */
  onRequestDelete: (tag: TagOut) => void;
  /** Called after pin / unpin so the consumer can refresh its tag list. */
  onRefresh: () => void | Promise<void>;
}

/**
 * Build the handler map for ``use:contextMenu`` on a tag chip.
 *
 * Pin / Unpin are mutually exclusive: only the applicable action fires
 * (the action registry lists both; the menu hides whichever has no
 * handler). Copy writes the tag name to the clipboard. Edit delegates
 * to ``callbacks.onEdit``; delete to ``callbacks.onRequestDelete`` so
 * the consumer controls the confirm-dialog UX.
 */
export function createTagMenuHandlers(
  tag: TagOut,
  callbacks: TagMenuCallbacks,
): Readonly<Record<string, HandlerEntry>> {
  const handlers: Record<string, HandlerEntry> = {
    [MENU_ACTION_TAG_COPY_NAME]: () => {
      void navigator.clipboard.writeText(tag.name);
    },
    [MENU_ACTION_TAG_EDIT]: () => {
      callbacks.onEdit(tag);
    },
    // tag.delete: consumer owns the confirm dialog via onRequestDelete, so
    // the central bridge skips its own dialog (skipMenuConfirm: true).
    [MENU_ACTION_TAG_DELETE]: {
      handler: () => {
        callbacks.onRequestDelete(tag);
      },
      skipMenuConfirm: true,
    },
  };

  // Pin and unpin are mutually exclusive: only whichever applies is
  // included so the menu primitive hides the inapplicable action
  // (no handler → no render).
  if (tag.pinned) {
    handlers[MENU_ACTION_TAG_UNPIN] = () => {
      void patchTagPinned(tag.id, false).then(() => callbacks.onRefresh());
    };
  } else {
    handlers[MENU_ACTION_TAG_PIN] = () => {
      void patchTagPinned(tag.id, true).then(() => callbacks.onRefresh());
    };
  }

  return handlers;
}

/**
 * Execute a confirmed tag delete.
 *
 * Separated from the handler so the confirmation dialog (which lives in
 * the consumer component) can call this after the user clicks "Delete".
 * Returns the deleted tag id so the consumer can prune its local list.
 */
export async function executeTagDelete(tagId: number): Promise<number> {
  await deleteTag(tagId);
  return tagId;
}
