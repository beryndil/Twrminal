/**
 * Reduced-motion helpers for imperative scroll calls.
 *
 * The CSS-side guard in `app.css` overrides
 * `transition-duration` / `animation-duration` / `scroll-behavior`
 * under `@media (prefers-reduced-motion: reduce)`, which covers every
 * declarative motion in the codebase. JS-driven scrolls
 * (`Element.scrollIntoView`, `Element.scrollTo`) read the `behavior`
 * argument directly, not from CSS, so they need a separate gate.
 *
 * Pattern at call sites:
 *
 *     el.scrollIntoView({ behavior: scrollBehavior(), block: 'center' });
 *
 * `scrollBehavior()` returns `'auto'` (instant jump) when the user has
 * "Reduce motion" enabled, otherwise `'smooth'` — preserving the
 * default scroll feel for the majority of users while honoring the
 * accessibility preference for those who set it.
 *
 * Both helpers fail safe in SSR / non-browser environments
 * (`window`/`matchMedia` undefined) by returning `false` /
 * `'smooth'` — the assumption being that the eventual hydration
 * environment supports motion unless told otherwise. The DOM call that
 * consumes `scrollBehavior()` is itself guarded by `typeof document`
 * checks at every existing call site, so SSR never reaches this code
 * with a real element.
 */

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

/** True when the OS reports the "Reduce motion" accessibility
 * preference. Returns `false` outside the browser (SSR, jsdom without
 * a `matchMedia` shim) so server-rendered output assumes the default
 * motion-on posture. */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false;
  }
  return window.matchMedia(REDUCED_MOTION_QUERY).matches;
}

/** Resolved `ScrollBehavior` for imperative `scrollTo` / `scrollIntoView`
 * calls. `'auto'` (instant) when reduced-motion is requested, `'smooth'`
 * otherwise. Centralized so a future change to the policy
 * (e.g. honoring a per-user preference store on top of the OS hint)
 * lands in one place. */
export function scrollBehavior(): ScrollBehavior {
  return prefersReducedMotion() ? 'auto' : 'smooth';
}
