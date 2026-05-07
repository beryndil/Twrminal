<script lang="ts">
  /**
   * About section — hero, identity card, coffee CTA.
   * Extracted from ``+page.svelte`` as part of gap-cycle-07-007.
   */
  import type { SaveStatus } from "../sections.js";
  import { ABOUT_SECTION_STRINGS, API_DIAG_SERVER_ENDPOINT } from "$lib/config";
  import { getJson } from "$lib/api/client";
  import { formatBuildMtime } from "$lib/utils/datetime";
  import BearingsMark from "$lib/components/icons/BearingsMark.svelte";

  interface Props {
    onsaveStatus?: (status: SaveStatus) => void;
  }

  // About is read-only — no user-initiated saves.
  const { onsaveStatus: _onsaveStatus }: Props = $props();

  interface AboutDiag {
    version: string;
    build_mtime: number | null;
  }

  let aboutVersion = $state<string | null>(null);
  let aboutBuildMtime = $state<number | null>(null);
  let aboutLoading = $state(true);

  $effect(() => {
    void loadAboutInfo();
  });

  async function loadAboutInfo(): Promise<void> {
    aboutLoading = true;
    try {
      const diag = await getJson<AboutDiag>(API_DIAG_SERVER_ENDPOINT);
      aboutVersion = diag.version;
      aboutBuildMtime = diag.build_mtime;
    } catch {
      aboutVersion = null;
      aboutBuildMtime = null;
    } finally {
      aboutLoading = false;
    }
  }
</script>

<section
  class="settings-page__group settings-about"
  aria-label="About"
  data-testid="settings-about"
>
  <h2 class="settings-page__heading">{ABOUT_SECTION_STRINGS.heading}</h2>

  <div class="settings-about__hero" data-testid="about-hero">
    <span class="settings-about__logo" data-testid="about-logo">
      <BearingsMark size={48} />
    </span>
    <p class="settings-about__product-name" data-testid="about-product-name">
      {ABOUT_SECTION_STRINGS.productName}
    </p>
    <p class="settings-about__version" data-testid="about-version">
      {#if aboutLoading}
        {ABOUT_SECTION_STRINGS.versionLoading}
      {:else if aboutVersion !== null}
        v{aboutVersion}
      {:else}
        {ABOUT_SECTION_STRINGS.versionUnavailable}
      {/if}
    </p>
    <p class="settings-about__tagline" data-testid="about-tagline">
      {ABOUT_SECTION_STRINGS.tagline}
    </p>
    <a
      class="settings-about__byline"
      href={ABOUT_SECTION_STRINGS.developerUrl}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="about-byline-link"
    >
      {ABOUT_SECTION_STRINGS.bylineLabel}
    </a>
    <img
      class="settings-about__photo"
      src="/about_beryndil.png"
      alt={ABOUT_SECTION_STRINGS.photoAlt}
      width="80"
      height="80"
      data-testid="about-photo"
    />
    <div class="settings-about__cta" data-testid="about-coffee-cta">
      <p class="settings-page__lede">{ABOUT_SECTION_STRINGS.coffeeEyebrow}</p>
      <a
        class="settings-help__action-btn settings-help__link settings-about__cta-link"
        href={ABOUT_SECTION_STRINGS.developerUrl}
        target="_blank"
        rel="noopener noreferrer"
        data-testid="about-coffee-link"
      >
        {ABOUT_SECTION_STRINGS.coffeeLabel}
      </a>
    </div>
  </div>

  <div class="settings-about__identity-card" data-testid="about-identity-card">
    <div class="settings-about__id-row" data-testid="about-build-row">
      <span class="settings-defaults__label settings-about__id-label">
        {ABOUT_SECTION_STRINGS.buildLabel}
      </span>
      <span class="settings-about__id-value" data-testid="about-build-value">
        {formatBuildMtime(aboutBuildMtime)}
      </span>
    </div>
    <div class="settings-about__id-row" data-testid="about-repository-row">
      <span class="settings-defaults__label settings-about__id-label">
        {ABOUT_SECTION_STRINGS.repositoryLabel}
      </span>
      <a
        class="settings-privacy__link"
        href={ABOUT_SECTION_STRINGS.repositoryHref}
        target="_blank"
        rel="noopener noreferrer"
        data-testid="about-repository-link"
      >
        {ABOUT_SECTION_STRINGS.repositoryLinkLabel}
      </a>
    </div>
    <div class="settings-about__id-row" data-testid="about-license-row">
      <span class="settings-defaults__label settings-about__id-label">
        {ABOUT_SECTION_STRINGS.licenseLabel}
      </span>
      <a
        class="settings-privacy__link"
        href={ABOUT_SECTION_STRINGS.licenseHref}
        target="_blank"
        rel="noopener noreferrer"
        data-testid="about-license-link"
      >
        {ABOUT_SECTION_STRINGS.licenseLinkLabel}
      </a>
    </div>
    <div class="settings-about__id-row" data-testid="about-credits-row">
      <span class="settings-defaults__label settings-about__id-label">
        {ABOUT_SECTION_STRINGS.creditsLabel}
      </span>
      <a
        class="settings-privacy__link"
        href={ABOUT_SECTION_STRINGS.creditsHref}
        target="_blank"
        rel="noopener noreferrer"
        data-testid="about-credits-link"
      >
        {ABOUT_SECTION_STRINGS.creditsLinkLabel}
      </a>
    </div>
  </div>
</section>

<style>
  .settings-about__hero {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
    padding: 1.25rem;
    background: rgb(var(--bearings-surface-2));
    border-radius: 0.5rem;
    text-align: center;
  }
  .settings-about__logo {
    display: flex;
    align-items: center;
    justify-content: center;
    color: rgb(var(--bearings-fg-strong));
  }
  .settings-about__product-name {
    font-size: 1.25rem;
    font-weight: 700;
    color: rgb(var(--bearings-fg-strong));
    margin: 0;
  }
  .settings-about__version {
    font-size: 0.8125rem;
    color: rgb(var(--bearings-fg-muted));
    margin: 0;
  }
  .settings-about__tagline {
    font-size: 0.8125rem;
    color: rgb(var(--bearings-fg-muted));
    margin: 0;
  }
  .settings-about__byline {
    font-size: 0.8125rem;
    color: rgb(var(--bearings-accent));
    text-decoration: underline;
  }
  .settings-about__byline:hover {
    opacity: 0.85;
  }
  .settings-about__photo {
    width: 5rem;
    height: 5rem;
    border-radius: 50%;
    object-fit: cover;
    margin-top: 0.25rem;
  }
  .settings-about__cta {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.375rem;
    margin-top: 0.5rem;
    padding: 0.75rem 1rem;
    background: rgb(var(--bearings-surface-1));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.375rem;
    width: 100%;
    max-width: 18rem;
  }
  .settings-about__cta-link {
    width: 100%;
    justify-content: center;
  }
  .settings-about__identity-card {
    display: flex;
    flex-direction: column;
    gap: 0;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.375rem;
    overflow: hidden;
  }
  .settings-about__id-row {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid rgb(var(--bearings-border));
  }
  .settings-about__id-row:last-child {
    border-bottom: none;
  }
  .settings-about__id-label {
    min-width: 6rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: 0.75rem;
    font-weight: 500;
    color: rgb(var(--bearings-fg-muted));
  }
  .settings-about__id-value {
    font-size: 0.8125rem;
    color: rgb(var(--bearings-fg-strong));
  }
  /* settings-privacy__link reused from PrivacySection — needs local copy
     since Svelte scopes styles per component. */
  .settings-privacy__link {
    font-size: 0.8125rem;
    color: rgb(var(--bearings-accent));
    text-decoration: underline;
  }
  .settings-privacy__link:hover {
    opacity: 0.85;
  }
  /* settings-help__action-btn reused from HelpSection — local copy. */
  .settings-help__action-btn {
    background: transparent;
    color: rgb(var(--bearings-accent));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.3rem 0.875rem;
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
  }
  .settings-help__link {
    text-decoration: none;
  }
</style>
