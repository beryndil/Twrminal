/**
 * Typed client for ``GET /api/preferences`` and ``PATCH /api/preferences``
 * — singleton user-preferences row (item 3.2).
 *
 * Backend route: :func:`bearings.web.routes.preferences`.
 * Pydantic shape: :class:`bearings.web.models.preferences.PreferencesOut`.
 */
import { API_PREFERENCES_ENDPOINT } from "../config";
import { getJson, patchJson } from "./client";

/**
 * Mirrors :class:`bearings.web.models.preferences.PreferencesOut`.
 *
 * ``theme`` is always present (NOT NULL column).  The three
 * ``default_*`` fields are nullable — ``null`` means "no default set".
 */
export interface PreferencesOut {
  theme: string;
  default_model: string | null;
  default_permission_mode: string | null;
  default_working_dir: string | null;
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
