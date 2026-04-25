/**
 * UI-action flags shared across the keyboard registry and the
 * components that own each overlay's render. The registry needs a way
 * to flip "open new session form" or "open template picker" without
 * pulling component refs around the tree, and components need a way
 * to read the same flag they themselves toggle. A tiny shared store
 * is the smallest thing that holds — every flag is local to the page
 * (no persistence, no server round-trip), and the registry stays
 * decoupled from component internals.
 *
 * The "fresh" flag on the new-session form is what `Shift+C` flips —
 * tells `NewSessionForm` to skip the per-open seed from the active
 * sidebar tag filter, so the user gets a blank slate. Plain `c`
 * leaves it `false` and the existing seed-from-filter path runs.
 */

class UiActions {
  /** Cheat-sheet overlay (`?` toggles, `Esc` closes). */
  cheatSheetOpen = $state(false);

  /** Inline `NewSessionForm` panel in the sidebar (`c` opens, `Esc` closes). */
  newSessionOpen = $state(false);

  /** When `true`, NewSessionForm skips the auto-seed-from-tag-filter
   * logic on its next open transition. Reset to `false` after the
   * form consumes it so a subsequent `c` press behaves normally. */
  newSessionFresh = $state(false);

  /** Sidebar template-picker dropdown (`t` opens, `Esc` closes). */
  templatePickerOpen = $state(false);

  openNewSession(opts: { fresh?: boolean } = {}): void {
    this.newSessionFresh = opts.fresh === true;
    this.newSessionOpen = true;
    // Mutually-exclusive overlays — pick one at a time so Esc has a
    // single layer to close and the sidebar doesn't render two
    // dropdowns on top of each other.
    this.templatePickerOpen = false;
    this.cheatSheetOpen = false;
  }

  toggleNewSession(opts: { fresh?: boolean } = {}): void {
    if (this.newSessionOpen) {
      this.newSessionOpen = false;
      this.newSessionFresh = false;
      return;
    }
    this.openNewSession(opts);
  }

  openTemplatePicker(): void {
    this.templatePickerOpen = true;
    this.newSessionOpen = false;
    this.cheatSheetOpen = false;
  }

  toggleTemplatePicker(): void {
    if (this.templatePickerOpen) {
      this.templatePickerOpen = false;
      return;
    }
    this.openTemplatePicker();
  }

  toggleCheatSheet(): void {
    this.cheatSheetOpen = !this.cheatSheetOpen;
  }

  /** Close every overlay this store owns. Called by the Esc handler
   * in the keyboard registry. Returns `true` when something actually
   * closed so the caller can decide whether to fall through to other
   * Esc behavior (defocusing an input, etc.). */
  dismissOverlays(): boolean {
    let closed = false;
    if (this.cheatSheetOpen) {
      this.cheatSheetOpen = false;
      closed = true;
    }
    if (this.newSessionOpen) {
      this.newSessionOpen = false;
      this.newSessionFresh = false;
      closed = true;
    }
    if (this.templatePickerOpen) {
      this.templatePickerOpen = false;
      closed = true;
    }
    return closed;
  }
}

export const uiActions = new UiActions();
