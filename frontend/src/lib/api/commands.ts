/**
 * Typed client for ``GET /api/commands`` — slash-command list used by
 * the composer typeahead (item 2.3).
 *
 * Backend route: :func:`bearings.web.routes.commands.list_commands`.
 * Pydantic shape: :class:`bearings.web.models.commands.CommandOut`.
 */
import { API_COMMANDS_ENDPOINT } from "../config";
import { getJson } from "./client";

/**
 * One slash-command entry — mirrors
 * :class:`bearings.web.models.commands.CommandOut`.
 *
 * ``source`` is one of ``"user_commands"`` | ``"user_skills"`` |
 * ``"project_commands"``.
 */
export interface CommandOut {
  name: string;
  description: string;
  source: string;
}

/**
 * Fetch the full slash-command list from the server.
 *
 * Never rejects on a network/server error — an empty array is returned
 * instead so the composer gracefully degrades when the backend is
 * unreachable.
 */
export async function listCommands(): Promise<CommandOut[]> {
  try {
    return await getJson<CommandOut[]>(API_COMMANDS_ENDPOINT);
  } catch {
    return [];
  }
}
