/**
 * Feedback URL builder and lazy version fetcher (gap-cycle-01-008).
 *
 * Provides :func:`openFeedbackTab` — the single entry point called by
 * :component:`FeedbackButton` (in the conversation header) and the
 * Help section of the Settings page.  All other exports are public
 * for unit-testing only.
 *
 * Design decisions:
 * - Version is fetched lazily on the **first click**, not on mount, to
 *   avoid a cold-path network round-trip on every conversation load.
 * - The fetch promise is cached at module scope so a second click
 *   reuses the resolved value without issuing a second request.
 * - On fetch failure the version falls back to ``"unknown"`` so the
 *   link still opens rather than silently failing.
 * - Bearings does not POST any data; the browser opens the GitHub
 *   ``issues/new`` form and the user submits manually (Beryndil
 *   standards §17).
 * - ``FeedbackKind`` discriminates bug reports from feature requests
 *   so each path can supply a kind-appropriate body scaffold and the
 *   correct ``labels`` query param (gap-cycle-07-004).
 */
import { getJson } from "../api/client";
import { API_DIAG_SERVER_ENDPOINT, FEEDBACK_GITHUB_ISSUES_URL } from "../config";

/**
 * Discriminator for the two GitHub issue kinds Bearings can open.
 *
 * - ``"bug"`` — pre-fills a steps-to-reproduce scaffold and
 *   ``labels=bug``.
 * - ``"feature"`` — pre-fills a use-case / proposed-behavior scaffold
 *   and ``labels=feature``.
 */
export type FeedbackKind = "bug" | "feature";

/** Subset of ``ServerDiagOut`` that :func:`fetchVersion` reads. */
interface DiagServerOut {
  version: string;
}

/** Module-level promise cache — null until first :func:`fetchVersion` call. */
let _versionPromise: Promise<string> | null = null;

/**
 * Reset the cached version promise between tests.  Not part of the
 * public surface — exported for vitest only.
 */
export function _resetVersionCacheForTests(): void {
  _versionPromise = null;
}

/**
 * Return a promise that resolves to the Bearings server version string.
 *
 * The first call initiates ``GET /api/diag/server``; subsequent calls
 * return the same cached promise without issuing a new request.  On
 * network or parse failure the promise resolves to ``"unknown"`` rather
 * than rejecting, so callers do not need a catch branch.
 */
export function fetchVersion(): Promise<string> {
  if (_versionPromise === null) {
    _versionPromise = getJson<DiagServerOut>(API_DIAG_SERVER_ENDPOINT)
      .then((diag) => diag.version)
      .catch(() => "unknown");
  }
  return _versionPromise;
}

/**
 * Compose a GitHub ``issues/new`` URL pre-filled with the operator's
 * environment.
 *
 * Included fields (both kinds):
 * - Bearings version (resolved by the caller from :func:`fetchVersion`)
 * - Browser user-agent (``navigator.userAgent``)
 * - Platform (``navigator.platform``)
 * - Language (``navigator.language``)
 *
 * The body scaffold differs by kind:
 * - ``"bug"`` — steps-to-reproduce, expected vs. actual behavior.
 * - ``"feature"`` — use case, proposed behavior, alternatives.
 *
 * The ``labels`` query param is ``"bug"`` or ``"feature"`` to match.
 *
 * The ``URLSearchParams`` encoding uses ``+`` for spaces and ``%XX``
 * for special characters — accepted as-is by GitHub's issue form.
 */
export function buildFeedbackUrl(kind: FeedbackKind, version: string): string {
  const header = [
    `**Bearings version:** ${version}`,
    `**Browser:** ${navigator.userAgent}`,
    `**Platform:** ${navigator.platform}`,
    `**Language:** ${navigator.language}`,
    "",
  ].join("\n");

  const scaffold =
    kind === "bug"
      ? [
          "## Steps to reproduce",
          "",
          "1. ",
          "2. ",
          "3. ",
          "",
          "## Expected behavior",
          "",
          "",
          "## Actual behavior",
          "",
        ].join("\n")
      : [
          "## Use case",
          "",
          "",
          "## Proposed behavior",
          "",
          "",
          "## Alternatives considered",
          "",
        ].join("\n");

  const body = header + scaffold;
  const params = new URLSearchParams({ title: "", body, labels: kind });
  return `${FEEDBACK_GITHUB_ISSUES_URL}?${params.toString()}`;
}

/**
 * Fetch the server version lazily, compose the feedback URL, and open
 * it in a new tab.  Called by :component:`FeedbackButton` (conversation
 * header, always ``"bug"``) and by the Settings Help section buttons.
 *
 * ``window.open`` is used with the ``"noopener"`` window-feature flag
 * so the opened tab cannot access the opener's browsing context.
 *
 * @param kind - ``"bug"`` (default) or ``"feature"``.  Selects the
 *   body scaffold and the ``labels`` query param.
 */
export async function openFeedbackTab(kind: FeedbackKind = "bug"): Promise<void> {
  const version = await fetchVersion();
  const url = buildFeedbackUrl(kind, version);
  window.open(url, "_blank", "noopener");
}
