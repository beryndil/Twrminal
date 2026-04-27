/** Specs for the GitHub-issues feedback URL builder.
 *
 * Contract surface:
 *  - The URL points at the canonical Beryndil/Bearings repo.
 *  - The query carries a template name matching the kind ('bug.yml'
 *    / 'feature.yml') so the GitHub issue-form renderer kicks in.
 *  - The body embeds the env block (version + build + browser UA +
 *    platform + language) so triagers see the user's runtime
 *    without having to ask.
 *  - Bug and feature scaffolds carry the right headings — those
 *    headings double as the field labels in
 *    `.github/ISSUE_TEMPLATE/{bug,feature}.yml`, so a heading
 *    mismatch breaks form-rendering on GitHub's side.
 *  - URL encoding survives newlines, angle brackets, and markdown
 *    punctuation in the body. We verify the round-trip via a
 *    decoded-body assertion.
 */
import { describe, expect, it } from 'vitest';

import { buildFeedbackBody, buildFeedbackUrl, composeEnv } from './feedback';

const ENV = {
  version: '0.21.0',
  build: '1714075200000000000',
  userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
  platform: 'Linux x86_64',
  language: 'en-US'
};

describe('composeEnv', () => {
  it('falls back to "unknown" when version info is absent', () => {
    const env = composeEnv(null);
    expect(env.version).toBe('unknown');
    expect(env.build).toBeNull();
  });

  it('passes through a populated version response', () => {
    const env = composeEnv({ version: '0.99.0', build: '12345' });
    expect(env.version).toBe('0.99.0');
    expect(env.build).toBe('12345');
  });
});

describe('buildFeedbackBody', () => {
  it('embeds the env block first, with version + build + UA', () => {
    const body = buildFeedbackBody('bug', ENV);
    expect(body).toMatch(/### Environment/);
    expect(body).toMatch(/Bearings version:\*\* 0\.21\.0/);
    expect(body).toMatch(/Browser:\*\* Mozilla\/5\.0/);
    expect(body).toMatch(/Platform:\*\* Linux/);
  });

  it('formats a numeric build as ISO datetime', () => {
    const body = buildFeedbackBody('bug', ENV);
    // 1714075200000000000 ns → 1714075200000 ms → 2024-04-25T20:00:00.000Z
    expect(body).toMatch(/Build:\*\* 2024-04-25T20:00:00\.000Z/);
  });

  it('renders "dev build" when build is null', () => {
    const body = buildFeedbackBody('bug', { ...ENV, build: null });
    expect(body).toMatch(/Build:\*\* dev build/);
  });

  it('renders bug scaffold with steps-to-repro headings', () => {
    const body = buildFeedbackBody('bug', ENV);
    expect(body).toMatch(/### What happened\?/);
    expect(body).toMatch(/### Steps to reproduce/);
    expect(body).toMatch(/### Expected behavior/);
    expect(body).toMatch(/### Actual behavior/);
  });

  it('renders feature scaffold with proposed-behavior headings', () => {
    const body = buildFeedbackBody('feature', ENV);
    expect(body).toMatch(/### What problem does this solve\?/);
    expect(body).toMatch(/### Proposed behavior/);
    expect(body).toMatch(/### Alternatives considered/);
    // Bug-only headings must NOT appear in feature body.
    expect(body).not.toMatch(/### Steps to reproduce/);
  });
});

describe('buildFeedbackUrl', () => {
  it('points at Beryndil/Bearings issues/new', () => {
    const url = buildFeedbackUrl('bug', ENV);
    expect(url.startsWith('https://github.com/Beryndil/Bearings/issues/new?')).toBe(true);
  });

  it('uses bug.yml template + bug label for kind=bug', () => {
    const url = new URL(buildFeedbackUrl('bug', ENV));
    expect(url.searchParams.get('template')).toBe('bug.yml');
    expect(url.searchParams.get('labels')).toBe('bug');
  });

  it('uses feature.yml template + enhancement label for kind=feature', () => {
    const url = new URL(buildFeedbackUrl('feature', ENV));
    expect(url.searchParams.get('template')).toBe('feature.yml');
    expect(url.searchParams.get('labels')).toBe('enhancement');
  });

  it('round-trips the body through URL encoding without corruption', () => {
    const url = new URL(buildFeedbackUrl('bug', ENV));
    const decoded = url.searchParams.get('body') ?? '';
    expect(decoded).toMatch(/### Environment/);
    expect(decoded).toMatch(/### Steps to reproduce/);
    // Markdown punctuation survives.
    expect(decoded).toMatch(/<!-- One-line summary/);
  });

  it('does not embed any user paths, cwd, or session ids', () => {
    const url = buildFeedbackUrl('bug', ENV);
    // The §17 plug forbids leaking project paths or session
    // identifiers. The builder's input is just env + browser, so
    // nothing path-shaped should sneak in.
    expect(url).not.toMatch(/\/home\//);
    expect(url).not.toMatch(/working_dir/);
    expect(url).not.toMatch(/session/i);
  });
});
