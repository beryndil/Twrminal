/**
 * Session-template HTTP client (Phase 9b of docs/context-menu-plan.md).
 *
 * Wraps the four server endpoints: `POST/GET /api/templates`,
 * `DELETE /api/templates/{id}`, `POST /api/sessions/from_template/{id}`.
 * The wire shape mirrors `TemplateOut` on the backend — `tag_ids` is
 * pre-decoded (not the raw JSON column).
 */

import type { Session } from './sessions';
import { jsonFetch, voidFetch } from './core';

export type Template = {
  id: string;
  name: string;
  body: string | null;
  working_dir: string | null;
  model: string | null;
  session_instructions: string | null;
  tag_ids: number[];
  created_at: string;
};

export type TemplateCreate = {
  name: string;
  body?: string | null;
  working_dir?: string | null;
  model?: string | null;
  session_instructions?: string | null;
  tag_ids?: number[];
};

export type TemplateInstantiateRequest = {
  title?: string | null;
  working_dir?: string | null;
  model?: string | null;
  session_instructions?: string | null;
  body?: string | null;
};

export function listTemplates(fetchImpl: typeof fetch = fetch): Promise<Template[]> {
  return jsonFetch<Template[]>(fetchImpl, '/api/templates');
}

export function createTemplate(
  body: TemplateCreate,
  fetchImpl: typeof fetch = fetch
): Promise<Template> {
  return jsonFetch<Template>(fetchImpl, '/api/templates', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body)
  });
}

export function deleteTemplate(
  id: string,
  fetchImpl: typeof fetch = fetch
): Promise<void> {
  return voidFetch(fetchImpl, `/api/templates/${encodeURIComponent(id)}`, {
    method: 'DELETE'
  });
}

export function instantiateTemplate(
  id: string,
  body: TemplateInstantiateRequest = {},
  fetchImpl: typeof fetch = fetch
): Promise<Session> {
  return jsonFetch<Session>(
    fetchImpl,
    `/api/sessions/from_template/${encodeURIComponent(id)}`,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body)
    }
  );
}
