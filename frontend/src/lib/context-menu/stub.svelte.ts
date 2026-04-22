/**
 * Stub-toast store.
 *
 * Per plan §6.6 and decision §2.3, an action with a route that exists
 * but returns 501 surfaces a "not yet implemented" toast. Kept
 * separate from the undo queue so a stub message never displaces a
 * real undo, and vice versa.
 *
 * These toasts are informational; they do not carry an inverse
 * handler. Default auto-dismiss is 4 seconds — long enough to read,
 * short enough that they don't stack when a user mashes buttons.
 */

export const STUB_DEFAULT_WINDOW_MS = 4_000;
export const STUB_MAX_VISIBLE = 3;

export type StubItem = {
  id: number;
  /** Stable action ID that triggered the stub. Used as the toast's
   * leading mono-font tag so the user sees which button they hit. */
  actionId: string;
  /** Optional human-readable amplification. Falls back to a generic
   * "Not yet implemented" line when omitted. */
  reason?: string;
  windowMs: number;
};

export type StubInput = Omit<StubItem, 'id' | 'windowMs'> & {
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

class StubStore {
  items = $state<StubItem[]>([]);
  private timers = new Map<number, Timer>();
  private nextId = 1;
  private time: TimeSource = realTime;

  /**
   * Push a new stub toast. Deduplicates by `actionId` — rapid
   * repeated clicks on the same stub button should reset the timer
   * on the existing toast rather than stack five identical rows.
   */
  show(input: StubInput): number {
    const existing = this.items.find((x) => x.actionId === input.actionId);
    if (existing) {
      this.clearTimer(existing.id);
      this.arm(existing.id, existing.windowMs);
      return existing.id;
    }
    const id = this.nextId++;
    const windowMs = input.windowMs ?? STUB_DEFAULT_WINDOW_MS;
    const item: StubItem = { ...input, id, windowMs };
    const next = [...this.items, item];
    while (next.length > STUB_MAX_VISIBLE) {
      const victim = next.shift();
      if (victim) this.clearTimer(victim.id);
    }
    this.items = next;
    this.arm(id, windowMs);
    return id;
  }

  dismiss(id: number): void {
    this.clearTimer(id);
    this.items = this.items.filter((x) => x.id !== id);
  }

  clear(): void {
    for (const t of this.timers.values()) this.time.clear(t);
    this.timers.clear();
    this.items = [];
  }

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

export const stubStore = new StubStore();

/** Convenience alias matching plan §6.6 name. Call this when a
 * handler's POST comes back 501, or when a disabled-with-tooltip
 * item would otherwise confuse the user. */
export function notYetImplemented(actionId: string, reason?: string): void {
  stubStore.show({ actionId, reason });
}
