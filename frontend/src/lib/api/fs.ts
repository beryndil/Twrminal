import { jsonFetch } from './core';

export type FsEntry = {
  name: string;
  path: string;
  is_dir: boolean;
};

export type FsList = {
  path: string;
  parent: string | null;
  entries: FsEntry[];
};

export type FsListOptions = {
  path?: string | null;
  hidden?: boolean;
  /** FolderPicker leaves this false to keep its dirs-only contract.
   * Callers that want files in the listing can pass true — each entry's
   * `is_dir` tells the UI which affordance to render. Currently unused
   * by the in-app UI (attach-file + working-dir flow both pop the
   * native picker via `/api/fs/pick`), but kept so the listing route
   * stays symmetric for future consumers. */
  includeFiles?: boolean;
};

export function listDir(
  opts: FsListOptions = {},
  fetchImpl: typeof fetch = fetch
): Promise<FsList> {
  const params = new URLSearchParams();
  if (opts.path) params.set('path', opts.path);
  if (opts.hidden) params.set('hidden', 'true');
  if (opts.includeFiles) params.set('include_files', 'true');
  const query = params.toString();
  return jsonFetch<FsList>(fetchImpl, `/api/fs/list${query ? `?${query}` : ''}`);
}

/** Shape of `POST /api/fs/pick`. `cancelled` is the primary branch the
 * UI checks — when true, the user dismissed the dialog and the UI
 * should no-op silently. Otherwise `paths` carries the selection(s)
 * and `path` mirrors the first pick for single-select callers. */
export type FsPick = {
  path: string | null;
  paths: string[];
  cancelled: boolean;
};

export type FsPickMode = 'file' | 'directory';

export type FsPickOptions = {
  /** Directory to open the picker in. Defaults to $HOME server-side. */
  start?: string | null;
  /** Allow multi-select. Ignored server-side for directory picks. */
  multiple?: boolean;
  /** Dialog title. Falls back to a generic label. */
  title?: string;
};

function pick(
  mode: FsPickMode,
  opts: FsPickOptions = {},
  fetchImpl: typeof fetch = fetch
): Promise<FsPick> {
  const params = new URLSearchParams();
  params.set('mode', mode);
  if (opts.start) params.set('start', opts.start);
  if (opts.multiple) params.set('multiple', 'true');
  if (opts.title) params.set('title', opts.title);
  return jsonFetch<FsPick>(fetchImpl, `/api/fs/pick?${params.toString()}`, {
    method: 'POST'
  });
}

/** Pop the host's native file picker (zenity/kdialog). Returns the
 * chosen absolute path(s) or a cancelled result. Only reachable on
 * localhost — a native picker on a remote server would be absurd. */
export function pickFile(
  opts: FsPickOptions = {},
  fetchImpl: typeof fetch = fetch
): Promise<FsPick> {
  return pick('file', opts, fetchImpl);
}

/** Pop the host's native directory picker. `multiple` is silently
 * ignored by zenity/kdialog, so the returned `paths` is always a
 * single-element array on success. */
export function pickDirectory(
  opts: FsPickOptions = {},
  fetchImpl: typeof fetch = fetch
): Promise<FsPick> {
  return pick('directory', opts, fetchImpl);
}
