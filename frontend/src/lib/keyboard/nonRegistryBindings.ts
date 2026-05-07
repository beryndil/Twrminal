/**
 * Non-registry cheat-sheet sections — context-local chords that are
 * wired by individual components (composer, checklist, context menu)
 * rather than the global keybinding dispatcher.  Adding a row here
 * does NOT require touching ``bindings.ts`` or the dispatcher.
 *
 * Each entry renders identically to registry rows: an array of
 * ``<kbd>``-capped key names on the left, a descriptive label on the
 * right.  The ``id`` field is used as the ``data-section`` DOM
 * attribute so tests can query sections by identity.
 */

export interface NonRegistryBinding {
  /** Key-cap labels — each becomes a ``<kbd>`` element. */
  readonly keys: readonly string[];
  /** Descriptive label for the action. */
  readonly label: string;
}

export interface NonRegistrySection {
  /** Stable id used as the ``data-section`` attribute. */
  readonly id: string;
  /** Section heading text. */
  readonly heading: string;
  /** Rows in display order. */
  readonly bindings: readonly NonRegistryBinding[];
}

/**
 * Context-local chords surfaced in the cheat sheet so the modal is
 * a complete discovery surface.  Ordered to match the
 * ``docs/behavior/keyboard-shortcuts.md`` §"Contexts" subsection order.
 */
export const NON_REGISTRY_SECTIONS: readonly NonRegistrySection[] = [
  {
    id: "conversation",
    heading: "Conversation",
    bindings: [
      { keys: ["Enter"], label: "Send message" },
      { keys: ["Shift", "Enter"], label: "Insert newline" },
    ],
  },
  {
    id: "context_menu",
    heading: "Context menu",
    bindings: [
      { keys: ["↑", "↓"], label: "Navigate items" },
      { keys: ["Enter"], label: "Activate highlighted item" },
      { keys: ["→"], label: "Open submenu" },
      { keys: ["Esc"], label: "Close menu" },
      { keys: ["A–Z"], label: "Jump to underlined action (mnemonic)" },
    ],
  },
  {
    id: "checklist",
    heading: "Checklist",
    bindings: [
      { keys: ["Tab"], label: "Nest item under previous sibling" },
      { keys: ["Shift", "Tab"], label: "Un-nest item" },
      { keys: ["Enter"], label: "Add item (in add-item input)" },
    ],
  },
] as const;
