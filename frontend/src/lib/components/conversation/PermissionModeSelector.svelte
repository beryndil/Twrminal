<script lang="ts">
  /**
   * Permission-mode dropdown for the conversation header (item 3.3).
   *
   * Displays the current session's ``permission_mode`` and lets the user
   * switch it mid-session. The new value is persisted immediately via
   * ``PATCH /api/sessions/{id}/permission_mode``; the runner picks it up
   * on the next turn.
   *
   * The dropdown offers the four main modes from the spec plan:
   *   default / acceptEdits / bypassPermissions / plan
   *
   * Hidden when ``sessionId`` is null (no active session).
   *
   * State source:
   *   - ``sessionsStore.sessions`` — read to get the current
   *     ``permission_mode`` for the active session; updated reactively
   *     when the sessions-broadcast WS pushes an upsert after the PATCH.
   *   - Local ``patching`` flag — suppresses the select during an
   *     in-flight request.
   */
  import {
    KNOWN_PERMISSION_MODES,
    PERMISSION_MODE_LABELS,
    PERMISSION_MODE_SELECTOR_STRINGS,
  } from "../../config";
  import { patchSessionPermissionMode } from "../../api/sessions";
  import { sessionsStore } from "../../stores/sessions.svelte";

  /** The four modes surfaced in the header dropdown (plan spec §3.3). */
  const SELECTOR_MODES = [
    "default",
    "acceptEdits",
    "bypassPermissions",
    "plan",
  ] as const satisfies readonly (typeof KNOWN_PERMISSION_MODES)[number][];

  interface Props {
    sessionId: string | null;
  }

  const { sessionId }: Props = $props();

  /** Look up the current permission_mode for the active session. */
  const currentMode = $derived(
    sessionId === null
      ? null
      : (sessionsStore.sessions.find((s) => s.id === sessionId)?.permission_mode ?? null),
  );

  /**
   * The value shown in the ``<select>``.  Defaults to ``"default"`` when
   * the session row has no ``permission_mode`` set (null → SDK default).
   */
  const selectValue = $derived(currentMode ?? "default");

  let patching = $state(false);
  let errorMsg = $state<string | null>(null);

  async function handleChange(event: Event): Promise<void> {
    if (sessionId === null) return;
    const target = event.target as HTMLSelectElement;
    const newMode = target.value === "default" ? null : target.value;
    patching = true;
    errorMsg = null;
    try {
      await patchSessionPermissionMode(sessionId, newMode);
      // The sessions-broadcast WS will merge the returned row into
      // sessionsStore — no manual update needed.
    } catch {
      errorMsg = PERMISSION_MODE_SELECTOR_STRINGS.saveError;
    } finally {
      patching = false;
    }
  }
</script>

{#if sessionId !== null}
  <div
    class="permission-mode-selector flex items-center gap-1.5 text-xs text-fg-muted"
    data-testid="permission-mode-selector"
  >
    <span class="select-none" aria-hidden="true">
      {PERMISSION_MODE_SELECTOR_STRINGS.labelPrefix}
    </span>
    <select
      class="rounded border border-border bg-surface-1 px-1.5 py-0.5 text-xs text-fg-strong
             hover:border-accent focus:outline-none focus:ring-1 focus:ring-accent
             disabled:opacity-50"
      aria-label={PERMISSION_MODE_SELECTOR_STRINGS.ariaLabel}
      data-testid="permission-mode-select"
      disabled={patching}
      value={selectValue}
      onchange={handleChange}
    >
      {#each SELECTOR_MODES as mode (mode)}
        <option value={mode}>{PERMISSION_MODE_LABELS[mode]}</option>
      {/each}
    </select>
    {#if errorMsg !== null}
      <span class="text-red-400" data-testid="permission-mode-error" role="alert">
        {errorMsg}
      </span>
    {/if}
  </div>
{/if}
