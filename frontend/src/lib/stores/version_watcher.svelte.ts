/**
 * Seamless-reload watcher.
 *
 * Polls `/api/version` on a cadence. On boot it pins the live token as
 * the SPA's identity (`myBuild`); subsequent polls compare the live
 * `serverBuild` against that pin. When they diverge — meaning the
 * operator ran `npm run build` while the SPA was running — the
 * watcher arms a reload and fires it the moment the user pauses
 * interacting, gated by the disruption guards.
 *
 * The reload triggers, in order of preference:
 *
 *   1. `visibilitychange` to hidden — the user just switched tabs or
 *      windows. They aren't looking. Reload silently and they'll be
 *      on the new bundle the moment they look back. Zero disruption,
 *      zero notification.
 *   2. Brief interactivity-debounce while visible — armed reload
 *      fires once the user has paused keyboard / pointer / scroll
 *      activity for IDLE_DEBOUNCE_MS, AND the disruption guards are
 *      clear. This is the active-tab path: a Bearings user who keeps
 *      the tab foreground all day still lands on the new bundle
 *      within seconds of their next natural pause.
 *   3. (future) WS reconnect carrying a new build token — fast path
 *      after a server bounce. Wired separately in `ws_sessions`.
 *
 * Disruption guards (configured by the consumer; default to "always
 * safe" for unit tests):
 *
 *   - We never reload while the agent is actively streaming a turn
 *     on the focused session.
 *   - We never reload while a modal is open (when the consumer wires
 *     `isModalOpen`).
 *   - We never reload while the composer holds non-empty draft text
 *     (when the consumer wires `hasComposerDraft`). Drafts are
 *     localStorage-persisted by `drafts.svelte`, so this is belt-
 *     and-suspenders — even if a reload landed mid-typing, the draft
 *     would re-hydrate.
 *
 * Why a short debounce instead of a long idle wait. An older policy
 * required ~10 minutes of no activity before the visible-tab branch
 * would fire; for an active Bearings user that window almost never
 * arrived, so a freshly-built bundle never reached them without a
 * manual reload — defeating the whole point of the watcher. The
 * disruption guards above already cover the actual hazards (mid-
 * stream, mid-typing, modal); a short interactivity debounce just
 * adds "don't reload mid-click" on top.
 *
 * Public API:
 *
 *   - `versionWatcher.init()` — call once on boot. Pins myBuild,
 *     starts the poll, wires the visibility / interactivity hooks.
 *   - `versionWatcher.markActivity()` — bump the activity clock.
 *     Called automatically by the document-level keydown / pointer /
 *     scroll listeners installed by `init()`; consumers can also
 *     call it explicitly to extend the debounce on programmatic
 *     activity (e.g. a route change with no user input).
 *   - `versionWatcher.dispose()` — tear down (test-only).
 */

import { fetchVersion } from '$lib/api/version';

const POLL_INTERVAL_MS = 60_000;
/** How long the watcher waits, while visible, with no user activity
 * before firing an armed reload. Five seconds is short enough that a
 * natural pause (finished reading a response, finished a click) lets
 * the bundle land within seconds, and long enough that an in-flight
 * click stream or rapid keypresses don't get yanked out from under
 * the user. The disruption guards (streaming / modal / draft) cover
 * the data-loss hazards; this debounce just covers the "don't reload
 * mid-action" UX hazard. */
const IDLE_DEBOUNCE_MS = 5_000;
/** How often the idle sweep checks whether the debounce has elapsed.
 * One second gives sub-debounce granularity without burning CPU —
 * the body is one date subtract and a few function calls per tick. */
const IDLE_SWEEP_INTERVAL_MS = 1_000;
/** Document events that count as user interactivity for the debounce.
 * Keyboard + pointer + scroll covers the common cases (typing,
 * clicking, reading-with-scroll); pointermove is intentionally NOT
 * included because cursor drift while reading is not meaningful
 * activity and would defeat the debounce entirely. */
const ACTIVITY_EVENTS = ['keydown', 'pointerdown', 'wheel', 'scroll'] as const;

type ActivityCheck = () => boolean;

class VersionWatcher {
  /** The bundle the SPA was loaded against. Pinned once on boot from
   * the first /api/version response, then never overwritten. Mutating
   * this would defeat the whole watcher — `wantsReload` would always
   * read false because we'd keep updating the pin to match the
   * server. */
  myBuild = $state<string | null>(null);

  /** The bundle the server is currently advertising. Updated by every
   * poll (and, in a future pass, by version frames on the WS
   * handshake). When this diverges from `myBuild`, the SPA is stale. */
  serverBuild = $state<string | null>(null);

  /** The human-readable release string the server advertises. Updated
   * alongside `serverBuild` on every poll so chrome surfaces (the
   * StatusBar version label) reflect a server-side version bump
   * without waiting for the seamless-reload to land — useful for the
   * brief window where the server's already on v1.0.1 but the user's
   * SPA hasn't rebooted yet, so they at least see "Bearings v1.0.1"
   * instead of a stale "v1.0.0". */
  version = $state<string | null>(null);

  /** Wall-clock of the last user activity ping. The visible-tab
   * reload waits for this to age past IDLE_DEBOUNCE_MS before firing.
   * Initialized to "now" on boot so the first debounce window starts
   * fresh. */
  private lastActivityAt = Date.now();

  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private idleTimer: ReturnType<typeof setInterval> | null = null;
  private visibilityHandler: (() => void) | null = null;
  private activityHandler: (() => void) | null = null;

  /** Latched true after a reload has been attempted. Stops the idle
   * sweep from re-firing every tick while the page is in the middle
   * of unloading — and guards against pathological cases where
   * `location.reload()` is suppressed (e.g. a `beforeunload` handler
   * blocking, browser intervention) so we don't spin at 1 Hz. */
  private reloadAttempted = false;

  /** Caller-supplied predicates for the disruption guards. Held as
   * functions rather than reactive reads so the watcher stays
   * framework-agnostic — tests inject simple bool returners; the
   * production wiring closes over the agent + drafts stores. Defaults
   * are "always safe" so a watcher created without explicit guards
   * still works (used by the unit tests). */
  private isAgentStreaming: ActivityCheck = () => false;
  private isModalOpen: ActivityCheck = () => false;
  private hasComposerDraft: ActivityCheck = () => false;

  /** True when the SPA's pin disagrees with the server's advertised
   * build. Both sides must be non-null — a `null` build means "dev
   * environment, bundle directory absent" and we never reload from
   * that. */
  get wantsReload(): boolean {
    if (this.myBuild === null) return false;
    if (this.serverBuild === null) return false;
    return this.myBuild !== this.serverBuild;
  }

  /** Configure the disruption guards. Call before `init()`. */
  configure(opts: {
    isAgentStreaming?: ActivityCheck;
    isModalOpen?: ActivityCheck;
    hasComposerDraft?: ActivityCheck;
  }): void {
    if (opts.isAgentStreaming) this.isAgentStreaming = opts.isAgentStreaming;
    if (opts.isModalOpen) this.isModalOpen = opts.isModalOpen;
    if (opts.hasComposerDraft) this.hasComposerDraft = opts.hasComposerDraft;
  }

  async init(): Promise<void> {
    if (this.myBuild !== null) return; // idempotent — second call is a no-op
    try {
      const v = await fetchVersion();
      this.myBuild = v.build;
      this.serverBuild = v.build;
      this.version = v.version;
    } catch {
      // First-call failure: leave myBuild null. The watcher stays
      // dormant (`wantsReload` returns false on null pin) until the
      // next successful poll lands a value. Don't surface the error
      // to the user — this is a background concern.
    }
    this.startPoll();
    this.installVisibilityHandler();
    this.installInteractivityHandler();
    this.startIdleSweep();
  }

  /** Bump the activity clock — the visible-tab reload waits
   * IDLE_DEBOUNCE_MS past this before firing. Called automatically by
   * the document-level keydown / pointerdown / wheel / scroll
   * listeners installed by `init()`, by `visibilitychange → visible`,
   * and by any consumer that wants to extend the debounce on
   * programmatic activity (e.g. a route change with no user input). */
  markActivity(): void {
    this.lastActivityAt = Date.now();
  }

  dispose(): void {
    if (this.pollTimer !== null) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    if (this.idleTimer !== null) {
      clearInterval(this.idleTimer);
      this.idleTimer = null;
    }
    if (this.visibilityHandler && typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', this.visibilityHandler);
      this.visibilityHandler = null;
    }
    if (this.activityHandler && typeof document !== 'undefined') {
      for (const ev of ACTIVITY_EVENTS) {
        document.removeEventListener(ev, this.activityHandler, true);
      }
      this.activityHandler = null;
    }
  }

  /** Test seam: invoked directly by unit tests so they don't have to
   * wait out the poll interval. Production code paths go through the
   * timer set up in `startPoll`. */
  async pollOnce(): Promise<void> {
    try {
      const v = await fetchVersion();
      this.serverBuild = v.build;
      this.version = v.version;
    } catch {
      // Transient failure — keep last known serverBuild rather than
      // forgetting it. Same discipline as the running-poll fix
      // (commit ed9f043).
    }
  }

  /** Test seam: directly invoke the reload-attempt path. Production
   * paths fire from the visibility handler or the idle sweep. The
   * actual `location.reload()` is delegated through `reloadImpl` so
   * tests can assert "we tried to reload" without actually reloading
   * the test runner. */
  attemptReload(reloadImpl: () => void = () => location.reload()): boolean {
    if (this.reloadAttempted) return false;
    if (!this.wantsReload) return false;
    if (this.isAgentStreaming()) return false;
    if (this.isModalOpen()) return false;
    if (this.hasComposerDraft()) return false;
    this.reloadAttempted = true;
    reloadImpl();
    return true;
  }

  private startPoll(): void {
    if (this.pollTimer !== null) return;
    this.pollTimer = setInterval(() => {
      void this.pollOnce();
    }, POLL_INTERVAL_MS);
  }

  private installVisibilityHandler(): void {
    if (typeof document === 'undefined') return;
    this.visibilityHandler = () => {
      if (document.visibilityState === 'hidden') {
        // Don't bother with the disruption guards on hidden — the user
        // isn't looking. Streaming will reconnect on the new bundle's
        // boot path; modal state has no practical user impact when the
        // tab is invisible; composer drafts already persist.
        if (this.wantsReload && !this.reloadAttempted) {
          this.reloadAttempted = true;
          location.reload();
        }
      } else {
        // Becoming visible counts as activity; reset the idle clock so
        // a user who's been actively switching tabs doesn't get an
        // immediate idle-fire on focus.
        this.markActivity();
      }
    };
    document.addEventListener('visibilitychange', this.visibilityHandler);
  }

  /** Wire document-level activity events to `markActivity` so the
   * debounce reflects real user interaction rather than just wall-
   * clock since boot. Capture-phase + passive so we never interfere
   * with downstream handlers. The hidden-tab branch doesn't need
   * this — it reloads unconditionally on visibilitychange. */
  private installInteractivityHandler(): void {
    if (typeof document === 'undefined') return;
    this.activityHandler = () => this.markActivity();
    for (const ev of ACTIVITY_EVENTS) {
      document.addEventListener(ev, this.activityHandler, {
        capture: true,
        passive: true,
      });
    }
  }

  private startIdleSweep(): void {
    if (this.idleTimer !== null) return;
    // Tick every IDLE_SWEEP_INTERVAL_MS so the "user just paused"
    // case lands within ~1 s of crossing the debounce threshold.
    // Body is one date subtract + a few function calls — cheap enough
    // to run at 1 Hz without showing up in any profile.
    this.idleTimer = setInterval(() => {
      if (typeof document === 'undefined') return;
      if (document.visibilityState !== 'visible') return; // visibility branch handles this
      if (!this.wantsReload) return;
      const elapsed = Date.now() - this.lastActivityAt;
      if (elapsed < IDLE_DEBOUNCE_MS) return;
      this.attemptReload();
    }, IDLE_SWEEP_INTERVAL_MS);
  }
}

export const versionWatcher = new VersionWatcher();
// Exported class so tests can build their own instance with injected
// guards and direct timer control.
export { VersionWatcher };
