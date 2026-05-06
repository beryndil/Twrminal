/**
 * Templates store — list of saved session templates + instantiate /
 * delete helpers.
 *
 * Responsibilities:
 *
 * - Cache the ``GET /api/templates`` snapshot, sorted newest-first
 *   (the picker renders them in this order per
 *   ``docs/behavior/keyboard-shortcuts.md`` §"Create").
 * - Expose :func:`refreshTemplates` so the picker reloads on open.
 * - Expose :func:`instantiate` so a row click creates a session from
 *   the template and returns the new session id for navigation.
 * - Expose :func:`removeTemplate` so the × row affordance can delete
 *   a template and refresh the list without closing the picker.
 *
 * Pattern mirrors :mod:`stores/sessions.svelte.ts` — single ``$state``
 * proxy, cancellable refresh, test seam via :func:`_resetForTests`.
 */
import { createSession } from "../api/sessions";
import { deleteTemplate, listTemplates, type TemplateOut } from "../api/templates";

interface TemplatesState {
  /** Cached template list, newest-first (sorted by ``created_at`` DESC). */
  templates: TemplateOut[];
  /** ``true`` while :func:`refreshTemplates` is in flight. */
  loading: boolean;
  /** Last fetch error (cleared on next successful fetch). */
  error: Error | null;
}

const state: TemplatesState = $state({
  templates: [],
  loading: false,
  error: null,
});

/** Reactive proxy — components read from this via destructuring or ``$derived``. */
export const templatesStore = state;

let refreshController: AbortController | null = null;

/**
 * Reload the template list from ``GET /api/templates``.
 *
 * The API returns templates alphabetically; this store re-sorts
 * newest-first (by ``created_at`` DESC) so the picker always shows
 * the most recently added template at the top.
 *
 * Concurrent calls cancel the previous in-flight request, matching
 * the pattern from :mod:`stores/sessions.svelte.ts`.
 */
export async function refreshTemplates(): Promise<void> {
  refreshController?.abort();
  const controller = new AbortController();
  refreshController = controller;
  state.loading = true;
  try {
    const templates = await listTemplates({ signal: controller.signal });
    if (controller.signal.aborted) return;
    // Sort newest-first.
    state.templates = [...templates].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    );
    state.error = null;
  } catch (error) {
    if (controller.signal.aborted || _isAbortError(error)) return;
    state.error = error instanceof Error ? error : new Error(String(error));
  } finally {
    if (refreshController === controller) {
      refreshController = null;
    }
    state.loading = false;
  }
}

/**
 * Create a new session from a template and return the new session id.
 *
 * Builds a ``POST /api/sessions`` body from the template's routing
 * fields. The title defaults to the template name. If the backend
 * rejects the request (e.g. ``working_dir`` absent and no tags to
 * fall back to — 422), the thrown :class:`ApiError` surfaces inline
 * in the picker rather than closing it.
 */
export async function instantiate(templateId: number): Promise<string> {
  const template = state.templates.find((t) => t.id === templateId);
  if (template === undefined) {
    throw new Error(`Template ${templateId} not found in cache`);
  }
  const session = await createSession({
    kind: "chat",
    title: template.name,
    model: template.model,
    working_dir: template.working_dir_default,
    permission_mode: template.permission_profile !== "" ? template.permission_profile : null,
    routing_advisor_model: template.advisor_model,
    routing_advisor_max_uses: template.advisor_max_uses,
    routing_effort_level: template.effort_level,
  });
  return session.id;
}

/**
 * Delete a template by id, then refresh the list.
 *
 * On success the deleted row disappears from :data:`templatesStore.templates`.
 * On failure the thrown :class:`ApiError` surfaces inline in the picker.
 */
export async function removeTemplate(templateId: number): Promise<void> {
  await deleteTemplate(templateId);
  await refreshTemplates();
}

/** Test seam — reset all state and cancel any in-flight request. */
export function _resetForTests(): void {
  state.templates = [];
  state.loading = false;
  state.error = null;
  refreshController?.abort();
  refreshController = null;
}

function _isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
