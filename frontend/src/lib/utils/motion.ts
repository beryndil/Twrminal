/**
 * Reduced-motion utilities (gap-cycle-14-001).
 *
 * Consumers:
 *  - Imperative scroll call sites pass :func:`scrollBehavior` as the
 *    ``behavior`` argument so the JS-side scroll matches the CSS-side
 *    ``@media (prefers-reduced-motion: reduce)`` guard in ``app.css``.
 *
 * Both functions are safe to call in SSR / no-``matchMedia`` environments —
 * they return the non-reduced defaults (``false`` / ``"smooth"``) when the
 * API is unavailable.
 */

/**
 * Returns ``true`` when the OS accessibility setting "Reduce motion" is
 * active.  Returns ``false`` in SSR or when ``window.matchMedia`` is absent
 * (e.g. jsdom without a polyfill).
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Returns the ``ScrollBehavior`` that should be used for imperative scroll
 * calls so they match the CSS-side reduced-motion guard.
 *
 * - ``"auto"`` when the user has "Reduce motion" enabled.
 * - ``"smooth"`` otherwise (default).
 */
export function scrollBehavior(): "auto" | "smooth" {
  return prefersReducedMotion() ? "auto" : "smooth";
}
