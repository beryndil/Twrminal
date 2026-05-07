<script lang="ts">
  /**
   * UserIdentityBlock (gap-cycle-03-011).
   *
   * Observable behavior: ``docs/behavior/preferences.md`` §"Profile / Identity".
   *
   * Renders the user's avatar and display name as a compact horizontal
   * block used in three surfaces:
   *
   * - Settings → Profile section (above Appearance).
   * - Sidebar top area (if wired by the layout).
   * - Status bar identity slot (if wired by the layout).
   *
   * When no avatar is set the block shows a circular fallback icon (a
   * person silhouette SVG) in the same size as the avatar.  When no
   * display name is set the name slot is hidden.
   *
   * Props:
   *  - ``displayName``  — the user's name string, or ``null``.
   *  - ``avatarUrl``    — URL path returned by the backend
   *    (``/api/preferences/avatar``), or ``null``.  The component
   *    appends ``?v=<cacheBust>`` to prevent browser caching of the
   *    previous image after an upload.
   *  - ``cacheBust``    — ``updated_at`` timestamp from
   *    ``PreferencesOut``; appended to ``avatarUrl`` as a query param.
   *    Defaults to empty string (no busting) when not supplied.
   *  - ``size``         — diameter in CSS units.  Defaults to "2.5rem".
   */
  import { PROFILE_STRINGS } from "../../config";

  interface Props {
    displayName: string | null;
    avatarUrl: string | null;
    cacheBust?: string;
    size?: string;
  }

  const {
    displayName,
    avatarUrl,
    cacheBust = "",
    size = "2.5rem",
  }: Props = $props();

  /** Full src attribute — appends cache-bust if an avatar is set. */
  const src: string = $derived(
    avatarUrl
      ? cacheBust
        ? `${avatarUrl}?v=${encodeURIComponent(cacheBust)}`
        : avatarUrl
      : "",
  );
</script>

<div
  class="user-identity-block"
  data-testid="user-identity-block"
  aria-label={displayName ?? PROFILE_STRINGS.avatarFallbackAriaLabel}
>
  <!-- Avatar or fallback icon -->
  <div
    class="user-identity-block__avatar"
    style:width={size}
    style:height={size}
    style:min-width={size}
  >
    {#if src}
      <img
        class="user-identity-block__img"
        {src}
        alt={PROFILE_STRINGS.avatarAlt}
        data-testid="user-identity-avatar-img"
      />
    {:else}
      <span
        class="user-identity-block__fallback"
        aria-label={PROFILE_STRINGS.avatarFallbackAriaLabel}
        data-testid="user-identity-avatar-fallback"
      >
        <!-- Simple person silhouette -->
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          aria-hidden="true"
        >
          <circle cx="12" cy="8" r="4" />
          <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" stroke-linecap="round" />
        </svg>
      </span>
    {/if}
  </div>

  <!-- Display name -->
  {#if displayName}
    <span class="user-identity-block__name" data-testid="user-identity-name">
      {displayName}
    </span>
  {/if}
</div>

<style>
  .user-identity-block {
    display: flex;
    align-items: center;
    gap: 0.625rem;
  }

  .user-identity-block__avatar {
    border-radius: 50%;
    overflow: hidden;
    flex-shrink: 0;
    background: rgb(var(--bearings-surface-2));
    display: flex;
    align-items: center;
    justify-content: center;
    color: rgb(var(--bearings-fg-muted));
  }

  .user-identity-block__img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .user-identity-block__fallback {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
  }

  .user-identity-block__fallback svg {
    width: 60%;
    height: 60%;
  }

  .user-identity-block__name {
    font-size: 0.875rem;
    font-weight: 500;
    color: rgb(var(--bearings-fg-strong));
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
