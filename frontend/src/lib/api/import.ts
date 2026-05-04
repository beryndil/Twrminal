/**
 * Typed client for ``POST /api/import/bearings`` — import data from
 * the original Bearings database into Bearings-v1.
 *
 * Backend route: :func:`bearings.web.routes.import_db.post_import_bearings`
 * Pydantic shape: :class:`bearings.web.routes.import_db.ImportResultOut`
 */
import { API_IMPORT_BEARINGS_ENDPOINT } from "../config";
import { postJson } from "./client";

/**
 * Mirrors :class:`bearings.web.routes.import_db.ImportResultOut`.
 *
 * Contains counts of imported and skipped rows per table, plus any
 * error messages encountered during the import.
 */
export interface ImportResultOut {
  tags_imported: number;
  sessions_imported: number;
  messages_imported: number;
  session_tags_imported: number;
  tag_memories_imported: number;
  checklist_items_imported: number;
  tags_skipped: number;
  sessions_skipped: number;
  messages_skipped: number;
  session_tags_skipped: number;
  tag_memories_skipped: number;
  checklist_items_skipped: number;
  errors: string[];
}

/**
 * Import all data from the original Bearings database.
 *
 * Reads from ~/.local/share/bearings/db.sqlite and copies all sessions,
 * messages, tags, and related data into the current Bearings-v1 database.
 * Rows with duplicate IDs are silently skipped.
 */
export async function importFromBearings(): Promise<ImportResultOut> {
  return postJson<ImportResultOut>(API_IMPORT_BEARINGS_ENDPOINT, {});
}
