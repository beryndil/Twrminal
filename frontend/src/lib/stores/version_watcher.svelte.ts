/**
 * Seamless-reload watcher.
 *
 * Polls `/api/version` on a cadence. On boot it pins the live token as
 * the SPA's identity (`myBuild`); subsequent polls compare the live
 * `serverBuild` against that pin. When they diverge — meaning the
 * operator ran `npm run build` while the SPA was running — the
 * watcher arms a reload and waits for a moment that won't disrupt the
 * user.
 *
 * The reload triggers, in order of preference:
 *
 *   1. `visibilitychange` to hidden — the user just switched tabs or
 *      windows. They aren't looking. Reload silently and they'll be
 *      on the new bundle the moment they look back. This is the
 *      "99% of the time" path: zero disruption, zero notification.
 *   2. Long idle while visible — composer empty, no streaming agent,
 *      no modal. Catches the "user keeps Bearings foreground all
 *      day" case so the SPA doesn't drift forever; the actual
 *      heuristic is "no `interactiveActivity` ping for IDLE_MS."
 *   3. (future) WS reconnect carrying a new build token — fast path
 *      after a server bounce. Wired separately in `ws_sessions`.
 *
 * Disruption guards:
 *
 *   - We never reload while a modal is open (data-attribute on the
 *     modal host).
 *   - We never reload while the agent is actively streaming a turn
 *     on the focused session.
 *   - We never reload while the composer holds non-empty draft text.
 *     Drafts are localStorage-persisted by `drafts.svelte`, so this
 *     is belt-and-suspenders — even if a reload landed mid-typing,
 *     the draft would re-hydrate.
 *
 * Public API:
 *
 *   - `versionWatcher.init()` — call once on boot. Pins myBuild,
 *     starts the poll, wires the visibility/idle triggers.
 *   - `versionWatcher.markActivity()` — bump the idle clock. Hooked
 *     into composer keystrokes and route changes by the consumer.
 *   - `versionWatcher.dispose()` — tear down (test-only).
 */

import { fetchVersion } from '$lib/api/version';

const POLL_INTERVAL_MS = 60_000;
/** How long the watcher waits, while visible, with no user activity
 * before it considers the page idle and reloads if armed. Ten minutes
 * is the lower bound where Daisy is unambiguously not actively using
 * the page; shorter would surprise her, longer reduces the seamless
 * experience for users who never switch tabs. */
const IDLE_RELOAD_MS = 10 * 60_000;

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

  /** Wall-clock of the last user activity ping. Idle reload waits for
   * this to age past IDLE_RELOAD_MS before firing. Initialized to
   * "now" on boot so the first idle window starts fresh. */
  private lastActivityAt = Date.now();

  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private idleTimer: ReturnType<typeof setInterval> | null = null;
  private visibilityHandler: (() => void) | null = null;

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
    } catch {
      // First-call failure: leave myBuild null. The watcher stays
      // dormant (`wantsReload` returns false on null pin) until the
      // next successful poll lands a value. Don't surface the error
      // to the user — this is a background concern.
    }
    this.startPoll();
    this.installVisibilityHandler();
    this.startIdleSweep();
  }

  /** Bump the activity clock — idle reload waits IDLE_RELOAD_MS past
   * this before firing. Hooked into composer keystrokes / focus /
   * pointer events by the +page.svelte wiring. Also called
   * automatically on `visibilitychange` to visible. */
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
  }

  /** Test seam: invoked directly by unit tests so they don't have to
   * wait out the poll interval. Production code paths go through the
   * timer set up in `startPoll`. */
  async pollOnce(): Promise<void> {
    try {
      const v = await fetchVersion();
      this.serverBuild = v.build;
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
    if (!this.wantsReload) return false;
    if (this.isAgentStreaming()) return false;
    if (this.isModalOpen()) return false;
    if (this.hasComposerDraft()) return false;
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
        if (this.wantsReload) location.reload();
      } else {
        // Becoming visible counts as activity; reset the idle clock so
        // a user who's been actively switching tabs doesn't get an
        // immediate idle-fire on focus.
        this.markActivity();
      }
    };
    document.addEventListener('visibilitychange', this.visibilityHandler);
  }

  private startIdleSweep(): void {
    if (this.idleTimer !== null) return;
    // Check every minute; the actual idle threshold is
    // IDLE_RELOAD_MS. Cheap — one comparison + a few function calls
    // per minute, no I/O.
    this.idleTimer = setInterval(() => {
      if (typeof document === 'undefined') return;
      if (document.visibilityState !== 'visible') return; // visibility branch handles this
      const elapsed = Date.now() - this.lastActivityAt;
      if (elapsed < IDLE_RELOAD_MS) return;
      this.attemptReload();
    }, 60_000);
  }
}

export const versionWatcher = new VersionWatcher();
// Exported class so tests can build their own instance with injected
// guards and direct timer control.
export { VersionWatcher };
