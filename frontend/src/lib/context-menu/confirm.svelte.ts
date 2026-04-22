/**
 * Destructive-action confirmation store.
 *
 * One pending request at a time. The store owns the session-scoped
 * "don't ask again" suppression set (plan §6.7). Keys are
 * `${actionId}:${targetType}` so suppressing
 * `session.delete:session` does not silently suppress
 * `message.delete:message` — each destructive target is independent.
 *
 * The set lives only in memory — page reload clears it. That matches
 * the spec's session-scope intent: it is a UX aid, never a
 * per-installation preference.
 */

export type ConfirmRequest = {
  /** Stable action ID used in the suppression key. */
  actionId: string;
  /** Target type from `ContextTarget['type']`. Keyed separately so
   * archiving sessions and deleting messages have independent
   * suppression. */
  targetType: string;
  /** Prose the dialog renders as the question. */
  message: string;
  /** Defaults to "Confirm". Destructive verbs ("Delete", "Archive")
   * read better than a generic label. */
  confirmLabel?: string;
  /** Defaults to "Cancel". */
  cancelLabel?: string;
  /** True turns the confirm button red (destructive styling). Most
   * callers of this store are destructive; this flag exists for the
   * rare non-destructive confirm (e.g. "Send this without review"). */
  destructive?: boolean;
  /** The work to run when the user confirms. If it throws, the
   * confirm dialog logs the error and closes — callers are
   * responsible for user-visible failure reporting. */
  onConfirm: () => void | Promise<void>;
};

export function suppressionKey(actionId: string, targetType: string): string {
  return `${actionId}:${targetType}`;
}

class ConfirmStore {
  /** The single in-flight request. `null` when no dialog is showing. */
  pending = $state<ConfirmRequest | null>(null);
  /** Suppression set — keys the user has checked "don't ask again"
   * on this session. Reset on reload. */
  private suppressed = $state(new Set<string>());
  /** True while `accept()` is awaiting the handler. The dialog uses
   * this to disable both buttons so double-click can't fire the
   * handler twice. */
  busy = $state(false);

  /** Is the user currently suppressing this action/target? Used by
   * callers to short-circuit before opening the dialog. */
  isSuppressed(actionId: string, targetType: string): boolean {
    return this.suppressed.has(suppressionKey(actionId, targetType));
  }

  /**
   * Ask the user to confirm. If the key is already suppressed this
   * session the handler fires immediately without a dialog — callers
   * can still treat the return value as "the confirmation flow is
   * owned by the store."
   */
  async request(req: ConfirmRequest): Promise<void> {
    if (this.isSuppressed(req.actionId, req.targetType)) {
      await runHandler(req);
      return;
    }
    this.pending = req;
  }

  /** User clicked the confirm button. `remember` toggles the
   * session-scoped "don't ask again" set. */
  async accept(remember: boolean): Promise<void> {
    const req = this.pending;
    if (!req || this.busy) return;
    this.busy = true;
    try {
      if (remember) {
        this.suppressed.add(suppressionKey(req.actionId, req.targetType));
      }
      await runHandler(req);
    } finally {
      this.busy = false;
      this.pending = null;
    }
  }

  /** User cancelled, pressed Escape, clicked backdrop. */
  dismiss(): void {
    if (this.busy) return;
    this.pending = null;
  }

  /** Test hook — resets all state. Not exported as part of the
   * runtime surface, but exposed for unit tests. */
  _resetForTests(): void {
    this.pending = null;
    this.busy = false;
    this.suppressed = new Set<string>();
  }
}

async function runHandler(req: ConfirmRequest): Promise<void> {
  try {
    await req.onConfirm();
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error('[confirm] handler threw', req.actionId, err);
  }
}

export const confirmStore = new ConfirmStore();
