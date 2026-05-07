/**
 * Typed client for ``POST /api/shell/exec`` — the shell-open surface
 * used by context-menu "Open in editor", "Reveal in file explorer",
 * and "Open in terminal" actions.
 *
 * All openers dispatch ``xdg-open`` (the only command in the default
 * allowlist defined in ``src/bearings/config/constants.py``
 * §"DEFAULT_ALLOWED_SHELL_COMMANDS").  The opener type determines
 * which path is passed:
 *
 * - ``editor``        — ``xdg-open <file_path>`` opens the file in
 *   the user's registered handler (typically a code editor or text
 *   editor).
 * - ``file_explorer`` — ``xdg-open <parent_dir>`` opens the file's
 *   parent directory in the default file manager.
 * - ``terminal``      — ``xdg-open <dir>`` opens the directory; the
 *   user's desktop environment determines whether this launches a
 *   terminal or a file manager depending on their XDG MIME
 *   configuration.
 *
 * Each function throws :class:`ApiError` on a non-2xx response so
 * callers can surface an error toast.
 *
 * Behavior anchor:
 * ``docs/behavior/context-menus.md`` §"Shell-open integration".
 */
import { API_SHELL_EXEC_ENDPOINT } from "../config";
import { postJson } from "./client";

// ---- Wire shapes ------------------------------------------------------------

interface ShellExecIn {
  readonly argv: readonly string[];
}

interface ShellExecOut {
  readonly exit_code: number;
  readonly reason: string;
  readonly stdout: string;
  readonly stderr: string;
  readonly duration_s: number;
}

// ---- Helpers ----------------------------------------------------------------

/**
 * Return the parent directory of an absolute ``path`` by stripping the
 * last path component.  Falls back to ``/`` for bare top-level paths.
 */
function parentDir(path: string): string {
  const idx = path.lastIndexOf("/");
  return idx > 0 ? path.slice(0, idx) : "/";
}

// ---- Public API -------------------------------------------------------------

/**
 * Open ``path`` in the user's default editor via ``xdg-open``.
 *
 * Throws :class:`ApiError` on a non-2xx response.
 */
export async function shellOpenInEditor(path: string): Promise<void> {
  await postJson<ShellExecOut>(API_SHELL_EXEC_ENDPOINT, {
    argv: ["xdg-open", path],
  } satisfies ShellExecIn);
}

/**
 * Open the parent directory of ``path`` in the file manager via
 * ``xdg-open``.
 *
 * Throws :class:`ApiError` on a non-2xx response.
 */
export async function shellRevealInExplorer(path: string): Promise<void> {
  await postJson<ShellExecOut>(API_SHELL_EXEC_ENDPOINT, {
    argv: ["xdg-open", parentDir(path)],
  } satisfies ShellExecIn);
}

/**
 * Open ``dir`` via ``xdg-open``.  On most desktop environments this
 * opens a file manager; users who have associated directories with a
 * terminal emulator in their XDG MIME database will get a terminal
 * window instead.
 *
 * Throws :class:`ApiError` on a non-2xx response.
 */
export async function shellOpenInTerminal(dir: string): Promise<void> {
  await postJson<ShellExecOut>(API_SHELL_EXEC_ENDPOINT, {
    argv: ["xdg-open", dir],
  } satisfies ShellExecIn);
}

export type { ShellExecIn, ShellExecOut };
