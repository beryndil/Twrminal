/**
 * Tests for :mod:`api/shell.ts` — locks the wire contract for
 * ``POST /api/shell/exec`` shell-open actions.
 *
 * Each acceptance-criterion action is verified to:
 * - POST to ``/api/shell/exec``
 * - Include the correct ``argv`` shape
 * - Throw :class:`ApiError` on non-2xx (surface to caller for toast)
 *
 * Behavior anchor:
 * ``docs/behavior/context-menus.md`` §"Shell-open integration".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../client";
import { shellOpenInEditor, shellOpenInTerminal, shellRevealInExplorer } from "../shell";

const fetchMock = vi.fn();

function okResponse(): Response {
  return {
    status: 200,
    statusText: "OK",
    json: async () => ({
      exit_code: 0,
      reason: "success",
      stdout: "",
      stderr: "",
      duration_s: 0.05,
    }),
    text: async () => "{}",
  } as unknown as Response;
}

function errorResponse(status: number, detail: string): Response {
  return {
    status,
    statusText: "Error",
    json: async () => ({ detail }),
    text: async () => JSON.stringify({ detail }),
  } as unknown as Response;
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

// ---- shellOpenInEditor ------------------------------------------------------

describe("shellOpenInEditor", () => {
  it("POSTs to /api/shell/exec with argv=['xdg-open', path]", async () => {
    fetchMock.mockResolvedValueOnce(okResponse());
    await shellOpenInEditor("/home/user/project/file.py");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/shell/exec");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string) as { argv: string[] };
    expect(body.argv).toEqual(["xdg-open", "/home/user/project/file.py"]);
  });

  it("throws ApiError on non-2xx (e.g. 422 allowlist rejection)", async () => {
    fetchMock.mockResolvedValueOnce(errorResponse(422, "argv[0] not in allowlist"));
    await expect(shellOpenInEditor("/etc/passwd")).rejects.toBeInstanceOf(ApiError);
  });

  it("throws ApiError on 503 (shell_cfg misconfigured)", async () => {
    fetchMock.mockResolvedValueOnce(
      errorResponse(503, "shell_cfg on app.state is not a ShellCfg instance"),
    );
    await expect(shellOpenInEditor("/some/path")).rejects.toBeInstanceOf(ApiError);
  });
});

// ---- shellRevealInExplorer --------------------------------------------------

describe("shellRevealInExplorer", () => {
  it("POSTs to /api/shell/exec with the parent directory as the path", async () => {
    fetchMock.mockResolvedValueOnce(okResponse());
    await shellRevealInExplorer("/home/user/project/file.py");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/shell/exec");
    const body = JSON.parse(init.body as string) as { argv: string[] };
    // parent of /home/user/project/file.py is /home/user/project
    expect(body.argv).toEqual(["xdg-open", "/home/user/project"]);
  });

  it("uses opener='file_explorer' convention: passes parent dir not the file", async () => {
    fetchMock.mockResolvedValueOnce(okResponse());
    await shellRevealInExplorer("/a/b/c/deep.ts");
    const body = JSON.parse(
      (fetchMock.mock.calls[0] as [string, RequestInit])[1].body as string,
    ) as { argv: string[] };
    expect(body.argv[1]).toBe("/a/b/c");
  });

  it("falls back to / for bare top-level path", async () => {
    fetchMock.mockResolvedValueOnce(okResponse());
    await shellRevealInExplorer("/file.txt");
    const body = JSON.parse(
      (fetchMock.mock.calls[0] as [string, RequestInit])[1].body as string,
    ) as { argv: string[] };
    expect(body.argv[1]).toBe("/");
  });

  it("throws ApiError on non-2xx", async () => {
    fetchMock.mockResolvedValueOnce(errorResponse(403, "forbidden"));
    await expect(shellRevealInExplorer("/some/path")).rejects.toBeInstanceOf(ApiError);
  });
});

// ---- shellOpenInTerminal ----------------------------------------------------

describe("shellOpenInTerminal", () => {
  it("POSTs to /api/shell/exec with argv=['xdg-open', dir]", async () => {
    fetchMock.mockResolvedValueOnce(okResponse());
    await shellOpenInTerminal("/home/user/project");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/shell/exec");
    const body = JSON.parse(init.body as string) as { argv: string[] };
    expect(body.argv).toEqual(["xdg-open", "/home/user/project"]);
  });

  it("passes the working_dir unchanged (no path manipulation)", async () => {
    fetchMock.mockResolvedValueOnce(okResponse());
    const dir = "/home/beryndil/Projects/active/bearings";
    await shellOpenInTerminal(dir);
    const body = JSON.parse(
      (fetchMock.mock.calls[0] as [string, RequestInit])[1].body as string,
    ) as { argv: string[] };
    expect(body.argv[1]).toBe(dir);
  });

  it("throws ApiError on non-2xx", async () => {
    fetchMock.mockResolvedValueOnce(errorResponse(504, "timeout"));
    await expect(shellOpenInTerminal("/some/dir")).rejects.toBeInstanceOf(ApiError);
  });
});
