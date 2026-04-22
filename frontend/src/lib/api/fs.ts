import { jsonFetch } from './core';

export type FsEntry = {
  name: string;
  path: string;
};

export type FsList = {
  path: string;
  parent: string | null;
  entries: FsEntry[];
};

export type FsListOptions = {
  path?: string | null;
  hidden?: boolean;
};

export function listDir(
  opts: FsListOptions = {},
  fetchImpl: typeof fetch = fetch
): Promise<FsList> {
  const params = new URLSearchParams();
  if (opts.path) params.set('path', opts.path);
  if (opts.hidden) params.set('hidden', 'true');
  const query = params.toString();
  return jsonFetch<FsList>(fetchImpl, `/api/fs/list${query ? `?${query}` : ''}`);
}

export type FsPick = {
  path: string | null;
  paths: string[];
  cancelled: boolean;
};

export type FsPickOptions = {
  /** Directory (or file) the dialog opens on. Falls back to $HOME. */
  start?: string | null;
  multiple?: boolean;
  title?: string;
};

/** Pops a native file picker on the server (zenity/kdialog) and returns
 * the absolute path the user chose. Bearings is localhost/single-user
 * by design, so spawning a dialog on the user's own desktop is fair
 * game — and it's the only way to hand Claude a real filesystem path
 * (browser `<input type="file">` can't expose one). */
export function pickFile(
  opts: FsPickOptions = {},
  fetchImpl: typeof fetch = fetch
): Promise<FsPick> {
  const params = new URLSearchParams();
  if (opts.start) params.set('start', opts.start);
  if (opts.multiple) params.set('multiple', 'true');
  if (opts.title) params.set('title', opts.title);
  const query = params.toString();
  return jsonFetch<FsPick>(fetchImpl, `/api/fs/pick${query ? `?${query}` : ''}`, {
    method: 'POST'
  });
}
