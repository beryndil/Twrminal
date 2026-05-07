<script lang="ts">
  /**
   * Auth-gate blocking modal (gap-cycle-01-007).
   *
   * Observable behavior: ``docs/behavior/chat.md`` §"Error states"
   * "Auth required / token expired":
   *
   * - When ``authStore.blocking`` is ``true``, a full-viewport modal
   *   overlays the app shell.  The modal cannot be dismissed without
   *   supplying a token — it is a hard gate.
   * - On mount (or whenever ``blocking`` becomes ``true``), the token
   *   input receives focus automatically.
   * - Submitting a non-empty token calls :func:`saveToken`; on
   *   resolution ``authStore.blocking`` is ``false`` and the modal
   *   disappears.
   *
   * Trigger wiring: this component also owns the cross-store wiring
   * between the sessions-broadcast WS status and the auth store,
   * per the architecture rule that components own cross-store
   * dependencies.  When ``wsConnectionStatus.lastCloseCode`` equals
   * :data:`WS_CLOSE_CODE_AUTH_FAILURE`, the ``$effect`` below calls
   * :func:`_setBlocking` (``true``).
   *
   * Mounted once in ``+layout.svelte`` as a ``position: fixed`` overlay
   * so it does not disturb the three-column grid layout.
   */
  import { tick } from "svelte";
  import {
    AUTH_GATE_STRINGS,
    WS_CLOSE_CODE_AUTH_FAILURE,
  } from "../../config";
  import { authStore, _setBlocking, saveToken } from "../../stores/auth.svelte";
  import { wsConnectionStatus } from "../../stores/sessions.svelte";

  /** Current value of the token input. */
  let tokenValue = $state("");

  /** Whether a :func:`saveToken` call is in-flight (disables the button). */
  let submitting = $state(false);

  /**
   * Binding to the ``<input>`` element so :func:`tick`-deferred focus
   * works without querying the DOM.
   */
  let inputEl: HTMLInputElement | null = $state(null);

  /**
   * Trigger the auth gate when the sessions-broadcast WebSocket closes
   * with code 4401.
   *
   * This ``$effect`` is the component-layer bridge that connects the
   * sessions store (which owns WS state) to the auth store (which owns
   * the blocking flag).  Keeping it here — rather than in either store
   * — preserves the "stores never subscribe to each other" rule.
   */
  $effect(() => {
    if (wsConnectionStatus.lastCloseCode === WS_CLOSE_CODE_AUTH_FAILURE) {
      _setBlocking(true);
    }
  });

  /**
   * Auto-focus the token input whenever the gate becomes visible.
   *
   * ``tick()`` defers the focus until after Svelte has flushed the DOM
   * update that inserted the ``<input>`` element.
   */
  $effect(() => {
    if (authStore.blocking) {
      void tick().then(() => {
        inputEl?.focus();
      });
    }
  });

  /**
   * Save the entered token and dismiss the gate on success.
   *
   * No-ops when the trimmed input is empty — the Submit button is also
   * disabled in that state, so this guard exists for keyboard-Enter
   * paths.
   */
  async function handleSubmit(): Promise<void> {
    if (tokenValue.trim() === "") return;
    submitting = true;
    try {
      await saveToken(tokenValue);
      tokenValue = "";
    } finally {
      submitting = false;
    }
  }
</script>

{#if authStore.blocking}
  <!-- Full-viewport overlay — sits above the three-column grid.
       role="dialog" + aria-modal="true" tells screen readers that all
       other content is inert while this overlay is open. -->
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
    data-testid="auth-gate-overlay"
    role="dialog"
    aria-modal="true"
    aria-labelledby="auth-gate-heading"
  >
    <div
      class="w-full max-w-sm rounded-lg border border-border bg-surface-1 p-6 shadow-xl"
      data-testid="auth-gate-modal"
    >
      <h2
        id="auth-gate-heading"
        class="mb-4 text-base font-semibold text-fg-strong"
        data-testid="auth-gate-heading"
      >
        {AUTH_GATE_STRINGS.heading}
      </h2>

      <label
        for="auth-gate-token-input"
        class="mb-1.5 block text-sm text-fg-muted"
        data-testid="auth-gate-label"
      >
        {AUTH_GATE_STRINGS.inputLabel}
      </label>
      <input
        id="auth-gate-token-input"
        bind:this={inputEl}
        bind:value={tokenValue}
        type="password"
        class="mb-4 w-full rounded border border-border bg-surface-0 px-3 py-2 text-sm text-fg focus:outline-none focus:ring-2 focus:ring-accent/70"
        placeholder={AUTH_GATE_STRINGS.inputPlaceholder}
        data-testid="auth-gate-input"
        autocomplete="off"
        onkeydown={(e) => {
          if (e.key === "Enter") void handleSubmit();
        }}
      />

      <button
        type="button"
        class="w-full rounded bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-muted disabled:opacity-50"
        disabled={submitting || tokenValue.trim() === ""}
        data-testid="auth-gate-submit"
        onclick={() => void handleSubmit()}
      >
        {submitting ? AUTH_GATE_STRINGS.submitting : AUTH_GATE_STRINGS.submit}
      </button>
    </div>
  </div>
{/if}
