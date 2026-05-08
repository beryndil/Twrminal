/**
 * Typed client for the templates REST surface (G7;
 * ``src/bearings/web/routes/templates.py``).
 *
 * Mirrors :class:`bearings.web.models.templates.TemplateOut` /
 * :class:`bearings.web.models.templates.TemplateIn` /
 * :class:`bearings.web.models.templates.TemplatePatch` /
 * :class:`bearings.web.models.templates.TemplateInstantiateIn` field for field.
 * The new-session dialog fetches the list on mount to populate the template
 * picker dropdown; the session-row context menu uses ``createTemplate`` to
 * implement the ``save_as_template`` action; ``instantiateTemplate`` creates a
 * fully-populated session from a template in one server-side transaction
 * (gap-cycle-13-006).
 */
import { API_TEMPLATES_ENDPOINT, templateEndpoint, templateInstantiateEndpoint } from "../config";
import { deleteResource, getJson, patchJson, postJson, type RequestOptions } from "./client";
import type { SessionOut } from "./sessions";

/** Wire shape — one-to-one with :class:`bearings.web.models.templates.TemplateOut`. */
export interface TemplateOut {
  id: number;
  name: string;
  description: string | null;
  model: string;
  advisor_model: string | null;
  advisor_max_uses: number;
  effort_level: string;
  permission_profile: string;
  system_prompt_baseline: string | null;
  working_dir_default: string | null;
  tag_names: string[];
  created_at: string;
  updated_at: string;
}

interface CreateTemplateParams {
  name: string;
  model: string;
  description?: string | null;
  advisor_model?: string | null;
  advisor_max_uses?: number;
  effort_level?: string;
  permission_profile?: string;
  system_prompt_baseline?: string | null;
  working_dir_default?: string | null;
  tag_names?: string[];
}

interface PatchTemplateParams {
  name?: string;
  model?: string;
  description?: string | null;
  advisor_model?: string | null;
  advisor_max_uses?: number;
  effort_level?: string;
  permission_profile?: string;
  system_prompt_baseline?: string | null;
  working_dir_default?: string | null;
  tag_names?: string[];
}

/**
 * Create a new template. Returns the created row.
 *
 * 409 when the name is already taken; 422 when routing fields are invalid.
 */
export async function createTemplate(
  params: CreateTemplateParams,
  options: RequestOptions = {},
): Promise<TemplateOut> {
  return await postJson<TemplateOut>(API_TEMPLATES_ENDPOINT, params, options);
}

/**
 * List all templates, alphabetically by name. Returns ``[]`` when none
 * exist yet — the picker renders only the "-- no template --" placeholder.
 */
export async function listTemplates(options: RequestOptions = {}): Promise<TemplateOut[]> {
  return await getJson<TemplateOut[]>(API_TEMPLATES_ENDPOINT, options);
}

/**
 * Fetch a single template by id. 404 surfaces as :class:`ApiError`.
 *
 * Not yet consumed by any UI component — export added when a template
 * detail / edit surface lands (future item).
 */
async function getTemplate(templateId: number, options: RequestOptions = {}): Promise<TemplateOut> {
  return await getJson<TemplateOut>(templateEndpoint(templateId), options);
}

/**
 * Partially update a template. Only the supplied fields are changed;
 * all others are preserved. 404 / 409 surface as :class:`ApiError`.
 *
 * Not yet consumed by any UI component — export added when a template
 * edit surface lands (future item).
 */
async function patchTemplate(
  templateId: number,
  params: PatchTemplateParams,
  options: RequestOptions = {},
): Promise<TemplateOut> {
  return await patchJson<TemplateOut>(templateEndpoint(templateId), params, options);
}

/**
 * Delete a template by id. 204 on success; 404 surfaces as :class:`ApiError`.
 */
export async function deleteTemplate(
  templateId: number,
  options: RequestOptions = {},
): Promise<void> {
  return await deleteResource<void>(templateEndpoint(templateId), options);
}

/** Optional override fields for :func:`instantiateTemplate`. */
interface InstantiateTemplateParams {
  /** Overrides the title; defaults to the template name server-side. */
  title?: string;
  /** Overrides the executor model. */
  model?: string;
  /** Overrides the description. */
  description?: string | null;
  /** Overrides the working directory. */
  working_dir?: string | null;
  /** Overrides the session instructions (baseline: system_prompt_baseline). */
  session_instructions?: string | null;
  /** Overrides the permission mode. */
  permission_mode?: string | null;
  /** Overrides the advisor model. */
  advisor_model?: string | null;
  /** Overrides the advisor max uses. */
  advisor_max_uses?: number;
  /** Overrides the effort level. */
  effort_level?: string;
}

/**
 * Create a new session from a template (gap-cycle-13-006).
 *
 * Calls ``POST /api/templates/{id}/instantiate`` which copies all template
 * fields (model, advisor settings, effort_level, permission_profile,
 * working_dir_default, system_prompt_baseline → session_instructions,
 * tag_names → attached tags, description) into a new session row in one
 * server-side sequence. The optional ``params`` body can override any field.
 *
 * 404 when the template does not exist; 422 when no working_dir is
 * resolvable or routing fields are invalid.
 */
export async function instantiateTemplate(
  templateId: number,
  params: InstantiateTemplateParams = {},
  options: RequestOptions = {},
): Promise<SessionOut> {
  return await postJson<SessionOut>(templateInstantiateEndpoint(templateId), params, options);
}

// Silence unused-variable warnings in editors until consumers are added.
void getTemplate;
void patchTemplate;
