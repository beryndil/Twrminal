import { jsonFetch } from './core';

/** Result of `POST /api/uploads` — the server persists the uploaded
 * bytes under a UUID name and hands back the absolute on-disk path,
 * which the drop handler injects into the prompt so Claude can read
 * it from disk. `filename` is the sanitized original name (basename
 * only, no path components) and is useful for a future attachment
 * chip; `size_bytes` and `mime_type` round out the display surface. */
export type Upload = {
  path: string;
  filename: string;
  size_bytes: number;
  mime_type: string;
};

/** Upload one File to `/api/uploads` and return the server-side path.
 *
 * The endpoint exists because Chrome on Wayland strips the URI
 * metadata from file drops even though `DataTransfer.files` still
 * carries the bytes. We read those bytes, POST them here, and inject
 * the resulting absolute path into the prompt — same shape as a
 * zenity/kdialog pick, just with an extra round-trip.
 *
 * Errors propagate as thrown `Error` instances (413 for over-size,
 * 415 for a blocked extension). The caller surfaces them via the
 * `dropDiagnostic` banner so the user sees the exact reason rather
 * than a silent failure. */
export function uploadFile(
  file: File,
  fetchImpl: typeof fetch = fetch
): Promise<Upload> {
  const form = new FormData();
  // Field name must match the FastAPI handler's `file: UploadFile`
  // parameter. `file.name` is the browser-reported filename; the
  // server treats it as untrusted input and only extracts the suffix.
  form.append('file', file, file.name);
  // Intentionally don't set Content-Type — the browser sets it to
  // `multipart/form-data; boundary=...` automatically for a FormData
  // body, and overriding would strip the boundary.
  return jsonFetch<Upload>(fetchImpl, '/api/uploads', {
    method: 'POST',
    body: form
  });
}
