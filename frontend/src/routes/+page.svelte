<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import AuthGate from '$lib/components/AuthGate.svelte';
  import CheatSheet from '$lib/components/CheatSheet.svelte';
  import Conversation from '$lib/components/Conversation.svelte';
  import Inspector from '$lib/components/Inspector.svelte';
  import SessionList from '$lib/components/SessionList.svelte';
  import { agent } from '$lib/agent.svelte';
  import { auth } from '$lib/stores/auth.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';

  let booted = $state(false);
  let showCheatSheet = $state(false);

  async function boot() {
    if (booted) return;
    booted = true;
    await sessions.refresh();
    if (sessions.selectedId) await agent.connect(sessions.selectedId);
  }

  onMount(async () => {
    await auth.check();
    if (auth.status === 'open' || auth.status === 'ok') await boot();
  });

  // Re-trigger once the user clears the gate.
  $effect(() => {
    if ((auth.status === 'open' || auth.status === 'ok') && !booted) boot();
  });

  // `?` toggles the cheat-sheet, but only when focus isn't in a form
  // field (so typing a literal "?" in the prompt still works). Esc
  // closes whether or not focus is in a field.
  $effect(() => {
    function onKey(e: KeyboardEvent) {
      const active = document.activeElement;
      const inField =
        active?.tagName === 'TEXTAREA' || active?.tagName === 'INPUT';
      if (e.key === '?' && !inField) {
        e.preventDefault();
        showCheatSheet = !showCheatSheet;
        return;
      }
      if (e.key === 'Escape' && showCheatSheet) {
        e.preventDefault();
        showCheatSheet = false;
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  });
</script>

<AuthGate />
<CheatSheet bind:open={showCheatSheet} />
<main class="grid h-full grid-cols-[280px_1fr_320px]">
  <SessionList />
  <Conversation />
  <Inspector />
</main>
