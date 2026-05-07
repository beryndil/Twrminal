/**
 * App-level configuration helpers fetched lazily from
 * ``GET /api/diag/server`` (gap-cycle-01-017).
 *
 * Provides :func:`fetchBillingMode` — the single entry point for
 * determining whether the Bearings instance is running in PAYG or
 * subscription billing mode. The promise is cached at module scope so
 * repeated calls (e.g. per session switch) issue only one network round-trip.
 *
 * Design decisions:
 * - Fetches lazily on first call (not at module load) to avoid a cold-path
 *   network round-trip until a consumer actually needs the mode.
 * - On fetch failure falls back to ``"payg"`` — the default billing mode —
 *   so the dollar-figure display remains visible rather than silently
 *   swapping to the token meter.
 * - :func:`_resetBillingModeCacheForTests` is exported for vitest only; it
 *   must not be called in production code paths.
 */
import { getJson } from "../api/client";
import { API_DIAG_SERVER_ENDPOINT } from "../config";

/** Wire type supported by :func:`fetchBillingMode`. */
export type BillingMode = "payg" | "subscription";

/** Subset of ``ServerDiagOut`` consumed by this module. */
interface DiagServerBillingOut {
  billing_mode: BillingMode;
}

/** Module-level cache — ``null`` until the first :func:`fetchBillingMode` call. */
let _billingModePromise: Promise<BillingMode> | null = null;

/**
 * Reset the cached billing-mode promise between tests.
 *
 * Not part of the public production surface — exported for vitest only.
 */
export function _resetBillingModeCacheForTests(): void {
  _billingModePromise = null;
}

/**
 * Return a promise that resolves to the server's configured billing mode.
 *
 * The first call initiates ``GET /api/diag/server``; subsequent calls
 * return the same cached promise without issuing a new request. On network
 * or parse failure the promise resolves to ``"payg"`` (safe default — keeps
 * the dollar figure visible rather than switching to the token meter with
 * no data).
 */
export function fetchBillingMode(): Promise<BillingMode> {
  if (_billingModePromise === null) {
    _billingModePromise = getJson<DiagServerBillingOut>(API_DIAG_SERVER_ENDPOINT)
      .then((diag) => diag.billing_mode)
      .catch(() => "payg" as BillingMode);
  }
  return _billingModePromise;
}
