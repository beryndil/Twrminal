/**
 * Typed client for ``GET /api/preferences``, ``PATCH /api/preferences``,
 * and the avatar / sync endpoints (item 3.2 + gap-cycle-03-011).
 *
 * Backend route: :func:`bearings.web.routes.preferences`.
 * Pydantic shape: :class:`bearings.web.models.preferences.PreferencesOut`.
 */
import {
  API_PREFERENCES_AVATAR_ENDPOINT,
  API_PREFERENCES_ENDPOINT,
  API_PREFERENCES_SYNC_ENDPOINT,
} from "../config";
import { deleteResource, getJson, patchJson, postJson } from "./client";

/**
 * Mirrors :class:`bearings.web.models.preferences.PreferencesOut`.
 *
 * ``theme`` is always present (NOT NULL column).  The three
 * ``default_*`` fields are nullable — ``null`` means "no default set".
 * ``display_name`` is ``null`` when the user has not set a name.
 * ``avatar_url`` is the URL path (``/api/preferences/avatar``) when an
 * avatar is stored, or ``null`` when none is set.  The caller appends
 * ``?v=<updated_at>`` for HTTP cache-busting.
 */
export interface PreferencesOut {
  theme: string;
  default_model: string | null;
  default_permission_mode: string | null;
  default_working_dir: string | null;
  display_name: string | null;
  avatar_url: string | null;
  /** gap-cycle-07-001: desktop-notification opt-in. */
  notify_on_complete: boolean;
  updated_at: string;
}

/**
 * Partial update body — mirrors
 * :class:`bearings.web.models.preferences.PreferencesPatch`.
 *
 * All fields are optional; only supplied keys are written to the DB.
 * Send ``null`` for a nullable field to clear it.
 */
export interface PreferencesPatch {
  theme?: string | null;
  default_model?: string | null;
  default_permission_mode?: string | null;
  default_working_dir?: string | null;
  display_name?: string | null;
  /** gap-cycle-07-001: desktop-notification opt-in. */
  notify_on_complete?: boolean | null;
}

/** Fetch the singleton user-preferences row. */
export async function getPreferences(): Promise<PreferencesOut> {
  return getJson<PreferencesOut>(API_PREFERENCES_ENDPOINT);
}

/**
 * Partially update user preferences.
 *
 * Only the supplied keys are written to the DB; omitted fields retain
 * their current values.  Returns the updated row.
 */
export async function patchPreferences(patch: PreferencesPatch): Promise<PreferencesOut> {
  return patchJson<PreferencesOut>(API_PREFERENCES_ENDPOINT, patch);
}

/**
 * Upload a new avatar image.
 *
 * ``file`` must be an image (JPEG, PNG, GIF, or WebP). Returns the
 * updated preferences row with ``avatar_url`` populated.
 */
export async function uploadAvatar(file: File): Promise<PreferencesOut> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(API_PREFERENCES_AVATAR_ENDPOINT, {
    method: "POST",
    body: form,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`POST avatar → ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as PreferencesOut;
}

/**
 * Delete the current avatar.
 *
 * Returns the updated preferences row with ``avatar_url`` set to ``null``.
 */
export async function deleteAvatar(): Promise<PreferencesOut> {
  return deleteResource<PreferencesOut>(API_PREFERENCES_AVATAR_ENDPOINT);
}

/**
 * Populate ``display_name`` from ``$USER`` and avatar from ``~/.face``.
 *
 * Returns the updated preferences row.
 */
export async function syncFromSystem(): Promise<PreferencesOut> {
  return postJson<PreferencesOut>(API_PREFERENCES_SYNC_ENDPOINT, {});
}
