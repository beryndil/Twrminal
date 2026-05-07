/**
 * Context-menu action registry — per-target action lists that drive
 * the menu UI per ``docs/behavior/context-menus.md`` §"Per-target
 * action lists".
 *
 * Action ids are public + stable (referenced from
 * ``~/.config/bearings/menus.toml`` for user pin / hide overrides).
 * Action *handlers* are bound at the consumer mount site; the menu
 * primitive walks the per-target action list, looks up a handler in
 * the consumer-provided handler map, and renders each entry as
 * enabled when a handler exists / disabled otherwise.
 *
 * Adding an action means:
 *
 * 1. Add the action-id constant in :mod:`config.ts`.
 * 2. Add a label entry in :data:`CONTEXT_MENU_STRINGS.actionLabels`.
 * 3. Append the descriptor to the matching per-target array below.
 * 4. Bind a handler in the consumer (e.g. ``SessionRow.svelte``).
 */
import {
  MENU_ACTION_ATTACHMENT_COPY_FILENAME,
  MENU_ACTION_ATTACHMENT_COPY_PATH,
  MENU_ACTION_ATTACHMENT_OPEN_IN_EDITOR,
  MENU_ACTION_ATTACHMENT_OPEN_IN_FILE_EXPLORER,
  MENU_ACTION_ATTACHMENT_REMOVE,
  MENU_ACTION_CHECKPOINT_COPY_ID,
  MENU_ACTION_CHECKPOINT_COPY_LABEL,
  MENU_ACTION_CHECKPOINT_DELETE,
  MENU_ACTION_CHECKPOINT_FORK,
  MENU_ACTION_CODE_BLOCK_COPY,
  MENU_ACTION_CODE_BLOCK_COPY_WITH_FENCE,
  MENU_ACTION_CODE_BLOCK_OPEN_IN_EDITOR,
  MENU_ACTION_CODE_BLOCK_SAVE_TO_FILE,
  MENU_ACTION_LINK_COPY_TEXT,
  MENU_ACTION_LINK_COPY_URL,
  MENU_ACTION_LINK_OPEN_IN_EDITOR,
  MENU_ACTION_LINK_OPEN_NEW_TAB,
  MENU_ACTION_MESSAGE_COPY_AS_MARKDOWN,
  MENU_ACTION_MESSAGE_COPY_CONTENT,
  MENU_ACTION_MESSAGE_COPY_ID,
  MENU_ACTION_MESSAGE_DELETE,
  MENU_ACTION_MESSAGE_FORK_FROM_HERE,
  MENU_ACTION_MESSAGE_HIDE_FROM_CONTEXT,
  MENU_ACTION_MESSAGE_JUMP_TO_TURN,
  MENU_ACTION_MESSAGE_MOVE_TO_SESSION,
  MENU_ACTION_MESSAGE_PIN,
  MENU_ACTION_MESSAGE_REGENERATE,
  MENU_ACTION_MESSAGE_REGENERATE_IN_PLACE,
  MENU_ACTION_MESSAGE_SPLIT_HERE,
  MENU_ACTION_MULTI_SELECT_CLEAR,
  MENU_ACTION_MULTI_SELECT_CLOSE,
  MENU_ACTION_MULTI_SELECT_DELETE,
  MENU_ACTION_MULTI_SELECT_EXPORT,
  MENU_ACTION_MULTI_SELECT_TAG,
  MENU_ACTION_MULTI_SELECT_UNTAG,
  MENU_ACTION_PENDING_OPERATION_COPY_COMMAND,
  MENU_ACTION_PENDING_OPERATION_COPY_NAME,
  MENU_ACTION_PENDING_OPERATION_DISMISS,
  MENU_ACTION_PENDING_OPERATION_OPEN_IN_EDITOR,
  MENU_ACTION_PENDING_OPERATION_RESOLVE,
  MENU_ACTION_SESSION_ARCHIVE,
  MENU_ACTION_SESSION_CHANGE_MODEL,
  MENU_ACTION_SESSION_COPY_ID,
  MENU_ACTION_SESSION_COPY_SHARE_LINK,
  MENU_ACTION_SESSION_COPY_TITLE,
  MENU_ACTION_SESSION_DELETE,
  MENU_ACTION_SESSION_EXPORT_JSON,
  MENU_ACTION_SESSION_OPEN_IN_TERMINAL,
  MENU_ACTION_SESSION_DUPLICATE,
  MENU_ACTION_SESSION_EDIT_TAGS,
  MENU_ACTION_SESSION_FORK_FROM_LAST_MESSAGE,
  MENU_ACTION_SESSION_OPEN_IN_NEW_TAB,
  MENU_ACTION_SESSION_PIN,
  MENU_ACTION_SESSION_REOPEN,
  MENU_ACTION_SESSION_RENAME,
  MENU_ACTION_SESSION_SAVE_AS_TEMPLATE,
  MENU_ACTION_SESSION_UNPIN,
  MENU_ACTION_TAG_CHIP_COPY_NAME,
  MENU_ACTION_TAG_CHIP_DETACH,
  MENU_ACTION_TAG_COPY_NAME,
  MENU_ACTION_TAG_DELETE,
  MENU_ACTION_TAG_EDIT,
  MENU_ACTION_TAG_PIN,
  MENU_ACTION_TAG_UNPIN,
  MENU_ACTION_TOOL_CALL_COPY_ID,
  MENU_ACTION_TOOL_CALL_COPY_INPUT,
  MENU_ACTION_TOOL_CALL_COPY_NAME,
  MENU_ACTION_TOOL_CALL_COPY_OUTPUT,
  MENU_ACTION_TOOL_CALL_RETRY,
  MENU_SECTION_COPY,
  MENU_SECTION_CREATE,
  MENU_SECTION_DESTRUCTIVE,
  MENU_SECTION_EDIT,
  MENU_SECTION_NAVIGATE,
  MENU_SECTION_ORGANIZE,
  MENU_SECTION_PRIMARY,
  MENU_SECTION_VIEW,
  MENU_TARGET_ATTACHMENT,
  MENU_TARGET_CHECKPOINT,
  MENU_TARGET_CODE_BLOCK,
  MENU_TARGET_LINK,
  MENU_TARGET_MESSAGE,
  MENU_TARGET_MULTI_SELECT,
  MENU_TARGET_PENDING_OPERATION,
  MENU_TARGET_SESSION,
  MENU_TARGET_TAG,
  MENU_TARGET_TAG_CHIP,
  MENU_TARGET_TOOL_CALL,
  type MenuSectionId,
  type MenuTargetId,
} from "../config";

/**
 * Single action descriptor inside a per-target action list. The
 * shape mirrors the per-row columns in
 * ``docs/behavior/context-menus.md`` §"Per-target action lists".
 */
export interface MenuActionDescriptor {
  /** Public action id; matches a key in :data:`CONTEXT_MENU_STRINGS.actionLabels`. */
  readonly id: string;
  /** Section the action renders under. */
  readonly section: MenuSectionId;
  /** Hidden until the user opens the menu with Shift held. */
  readonly advanced?: boolean;
  /** Routes through a confirmation dialog before firing. */
  readonly destructive?: boolean;
  /**
   * Trailing arrow indicates a submenu is opened on hover / right-arrow.
   * The doc renders ``▸`` on these entries.
   */
  readonly submenu?: boolean;
  /**
   * Override the keyboard mnemonic character for this action (single
   * alphanumeric, case-insensitive). When omitted the first alphanumeric
   * character of the localised label is used as the mnemonic. The
   * underlined glyph in the rendered label indicates the mnemonic.
   */
  readonly mnemonic?: string;
}

const SESSION_ACTIONS: readonly MenuActionDescriptor[] = [
  { id: MENU_ACTION_SESSION_OPEN_IN_NEW_TAB, section: MENU_SECTION_NAVIGATE },
  { id: MENU_ACTION_SESSION_RENAME, section: MENU_SECTION_EDIT },
  { id: MENU_ACTION_SESSION_EDIT_TAGS, section: MENU_SECTION_EDIT },
  { id: MENU_ACTION_SESSION_CHANGE_MODEL, section: MENU_SECTION_EDIT, submenu: true },
  { id: MENU_ACTION_SESSION_DUPLICATE, section: MENU_SECTION_CREATE },
  { id: MENU_ACTION_SESSION_SAVE_AS_TEMPLATE, section: MENU_SECTION_CREATE },
  { id: MENU_ACTION_SESSION_FORK_FROM_LAST_MESSAGE, section: MENU_SECTION_CREATE, advanced: true },
  { id: MENU_ACTION_SESSION_PIN, section: MENU_SECTION_ORGANIZE },
  { id: MENU_ACTION_SESSION_UNPIN, section: MENU_SECTION_ORGANIZE },
  { id: MENU_ACTION_SESSION_ARCHIVE, section: MENU_SECTION_ORGANIZE },
  { id: MENU_ACTION_SESSION_REOPEN, section: MENU_SECTION_ORGANIZE },
  { id: MENU_ACTION_SESSION_COPY_ID, section: MENU_SECTION_COPY, advanced: true },
  { id: MENU_ACTION_SESSION_COPY_TITLE, section: MENU_SECTION_COPY },
  { id: MENU_ACTION_SESSION_COPY_SHARE_LINK, section: MENU_SECTION_COPY, advanced: true },
  { id: MENU_ACTION_SESSION_EXPORT_JSON, section: MENU_SECTION_COPY },
  { id: MENU_ACTION_SESSION_DELETE, section: MENU_SECTION_DESTRUCTIVE, destructive: true },
  { id: MENU_ACTION_SESSION_OPEN_IN_TERMINAL, section: MENU_SECTION_NAVIGATE, advanced: true },
];

const MESSAGE_ACTIONS: readonly MenuActionDescriptor[] = [
  { id: MENU_ACTION_MESSAGE_JUMP_TO_TURN, section: MENU_SECTION_NAVIGATE },
  { id: MENU_ACTION_MESSAGE_COPY_CONTENT, section: MENU_SECTION_COPY },
  { id: MENU_ACTION_MESSAGE_COPY_AS_MARKDOWN, section: MENU_SECTION_COPY, advanced: true },
  { id: MENU_ACTION_MESSAGE_COPY_ID, section: MENU_SECTION_COPY, advanced: true },
  { id: MENU_ACTION_MESSAGE_PIN, section: MENU_SECTION_ORGANIZE },
  { id: MENU_ACTION_MESSAGE_HIDE_FROM_CONTEXT, section: MENU_SECTION_ORGANIZE, advanced: true },
  { id: MENU_ACTION_MESSAGE_MOVE_TO_SESSION, section: MENU_SECTION_ORGANIZE },
  { id: MENU_ACTION_MESSAGE_SPLIT_HERE, section: MENU_SECTION_ORGANIZE },
  { id: MENU_ACTION_MESSAGE_FORK_FROM_HERE, section: MENU_SECTION_CREATE, advanced: true },
  { id: MENU_ACTION_MESSAGE_REGENERATE, section: MENU_SECTION_CREATE },
  { id: MENU_ACTION_MESSAGE_REGENERATE_IN_PLACE, section: MENU_SECTION_CREATE, advanced: true },
  {
    id: MENU_ACTION_MESSAGE_DELETE,
    section: MENU_SECTION_DESTRUCTIVE,
    destructive: true,
    advanced: true,
  },
];

const TAG_ACTIONS: readonly MenuActionDescriptor[] = [
  { id: MENU_ACTION_TAG_PIN, section: MENU_SECTION_ORGANIZE },
  { id: MENU_ACTION_TAG_UNPIN, section: MENU_SECTION_ORGANIZE },
  { id: MENU_ACTION_TAG_COPY_NAME, section: MENU_SECTION_COPY },
  { id: MENU_ACTION_TAG_EDIT, section: MENU_SECTION_EDIT },
  {
    id: MENU_ACTION_TAG_DELETE,
    section: MENU_SECTION_DESTRUCTIVE,
    destructive: true,
    advanced: true,
  },
];

const TAG_CHIP_ACTIONS: readonly MenuActionDescriptor[] = [
  { id: MENU_ACTION_TAG_CHIP_COPY_NAME, section: MENU_SECTION_COPY },
  { id: MENU_ACTION_TAG_CHIP_DETACH, section: MENU_SECTION_DESTRUCTIVE, destructive: true },
];

const TOOL_CALL_ACTIONS: readonly MenuActionDescriptor[] = [
  { id: MENU_ACTION_TOOL_CALL_COPY_NAME, section: MENU_SECTION_COPY },
  { id: MENU_ACTION_TOOL_CALL_COPY_INPUT, section: MENU_SECTION_COPY },
  { id: MENU_ACTION_TOOL_CALL_COPY_OUTPUT, section: MENU_SECTION_COPY },
  { id: MENU_ACTION_TOOL_CALL_COPY_ID, section: MENU_SECTION_COPY, advanced: true },
  { id: MENU_ACTION_TOOL_CALL_RETRY, section: MENU_SECTION_EDIT, advanced: true },
];

const CODE_BLOCK_ACTIONS: readonly MenuActionDescriptor[] = [
  { id: MENU_ACTION_CODE_BLOCK_COPY, section: MENU_SECTION_COPY },
  { id: MENU_ACTION_CODE_BLOCK_COPY_WITH_FENCE, section: MENU_SECTION_COPY, advanced: true },
  { id: MENU_ACTION_CODE_BLOCK_SAVE_TO_FILE, section: MENU_SECTION_EDIT },
  { id: MENU_ACTION_CODE_BLOCK_OPEN_IN_EDITOR, section: MENU_SECTION_EDIT, advanced: true },
];

const LINK_ACTIONS: readonly MenuActionDescriptor[] = [
  { id: MENU_ACTION_LINK_COPY_URL, section: MENU_SECTION_COPY },
  { id: MENU_ACTION_LINK_COPY_TEXT, section: MENU_SECTION_COPY, advanced: true },
  { id: MENU_ACTION_LINK_OPEN_NEW_TAB, section: MENU_SECTION_NAVIGATE },
  { id: MENU_ACTION_LINK_OPEN_IN_EDITOR, section: MENU_SECTION_NAVIGATE, advanced: true },
];

// Phase 14 — Checkpoint surface (gutter chip).
const CHECKPOINT_ACTIONS: readonly MenuActionDescriptor[] = [
  { id: MENU_ACTION_CHECKPOINT_FORK, section: MENU_SECTION_PRIMARY },
  { id: MENU_ACTION_CHECKPOINT_COPY_LABEL, section: MENU_SECTION_COPY },
  { id: MENU_ACTION_CHECKPOINT_COPY_ID, section: MENU_SECTION_COPY, advanced: true },
  { id: MENU_ACTION_CHECKPOINT_DELETE, section: MENU_SECTION_DESTRUCTIVE, destructive: true },
];

const MULTI_SELECT_ACTIONS: readonly MenuActionDescriptor[] = [
  { id: MENU_ACTION_MULTI_SELECT_CLEAR, section: MENU_SECTION_NAVIGATE },
  { id: MENU_ACTION_MULTI_SELECT_TAG, section: MENU_SECTION_ORGANIZE, submenu: true },
  {
    id: MENU_ACTION_MULTI_SELECT_UNTAG,
    section: MENU_SECTION_ORGANIZE,
    submenu: true,
    advanced: true,
  },
  { id: MENU_ACTION_MULTI_SELECT_CLOSE, section: MENU_SECTION_ORGANIZE },
  { id: MENU_ACTION_MULTI_SELECT_EXPORT, section: MENU_SECTION_COPY },
  { id: MENU_ACTION_MULTI_SELECT_DELETE, section: MENU_SECTION_DESTRUCTIVE, destructive: true },
];

// Phase 15 — Attachment surface (composer / transcript chip).
const ATTACHMENT_ACTIONS: readonly MenuActionDescriptor[] = [
  { id: MENU_ACTION_ATTACHMENT_COPY_PATH, section: MENU_SECTION_COPY },
  { id: MENU_ACTION_ATTACHMENT_COPY_FILENAME, section: MENU_SECTION_COPY },
  { id: MENU_ACTION_ATTACHMENT_OPEN_IN_EDITOR, section: MENU_SECTION_VIEW },
  {
    id: MENU_ACTION_ATTACHMENT_OPEN_IN_FILE_EXPLORER,
    section: MENU_SECTION_VIEW,
    advanced: true,
  },
  { id: MENU_ACTION_ATTACHMENT_REMOVE, section: MENU_SECTION_DESTRUCTIVE, destructive: true },
];

// Phase 16 — Pending operation surface (row inside the floating card).
const PENDING_OPERATION_ACTIONS: readonly MenuActionDescriptor[] = [
  { id: MENU_ACTION_PENDING_OPERATION_RESOLVE, section: MENU_SECTION_PRIMARY },
  {
    id: MENU_ACTION_PENDING_OPERATION_DISMISS,
    section: MENU_SECTION_DESTRUCTIVE,
    destructive: true,
  },
  { id: MENU_ACTION_PENDING_OPERATION_COPY_NAME, section: MENU_SECTION_COPY },
  { id: MENU_ACTION_PENDING_OPERATION_COPY_COMMAND, section: MENU_SECTION_COPY, advanced: true },
  {
    id: MENU_ACTION_PENDING_OPERATION_OPEN_IN_EDITOR,
    section: MENU_SECTION_VIEW,
    advanced: true,
  },
];

/**
 * Per-target action lists. The menu primitive looks up the per-target
 * list when opening; consumers do NOT pass the action list themselves
 * — they pass the target id + a handler map keyed by action id.
 */
export const MENU_ACTIONS_BY_TARGET: Readonly<
  Record<MenuTargetId, readonly MenuActionDescriptor[]>
> = {
  [MENU_TARGET_SESSION]: SESSION_ACTIONS,
  [MENU_TARGET_MESSAGE]: MESSAGE_ACTIONS,
  [MENU_TARGET_TAG]: TAG_ACTIONS,
  [MENU_TARGET_TAG_CHIP]: TAG_CHIP_ACTIONS,
  [MENU_TARGET_TOOL_CALL]: TOOL_CALL_ACTIONS,
  [MENU_TARGET_CODE_BLOCK]: CODE_BLOCK_ACTIONS,
  [MENU_TARGET_LINK]: LINK_ACTIONS,
  [MENU_TARGET_CHECKPOINT]: CHECKPOINT_ACTIONS,
  [MENU_TARGET_MULTI_SELECT]: MULTI_SELECT_ACTIONS,
  [MENU_TARGET_ATTACHMENT]: ATTACHMENT_ACTIONS,
  [MENU_TARGET_PENDING_OPERATION]: PENDING_OPERATION_ACTIONS,
} as const;

/** Convenience accessor — returns ``[]`` for an unknown target. */
export function actionsForTarget(target: MenuTargetId): readonly MenuActionDescriptor[] {
  return MENU_ACTIONS_BY_TARGET[target] ?? [];
}
