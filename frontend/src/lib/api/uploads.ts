/**
 * Typed client for ``POST /api/uploads`` — the file-upload surface
 * (``src/bearings/web/routes/uploads.py``;
 * ``docs/behavior/chat.md`` §"Composer — attachment ingestion").
 *
 * Batch-upload semantics (multiple files dropped at once) are
 * implemented as parallel individual POSTs — the backend exposes no
 * ``/api/uploads/batch`` endpoint in v18. All uploads fire concurrently
 * and each resolves independently with its own :class:`ApiError` if it
 * fails. This matches the acceptance requirement while avoiding an
 * extra backend endpoint.
 *
 * The upload body is ``multipart/form-data`` with a single ``file``
 * part. The browser derives the correct ``Content-Type`` boundary
 * automatically from the ``FormData`` object — callers must NOT set it
 * manually.
 */
import { API_UPLOADS_ENDPOINT } from "../config";
import { ApiError } from "./client";

/**
 * Wire shape — one-to-one with
 * :class:`bearings.web.models.uploads.UploadOut`. Mirrors the field
 * names exactly so the cast in :func:`uploadFile` is correct without
 * runtime validation.
 */
export interface UploadOut {
  id: number;
  sha256: string;
  filename: string;
  mime_type: string;
  size: number;
  created_at: number;
}

const HTTP_OK_MIN = 200;
const HTTP_OK_MAX = 300;

/**
 * Upload a single file to ``POST /api/uploads``. Returns the server
 * row on ``201 Created``.
 *
 * Throws an :class:`ApiError` on any non-2xx response so the caller
 * can surface the ``detail`` string inline next to the chip without
 * blocking other concurrent uploads.
 *
 * Pass an ``AbortSignal`` (from an ``AbortController``) to cancel the
 * upload mid-flight. When aborted, the promise rejects with the
 * browser-native ``AbortError`` — callers should check
 * ``error.name === "AbortError"`` and suppress the rejection rather
 * than surfacing it as an inline chip error.
 */
export async function uploadFile(file: File, signal?: AbortSignal): Promise<UploadOut> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(API_UPLOADS_ENDPOINT, {
    method: "POST",
    body: form,
    signal,
  });
  if (response.status < HTTP_OK_MIN || response.status >= HTTP_OK_MAX) {
    const body = await safeReadBody(response);
    throw new ApiError(
      response.status,
      body,
      `POST ${API_UPLOADS_ENDPOINT} → ${response.status} ${response.statusText}`,
    );
  }
  return (await response.json()) as UploadOut;
}

async function safeReadBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    try {
      return await response.text();
    } catch {
      return null;
    }
  }
}
