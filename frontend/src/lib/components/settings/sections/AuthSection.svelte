<script lang="ts">
  /**
   * Authentication section — per-device auth token stored in localStorage.
   * Extracted from ``+page.svelte`` as part of gap-cycle-07-007.
   */
  import type { SaveStatus } from "../sections.js";
  import { AUTH_SECTION_STRINGS } from "$lib/config";
  import { clearToken, getStoredToken, saveToken } from "$lib/stores/auth.svelte";

  interface Props {
    onsaveStatus?: (status: SaveStatus) => void;
  }

  // Auth auto-saves on every keystroke — no explicit save button — so
  // onsaveStatus is unused but declared for registry uniformity.
  const { onsaveStatus: _onsaveStatus }: Props = $props();

  let authTokenValue = $state(getStoredToken());

  function handleAuthTokenInput(e: Event): void {
    const value = (e.target as HTMLInputElement).value;
    authTokenValue = value;
    if (value.trim() !== "") {
      void saveToken(value);
    } else {
      clearToken();
    }
  }
</script>

<section class="settings-page__group" aria-label="Authentication" data-testid="settings-auth">
  <h2 class="settings-page__heading">{AUTH_SECTION_STRINGS.heading}</h2>
  <p class="settings-page__lede">{AUTH_SECTION_STRINGS.lede}</p>
  <label class="settings-defaults__field">
    <span class="settings-defaults__label">{AUTH_SECTION_STRINGS.tokenLabel}</span>
    <input
      type="password"
      class="settings-defaults__input settings-auth__token-input"
      value={authTokenValue}
      placeholder={AUTH_SECTION_STRINGS.tokenPlaceholder}
      oninput={handleAuthTokenInput}
      data-testid="auth-token-input"
      autocomplete="off"
      spellcheck={false}
    />
  </label>
</section>

<style>
  .settings-auth__token-input {
    font-family: monospace;
  }
</style>
