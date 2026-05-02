<script lang="ts">
  /**
   * Bearings app shell.
   *
   * Three-column layout per `docs/behavior/chat.md`:
   *
   *   ┌────────────┬──────────────────────────┬────────────┐
   *   │  Sidebar   │   Main conversation pane │ Inspector  │
   *   │  (left)    │   (center)               │ (right)    │
   *   └────────────┴──────────────────────────┴────────────┘
   *
   * Each column hosts a self-contained component subtree:
   *
   * - Sidebar: ``SessionList`` (session rows + tag filter chrome).
   * - Center: ``Conversation`` (header + transcript) + ``Composer``
   *   (textarea footer); when a checklist row is selected,
   *   ``ChecklistView`` swaps in instead.
   * - Inspector: ``Inspector`` (Agent / Context / Instructions /
   *   Routing / Usage tabs).
   *
   * The visible-row selection is owned by the inspector store
   * (``$lib/stores/inspector.svelte``); URL routing
   * (``/sessions/[id]``) syncs into it on navigation so reload +
   * browser back/forward preserve the active session.
   */
  import "../app.css";
  import type { Snippet } from "svelte";

  import { page } from "$app/state";
  import { goto } from "$app/navigation";

  import { SESSION_KIND_CHECKLIST, SIDEBAR_STRINGS } from "$lib/config";
  import SessionList from "$lib/components/sidebar/SessionList.svelte";
  import Conversation from "$lib/components/conversation/Conversation.svelte";
  import Composer from "$lib/components/composer/Composer.svelte";
  import ChecklistView from "$lib/components/checklist/ChecklistView.svelte";
  import Inspector from "$lib/components/inspector/Inspector.svelte";
  import ThemeProvider from "$lib/themes/ThemeProvider.svelte";
  import KeybindingsProvider from "$lib/keyboard/KeybindingsProvider.svelte";
  import ContextMenuProvider from "$lib/context-menu/ContextMenuProvider.svelte";
  import { sessionsStore } from "$lib/stores/sessions.svelte";
  import { inspectorStore, setActiveSession } from "$lib/stores/inspector.svelte";

  interface Props {
    children?: Snippet;
  }

  const { children }: Props = $props();

  /**
   * The active session id is owned by the inspector store so the
   * sidebar (which selects), the conversation pane (which reads the
   * messages), and the inspector pane (which reads the session row)
   * all observe the same value. The local mirror below is purely for
   * the conversation prop wiring; mutation goes through
   * :func:`setActiveSession` so the store stays the source of truth.
   */
  const selectedSessionId = $derived(inspectorStore.activeSessionId);

  /**
   * Look up the active session in the sessions cache so the inspector
   * can render its row without an extra fetch. ``undefined`` (sidebar
   * has a selection but the row isn't loaded yet) is mapped to
   * ``null`` here — the inspector treats both as "render the empty
   * state" per its empty-session branch.
   */
  const activeSession = $derived(
    selectedSessionId === null
      ? null
      : (sessionsStore.sessions.find((row) => row.id === selectedSessionId) ?? null),
  );

  /**
   * Sync the store from the URL on every navigation. The
   * ``/sessions/[id]`` route file fires the same effect from its own
   * ``+page.svelte`` — wiring it here too means the empty-children
   * branches (``/``, ``/settings``, ``/memories``, ``/vault``) get
   * the store cleared back to ``null``, so the conversation pane
   * reverts to its empty state when the user navigates away from a
   * session URL.
   */
  $effect(() => {
    const routeId = page.route.id;
    const id = page.params.id;
    if (routeId === "/sessions/[id]" && typeof id === "string" && id.length > 0) {
      setActiveSession(id);
    } else {
      setActiveSession(null);
    }
  });

  /**
   * Sidebar still passes ``onSelect`` for compatibility with existing
   * tests + the future keyboard-nav surface. Activation goes through
   * SvelteKit client-nav (anchor href on the row); we mirror that here
   * via :func:`goto` so a synthetic onSelect call (or a tag-chip
   * keyboard activation that bubbled past the chip's own handler)
   * still navigates the same way.
   */
  function handleSelectSession(sessionId: string): void {
    void goto(`/sessions/${encodeURIComponent(sessionId)}`);
  }
</script>

<ThemeProvider>
  <KeybindingsProvider>
    <ContextMenuProvider>
      <div class="app-shell" data-testid="app-shell">
        <aside
          class="app-shell__sidebar border-r border-border bg-surface-1"
          data-testid="app-shell-sidebar"
          aria-label="Sessions sidebar"
        >
          <header class="app-shell__sidebar-header border-b border-border p-3">
            <h1 class="font-mono text-sm text-fg-strong">{SIDEBAR_STRINGS.heading}</h1>
            <p class="text-xs text-fg-muted">{SIDEBAR_STRINGS.versionTag}</p>
          </header>
          <div class="app-shell__sidebar-body" data-testid="app-shell-sidebar-body">
            <SessionList {selectedSessionId} onSelect={handleSelectSession} />
          </div>
        </aside>

        <main
          class="app-shell__main bg-surface-0"
          data-testid="app-shell-main"
          aria-label="Conversation pane"
        >
          <header
            class="app-shell__main-header border-b border-border p-3"
            data-testid="app-shell-main-header"
          >
            {#if activeSession !== null}
              <p class="truncate text-sm text-fg-strong" data-testid="conversation-header-title">
                {activeSession.title}
              </p>
            {/if}
          </header>
          <section
            class="app-shell__main-body text-fg"
            data-testid="app-shell-main-body"
            aria-label="Conversation body"
          >
            {#if selectedSessionId !== null && activeSession?.kind === SESSION_KIND_CHECKLIST}
              <ChecklistView
                checklistId={selectedSessionId}
                availableChats={sessionsStore.sessions.filter(
                  (row) => row.kind !== SESSION_KIND_CHECKLIST && row.closed_at === null,
                )}
                onSelectChat={handleSelectSession}
              />
            {:else if selectedSessionId !== null}
              <Conversation sessionId={selectedSessionId} />
            {:else if children}
              {@render children()}
            {:else}
              <p class="p-4 text-fg-muted">No session selected.</p>
            {/if}
          </section>
          <footer
            class="app-shell__main-composer border-t border-border bg-surface-1 p-3"
            data-testid="app-shell-main-composer"
          >
            {#if selectedSessionId !== null && activeSession?.kind !== SESSION_KIND_CHECKLIST}
              <Composer
                sessionId={selectedSessionId}
                disabled={activeSession?.closed_at !== null &&
                  activeSession?.closed_at !== undefined}
              />
            {/if}
          </footer>
        </main>

        <aside
          class="app-shell__inspector border-l border-border bg-surface-1"
          data-testid="app-shell-inspector"
          aria-label="Inspector"
        >
          <Inspector session={activeSession} />
        </aside>
      </div>
    </ContextMenuProvider>
  </KeybindingsProvider>
</ThemeProvider>

<style>
  /*
   * The grid is the only piece that has to hold across themes —
   * everything else uses Tailwind utility classes so theme switches
   * re-tint the shell synchronously.
   */
  .app-shell {
    display: grid;
    grid-template-columns: 16rem minmax(0, 1fr) 20rem;
    height: 100vh;
    width: 100vw;
    overflow: hidden;
  }

  .app-shell__sidebar,
  .app-shell__inspector {
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .app-shell__sidebar-body {
    flex: 1;
    overflow-y: auto;
  }

  .app-shell__main {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto;
    overflow: hidden;
  }

  .app-shell__main-body {
    overflow-y: auto;
  }
</style>
