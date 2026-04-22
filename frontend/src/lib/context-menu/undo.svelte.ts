/**
 * Undo-toast queue store.
 *
 * Capped at 3 visible toasts (plan §6.8). When a fourth arrives the
 * oldest is evicted. Each toast auto-expires after its own
 * `windowMs` (default 30000) — matches the existing
 * `ReorgUndoToast` feel so this queue can eventually absorb reorg
 * undos without a visual change.
 *
 * Time source is injectable for tests. The production runtime uses
 * `setTimeout` / `clearTimeout`; tests substitute vitest's fake
 * timers via `undoStore._setTimeSource(...)`.
 */

export const DEFAULT_WINDOW_MS = 30_000;
export const MAX_VISIBLE = 3;

/** A single undo entry in the queue. `id` is assigned by the store. */
export type UndoItem = {
  id: number;
  /** Primary line shown in the toast. */
  message: string;
  /** Optional second-line detail (e.g. reorg warnings). */
  detail?: string;
  /** Milliseconds this toast stays on screen before auto-dismiss. */
  windowMs: number;
  /** The inverse operation. The toast's Undo button awaits this
   * before dismissing — errors bubble out as the returned promise
   * rejects. Callers catch and report as they see fit. */
  inverse: () => void | Promise<void>;
};

/** What callers pass to `push`. The store fills in `id` and `windowMs`. */
export type UndoInput = Omit<UndoItem, 'id' | 'windowMs'> & {
  windowMs?: number;
};

type Timer = ReturnType<typeof setTimeout>;

type TimeSource = {
  set: (fn: () => void, ms: number) => Timer;
  clear: (t: Timer) => void;
};

const realTime: TimeSource = {
  set: (fn, ms) => setTimeout(fn, ms),
  clear: (t) => clearTimeout(t)
};

class UndoStore {
  items = $state<UndoItem[]>([]);
  private timers = new Map<number, Timer>();
  private nextId = 1;
  private time: TimeSource = realTime;

  /** Enqueue a new undo toast. Returns the assigned id so callers
   * can dismiss programmatically if they want. */
  push(input: UndoInput): number {
    const id = this.nextId++;
    const windowMs = input.windowMs ?? DEFAULT_WINDOW_MS;
    const item: UndoItem = { ...input, id, windowMs };
    const next = [...this.items, item];
    // Evict the oldest when we exceed cap. The evicted timer is
    // cleared so a zombie expiry doesn't mutate state later.
    while (next.length > MAX_VISIBLE) {
      const victim = next.shift();
      if (victim) this.clearTimer(victim.id);
    }
    this.items = next;
    this.arm(id, windowMs);
    return id;
  }

  /** User clicked Undo. Awaits the inverse, then dismisses. */
  async invoke(id: number): Promise<void> {
    const item = this.items.find((x) => x.id === id);
    if (!item) return;
    this.clearTimer(id);
    // Remove the item before running the inverse so repeated clicks
    // can't double-trigger — matches the spec's "Undo is single-shot"
    // expectation.
    this.items = this.items.filter((x) => x.id !== id);
    try {
      await item.inverse();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('[undo] inverse threw', id, err);
    }
  }

  /** User clicked dismiss, or the timer expired. */
  dismiss(id: number): void {
    this.clearTimer(id);
    this.items = this.items.filter((x) => x.id !== id);
  }

  /** Clear all toasts without running their inverses. Used on
   * navigate-away flows where the old undos are irrelevant. */
  clear(): void {
    for (const t of this.timers.values()) this.time.clear(t);
    this.timers.clear();
    this.items = [];
  }

  /** Test-only: swap the time source. Pass `null` to restore
   * real timers. */
  _setTimeSource(src: TimeSource | null): void {
    this.time = src ?? realTime;
  }

  _resetForTests(): void {
    this.clear();
    this.nextId = 1;
  }

  private arm(id: number, ms: number): void {
    const timer = this.time.set(() => this.dismiss(id), ms);
    this.timers.set(id, timer);
  }

  private clearTimer(id: number): void {
    const t = this.timers.get(id);
    if (t !== undefined) {
      this.time.clear(t);
      this.timers.delete(id);
    }
  }
}

export const undoStore = new UndoStore();
