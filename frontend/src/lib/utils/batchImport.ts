/**
 * Batch-import helper for drag-and-drop session import.
 *
 * Extracted from ``+layout.svelte`` so the progress/error logic is
 * independently testable without mounting the full app shell.
 *
 * Per ``docs/behavior/sessions.md`` §"Import contract — Drag-and-drop".
 */
import { importSessionJson } from "$lib/api/sessions";
import { ApiError } from "$lib/api/client";
import type { SessionOut } from "$lib/api/sessions";

/**
 * Read a ``File`` as UTF-8 text using ``FileReader``.
 *
 * Prefer ``FileReader`` over ``File.prototype.text()`` for jsdom
 * compatibility — ``Blob.prototype.text()`` is not implemented in the
 * jsdom version used by the vitest suite.
 */
function readFileAsText(file: File): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e): void => {
      const value = e.target?.result;
      if (typeof value === "string") {
        resolve(value);
      } else {
        reject(new Error("FileReader did not return a string"));
      }
    };
    reader.onerror = (): void => {
      reject(new Error("FileReader error"));
    };
    reader.readAsText(file);
  });
}

/** Progress snapshot emitted once per file before its fetch begins. */
export interface BatchImportProgress {
  /** 1-indexed position of the file currently being imported. */
  current: number;
  /** Total number of files in this batch. */
  total: number;
}

/** Per-file error entry. */
export interface BatchImportFileError {
  /** Original filename (``File.name``). */
  name: string;
  /** Human-readable detail string (API ``detail`` field or parse error). */
  detail: string;
}

/** Aggregate result returned after all files have been processed. */
export interface BatchImportResult {
  /** Sessions successfully imported (in import order). */
  imported: SessionOut[];
  /** Files that failed, with a per-file error message. */
  errors: BatchImportFileError[];
}

/**
 * Import an array of ``File`` objects as session exports.
 *
 * For each file in order:
 *
 * 1. Calls ``onProgress({ current: i+1, total: files.length })`` so
 *    the caller can update a "Importing N of M…" status line.
 * 2. Reads the file text, JSON-parses it, calls
 *    :func:`importSessionJson`.
 * 3. On success: pushes the returned ``SessionOut`` into
 *    ``result.imported``.
 * 4. On failure (parse error or ``ApiError``): pushes a
 *    :class:`BatchImportFileError` into ``result.errors`` and
 *    continues — one bad file does NOT abort the rest.
 *
 * @param files - Flat list of ``.json`` files to import.
 * @param onProgress - Called before each file's network request.
 * @returns Aggregate :class:`BatchImportResult` after all files are done.
 */
export async function importFromFiles(
  files: File[],
  onProgress: (progress: BatchImportProgress) => void,
): Promise<BatchImportResult> {
  const result: BatchImportResult = { imported: [], errors: [] };

  for (let i = 0; i < files.length; i += 1) {
    const file = files[i];
    onProgress({ current: i + 1, total: files.length });

    let text: string;
    try {
      text = await readFileAsText(file);
    } catch {
      result.errors.push({ name: file.name, detail: "Could not read file" });
      continue;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      result.errors.push({ name: file.name, detail: "Invalid JSON" });
      continue;
    }

    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      result.errors.push({ name: file.name, detail: "Not a JSON object" });
      continue;
    }

    try {
      const session = await importSessionJson(parsed as object);
      result.imported.push(session);
    } catch (err) {
      let detail: string;
      if (err instanceof ApiError) {
        detail =
          typeof err.body === "object" &&
          err.body !== null &&
          "detail" in err.body
            ? String((err.body as Record<string, unknown>).detail)
            : `HTTP ${err.status}`;
      } else if (err instanceof Error) {
        detail = err.message;
      } else {
        detail = "Import failed";
      }
      result.errors.push({ name: file.name, detail });
    }
  }

  return result;
}
