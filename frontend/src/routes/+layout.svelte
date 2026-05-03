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
  import ContextMeter from "$lib/components/conversation/ContextMeter.svelte";

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

  /** Current URL path as a plain string for nav-active comparisons. */
  const currentPath: string = $derived(page.url.pathname as string);
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
          <!-- Brand -->
          <div class="flex items-center gap-2 px-2 py-2 text-accent" data-testid="sidebar-brand">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 512 512"
              width="22"
              height="22"
              aria-hidden="true"
              data-testid="bearings-mark"
            >
              <g fill="none" stroke="currentColor">
                <circle cx="256" cy="256" r="220" stroke-width="18" opacity="0.3" />
                <circle cx="256" cy="256" r="160" stroke-width="12" opacity="0.5" />
                <circle cx="256" cy="256" r="100" stroke-width="12" opacity="0.7" />
              </g>
              <circle cx="256" cy="256" r="34" fill="currentColor" />
              <g fill="currentColor">
                <circle cx="386" cy="256" r="24" />
                <circle cx="347.92" cy="347.92" r="24" />
                <circle cx="256" cy="386" r="24" />
                <circle cx="164.08" cy="347.92" r="24" />
                <circle cx="126" cy="256" r="24" />
                <circle cx="164.08" cy="164.08" r="24" />
                <circle cx="256" cy="126" r="24" />
                <circle cx="347.92" cy="164.08" r="24" />
              </g>
            </svg>
            <span class="text-base font-semibold tracking-tight">{SIDEBAR_STRINGS.heading}</span>
          </div>

          <!-- New Session -->
          <div class="px-2 pb-2">
            <button
              type="button"
              class="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-muted focus:outline-none focus:ring-2 focus:ring-accent/70"
              aria-label={SIDEBAR_STRINGS.newSessionAriaLabel}
              data-testid="new-session-pill"
              onclick={() => void goto("/sessions/new")}
            >
              <span aria-hidden="true">+</span>
              <span>{SIDEBAR_STRINGS.newSessionLabel}</span>
            </button>
          </div>

          <!-- Primary nav -->
          <nav
            class="flex flex-col gap-0.5 px-1 pb-1"
            aria-label={SIDEBAR_STRINGS.navAriaLabel}
            data-testid="sidebar-nav"
          >
            <a
              href="/"
              class="flex items-center gap-2 rounded px-2 py-1.5 text-sm transition-colors"
              class:nav-link--active={currentPath === "/" || currentPath.startsWith("/sessions/")}
              class:text-accent={currentPath === "/" || currentPath.startsWith("/sessions/")}
              class:text-fg-muted={currentPath !== "/" && !currentPath.startsWith("/sessions/")}
              class:hover:bg-surface-2={currentPath !== "/" &&
                !currentPath.startsWith("/sessions/")}
              class:hover:text-fg={currentPath !== "/" && !currentPath.startsWith("/sessions/")}
              data-testid="sidebar-nav-sessions"
            >
              <svg
                viewBox="0 0 24 24"
                width="18"
                height="18"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line
                  x1="8"
                  y1="18"
                  x2="21"
                  y2="18"
                />
                <circle cx="3.5" cy="6" r="1.2" /><circle cx="3.5" cy="12" r="1.2" /><circle
                  cx="3.5"
                  cy="18"
                  r="1.2"
                />
              </svg>
              {SIDEBAR_STRINGS.navSessions}
            </a>

            <a
              href="/tags"
              class="flex items-center gap-2 rounded px-2 py-1.5 text-sm transition-colors"
              class:nav-link--active={currentPath === "/tags"}
              class:text-accent={currentPath === "/tags"}
              class:text-fg-muted={currentPath !== "/tags"}
              class:hover:bg-surface-2={currentPath !== "/tags"}
              class:hover:text-fg={currentPath !== "/tags"}
              data-testid="sidebar-nav-tags"
            >
              <svg
                viewBox="0 0 24 24"
                width="18"
                height="18"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <path
                  d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"
                />
                <circle cx="7" cy="7" r="1.2" fill="currentColor" stroke="none" />
              </svg>
              {SIDEBAR_STRINGS.navTags}
            </a>

            <a
              href="/memories"
              class="flex items-center gap-2 rounded px-2 py-1.5 text-sm transition-colors"
              class:nav-link--active={currentPath === "/memories"}
              class:text-accent={currentPath === "/memories"}
              class:text-fg-muted={currentPath !== "/memories"}
              class:hover:bg-surface-2={currentPath !== "/memories"}
              class:hover:text-fg={currentPath !== "/memories"}
              data-testid="sidebar-nav-memories"
            >
              <svg
                viewBox="0 0 24 24"
                width="18"
                height="18"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
              </svg>
              {SIDEBAR_STRINGS.navMemories}
            </a>

            <a
              href="/analytics"
              class="flex items-center gap-2 rounded px-2 py-1.5 text-sm transition-colors"
              class:nav-link--active={currentPath === "/analytics"}
              class:text-accent={currentPath === "/analytics"}
              class:text-fg-muted={currentPath !== "/analytics"}
              class:hover:bg-surface-2={currentPath !== "/analytics"}
              class:hover:text-fg={currentPath !== "/analytics"}
              data-testid="sidebar-nav-analytics"
            >
              <svg
                viewBox="0 0 24 24"
                width="18"
                height="18"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <line x1="6" y1="20" x2="6" y2="14" /><line x1="12" y1="20" x2="12" y2="4" /><line
                  x1="18"
                  y1="20"
                  x2="18"
                  y2="10"
                />
              </svg>
              {SIDEBAR_STRINGS.navAnalytics}
            </a>

            <a
              href="/settings"
              class="flex items-center gap-2 rounded px-2 py-1.5 text-sm transition-colors"
              class:nav-link--active={currentPath === "/settings"}
              class:text-accent={currentPath === "/settings"}
              class:text-fg-muted={currentPath !== "/settings"}
              class:hover:bg-surface-2={currentPath !== "/settings"}
              class:hover:text-fg={currentPath !== "/settings"}
              data-testid="sidebar-nav-settings"
            >
              <svg
                viewBox="0 0 24 24"
                width="18"
                height="18"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="3" />
                <path
                  d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"
                />
              </svg>
              {SIDEBAR_STRINGS.navSettings}
            </a>
          </nav>

          <!-- Session list -->
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
            class="app-shell__main-header border-b border-border px-3 py-2"
            data-testid="app-shell-main-header"
          >
            {#if activeSession !== null}
              <!-- Title + model + msg count -->
              <div class="flex min-w-0 items-baseline gap-2">
                <p
                  class="flex-1 truncate text-sm font-medium text-fg-strong"
                  data-testid="conversation-header-title"
                >
                  {activeSession.title}
                </p>
                <span class="shrink-0 rounded bg-surface-2 px-1.5 py-0.5 text-xs text-fg-muted">
                  {activeSession.model}
                </span>
                {#if activeSession.message_count > 0}
                  <span class="shrink-0 text-xs text-fg-muted"
                    >{activeSession.message_count} msgs</span
                  >
                {/if}
              </div>
              <!-- Tags -->
              {#if (sessionsStore.tagsBySessionId[activeSession.id] ?? []).length > 0}
                <div class="mt-1 flex flex-wrap gap-1" data-testid="conversation-header-tags">
                  {#each sessionsStore.tagsBySessionId[activeSession.id] ?? [] as tag (tag.id)}
                    <span
                      class="rounded px-1.5 py-0.5 text-xs"
                      style={tag.color ? `background:${tag.color}22;color:${tag.color}` : undefined}
                      class:bg-surface-2={!tag.color}
                      class:text-fg-muted={!tag.color}
                      data-testid="conversation-header-tag"
                    >
                      {tag.name}
                    </span>
                  {/each}
                </div>
              {/if}
              <!-- Description excerpt -->
              {#if activeSession.description}
                <p
                  class="mt-1 line-clamp-2 text-xs text-fg-muted"
                  data-testid="conversation-header-desc"
                >
                  {activeSession.description}
                </p>
              {/if}
            {/if}
          </header>
          <!-- Context/token meter strip — hidden until first context_usage arrives -->
          <ContextMeter />
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
            class="app-shell__main-composer border-t border-border bg-surface-2 p-3"
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

        <!-- Status bar — spans full width -->
        <footer
          class="app-shell__statusbar border-t border-border bg-surface-0 px-3"
          data-testid="status-bar"
          aria-label="Status bar"
        >
          <span class="text-fg-muted">{SIDEBAR_STRINGS.heading} {SIDEBAR_STRINGS.versionTag}</span>
          <span class="ml-auto flex items-center gap-4">
            <span class="flex items-center gap-1.5 text-fg-muted">
              <span class="inline-block h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true"
              ></span>
              Recovery: Idle
            </span>
            <span class="flex items-center gap-1.5 text-fg-muted">
              <span class="inline-block h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true"
              ></span>
              Auto-save: Idle
            </span>
            <span
              class="rounded bg-surface-2 px-2 py-0.5 text-xs font-medium text-fg-muted"
              data-testid="status-bar-connection"
            >
              IDLE
            </span>
          </span>
        </footer>
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

  /* Active nav link — soft accent tint that re-tints on theme change. */
  .nav-link--active {
    background-color: rgb(var(--bearings-accent) / 0.12);
    color: rgb(var(--bearings-accent));
  }

  .app-shell {
    display: grid;
    grid-template-columns: 16rem minmax(0, 1fr) 20rem;
    grid-template-rows: 1fr auto;
    height: 100vh;
    width: 100vw;
    overflow: hidden;
  }

  .app-shell__statusbar {
    grid-column: 1 / -1;
    display: flex;
    align-items: center;
    height: 1.75rem;
    font-size: 0.6875rem;
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
