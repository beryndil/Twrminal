/**
 * Typed client for ``POST /api/fs/pick`` (folder picker bootstrap +
 * navigation, item 3.1).
 *
 * The folder picker uses ``POST /api/fs/pick`` for every navigation
 * step — initial bootstrap and each directory descent or ascent.
 * Each call validates the requested path server-side (against the
 * configured allow-roots, or the user's home dir when no roots are
 * configured) and returns the directory listing.
 *
 * The ``token`` field in the response is a per-call UUID reserved for
 * future server-side picker-session tracking; clients may ignore it.
 */
import { postJson } from "./client";

/** Wire shape for one directory entry, mirroring ``FsEntryOut``. */
export interface FsEntry {
  name: string;
  /** ``"file"`` | ``"dir"`` | ``"symlink"`` | ``"other"`` */
  kind: string;
  size: number;
  mtime: number;
  is_readable: boolean;
}

/** Response shape for ``POST /api/fs/pick``, mirroring ``FsPickOut``. */
interface FsPickOut {
  token: string;
  path: string;
  entries: FsEntry[];
  capped: boolean;
}

/**
 * Bootstrap or navigate a folder-picker session.
 *
 * Pass ``root`` to start at a specific absolute path; omit (or pass
 * an empty string) to let the server default to the user's home
 * directory.  Call again with the new path to navigate.
 */
export async function pickDir(root = ""): Promise<FsPickOut> {
  return postJson<FsPickOut>("/api/fs/pick", { root });
}
