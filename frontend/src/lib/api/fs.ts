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
   * FilePickerModal passes true so the listing also includes regular
   * files — each entry's `is_dir` tells the UI which affordance to
   * render. */
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
