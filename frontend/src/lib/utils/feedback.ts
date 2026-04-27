/**
 * GitHub-issues feedback URL builder.
 *
 * Builds a `https://github.com/Beryndil/Bearings/issues/new?...`
 * URL with a prefilled body so the operator can file a bug report or
 * feature request from inside the app. The button only opens the URL
 * — Bearings never POSTs the report anywhere itself, so no telemetry,
 * no analytics, no user-data exfiltration. The user sees the GitHub
 * compose form and submits manually.
 *
 * Two flavors:
 *   - `bug`     → uses `bug.yml` issue-form template; body carries
 *                 environment + steps-to-reproduce / expected /
 *                 actual scaffolding.
 *   - `feature` → uses `feature.yml` template; body carries
 *                 problem / proposed-behavior / alternatives
 *                 scaffolding.
 *
 * Environment fields (version, build, browser UA, OS hint) are
 * included in the body so a maintainer triaging the report has the
 * minimum context. Everything in the body is information the operator
 * can already see in the app — no project paths, no cwd, no session
 * ids. The §17 standards plug explicitly forbids leaking those.
 *
 * The actual `.github/ISSUE_TEMPLATE/*.yml` files live at the repo
 * root and define the structured sections that GitHub renders. The
 * body prefill targets the same section labels so the rendered form
 * fields land pre-filled when the user hits the URL.
 */

const REPO_URL = 'https://github.com/Beryndil/Bearings';
const ISSUES_NEW_URL = `${REPO_URL}/issues/new`;

export type FeedbackKind = 'bug' | 'feature';

/** Snapshot of the runtime that the feedback body embeds. Captured at
 * click time so the report reflects the user's actual session, not
 * stale data from a previous mount. */
export interface FeedbackEnv {
  /** Bearings package version (e.g. "0.21.0") or "unknown" if
   * `/api/version` is unreachable. */
  version: string;
  /** Build identifier (mtime) or `null` for dev builds / fetch
   * failures. Surfaces in the report so a maintainer can map the
   * report to a specific frontend bundle. */
  build: string | null;
  /** Raw `navigator.userAgent` string. The maintainer needs this to
   * reproduce browser-specific issues; it's the same string every
   * site Dave visits already sees, so no new exposure. */
  userAgent: string;
  /** OS hint — `navigator.platform` is deprecated but still widely
   * populated; we fall back to "unknown" if it's missing. */
  platform: string;
  /** Preferred language (`navigator.language`) — useful for i18n bug
   * triage once Bearings ships translations. */
  language: string;
}

/** Read environment fields from `navigator` / `window`. Returns safe
 * defaults when called in SSR or a stripped-down test environment. */
export function readBrowserEnv(): Pick<FeedbackEnv, 'userAgent' | 'platform' | 'language'> {
  if (typeof navigator === 'undefined') {
    return { userAgent: 'unknown', platform: 'unknown', language: 'unknown' };
  }
  return {
    userAgent: navigator.userAgent || 'unknown',
    platform: navigator.platform || 'unknown',
    language: navigator.language || 'unknown'
  };
}

/** Compose a `FeedbackEnv` from a `/api/version` response (which may
 * be `null` if the fetch failed) plus the live browser env. */
export function composeEnv(
  versionInfo: { version: string; build: string | null } | null
): FeedbackEnv {
  const browser = readBrowserEnv();
  return {
    version: versionInfo?.version ?? 'unknown',
    build: versionInfo?.build ?? null,
    ...browser
  };
}

/** Format the build token (nanosecond mtime as a string) into a
 * human-friendly local datetime. Mirrors `AboutSection.formatBuild`
 * so the value the operator sees in Settings > About matches what
 * lands in their issue body. `null` → "dev build". */
function formatBuild(build: string | null): string {
  if (build === null) return 'dev build';
  const ns = Number(build);
  if (!Number.isFinite(ns) || ns <= 0) return 'unknown';
  const ms = Math.floor(ns / 1_000_000);
  return new Date(ms).toISOString();
}

/** Render the environment block as a markdown table. Goes at the top
 * of the body so it's the first thing visible in the rendered issue
 * after the user submits. */
function renderEnvBlock(env: FeedbackEnv): string {
  return [
    '### Environment',
    '',
    `- **Bearings version:** ${env.version}`,
    `- **Build:** ${formatBuild(env.build)}`,
    `- **Browser:** ${env.userAgent}`,
    `- **Platform:** ${env.platform}`,
    `- **Language:** ${env.language}`
  ].join('\n');
}

/** Bug-report scaffold. Section headings match the field labels in
 * `.github/ISSUE_TEMPLATE/bug.yml` so GitHub's issue-form rendering
 * lands them in the right slots. */
function renderBugScaffold(): string {
  return [
    '### What happened?',
    '',
    '<!-- One-line summary of the bug. -->',
    '',
    '### Steps to reproduce',
    '',
    '1. ',
    '2. ',
    '3. ',
    '',
    '### Expected behavior',
    '',
    '',
    '',
    '### Actual behavior',
    '',
    '',
    '',
    '### Additional context',
    '',
    '<!-- Screenshots, logs, or anything else that helps. -->'
  ].join('\n');
}

/** Feature-request scaffold. Section headings match
 * `.github/ISSUE_TEMPLATE/feature.yml`. */
function renderFeatureScaffold(): string {
  return [
    '### What problem does this solve?',
    '',
    '<!-- The user-facing pain point. Why does this need to exist? -->',
    '',
    '### Proposed behavior',
    '',
    '<!-- How would the feature work from the operator perspective? -->',
    '',
    '### Alternatives considered',
    '',
    '<!-- Other approaches you weighed and why they fell short. -->',
    '',
    '### Additional context',
    '',
    '<!-- Mock-ups, related issues, anything that helps. -->'
  ].join('\n');
}

/** Compose the full markdown body for a feedback issue. Env block
 * first (always), scaffold next (varies by kind). */
export function buildFeedbackBody(kind: FeedbackKind, env: FeedbackEnv): string {
  const scaffold = kind === 'bug' ? renderBugScaffold() : renderFeatureScaffold();
  return `${renderEnvBlock(env)}\n\n${scaffold}\n`;
}

/** Build the full GitHub `/issues/new` URL with the prefilled body
 * encoded as a query parameter. Caller is responsible for opening it
 * (window.open or `<a href>` with `target="_blank"`). */
export function buildFeedbackUrl(kind: FeedbackKind, env: FeedbackEnv): string {
  const template = kind === 'bug' ? 'bug.yml' : 'feature.yml';
  const labels = kind === 'bug' ? 'bug' : 'enhancement';
  const body = buildFeedbackBody(kind, env);
  // URLSearchParams handles the percent-encoding correctly for the
  // body's newlines, markdown punctuation, and angle brackets.
  const params = new URLSearchParams({
    template,
    labels,
    body
  });
  return `${ISSUES_NEW_URL}?${params.toString()}`;
}
