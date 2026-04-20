from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from typing import IO, Any

from websockets.asyncio.client import connect as ws_connect

from twrminal import __version__
from twrminal.config import load_settings

# Ordered by popularity on Linux so the first hit on PATH is likely
# the one the user actually uses. All of these accept --app=URL to
# launch a chromeless standalone window.
CHROMIUM_FLAVORED_BROWSERS: tuple[str, ...] = (
    "google-chrome-stable",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "brave-browser",
    "brave",
    "microsoft-edge-stable",
    "microsoft-edge",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="twrminal")
    parser.add_argument("--version", action="version", version=f"twrminal {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="Run the FastAPI server")
    sub.add_parser("init", help="Initialize config + database on disk")

    window = sub.add_parser(
        "window",
        help="Open the UI in a standalone Chromium-flavored app window",
    )
    window.add_argument("--host", default=None, help="Server host (default: from config)")
    window.add_argument("--port", type=int, default=None, help="Server port (default: from config)")
    window.add_argument(
        "--browser",
        default=None,
        help="Path to a Chromium-flavored browser binary. Defaults to autodetect.",
    )

    send = sub.add_parser("send", help="Send a one-shot prompt to an agent session")
    send.add_argument("--session", required=True, help="Session id")
    send.add_argument("--host", default=None, help="Server host (default: from config)")
    send.add_argument("--port", type=int, default=None, help="Server port (default: from config)")
    send.add_argument(
        "--token",
        default=None,
        help="Auth token (default: from config auth.token when auth.enabled)",
    )
    send.add_argument(
        "--format",
        dest="format",
        choices=("json", "pretty"),
        default="json",
        help="Output format: json (one event per line, default) or pretty (human-readable).",
    )
    send.add_argument("message", help="Prompt text")

    return parser


def _format_pretty(event: dict[str, Any]) -> str | None:
    """Human-readable render of a single AgentEvent. Returns None when
    the event shouldn't emit a line (e.g. tokens are streamed inline)."""
    etype = event.get("type")
    if etype == "token":
        # Tokens stream inline without newlines — the caller writes them
        # via a separate path to avoid a trailing newline after each.
        return None
    if etype == "thinking":
        return None
    if etype == "message_start":
        return None
    if etype == "tool_call_start":
        return (
            f"\n  ↳ tool {event.get('name')} "
            f"({json.dumps(event.get('input', {}), separators=(',', ':'))})"
        )
    if etype == "tool_call_end":
        status = "ok" if event.get("ok") else "error"
        body = event.get("output") if event.get("ok") else event.get("error")
        return f"  ← {status}: {body}"
    if etype == "message_complete":
        cost = event.get("cost_usd")
        cost_str = f"  [${cost:.4f}]" if isinstance(cost, int | float) else ""
        return f"\n{'─' * 40}{cost_str}"
    if etype == "error":
        return f"\nERROR: {event.get('message')}"
    return f"[{etype}] {json.dumps(event)}"


async def _run_send(url: str, prompt: str, out: IO[str], *, pretty: bool = False) -> int:
    async with ws_connect(url) as ws:
        await ws.send(json.dumps({"type": "prompt", "content": prompt}))
        async for raw in ws:
            event: dict[str, Any] = json.loads(raw)
            if pretty:
                if event.get("type") == "token":
                    # Stream tokens inline, no newline per frame.
                    out.write(str(event.get("text", "")))
                    out.flush()
                else:
                    line = _format_pretty(event)
                    if line is not None:
                        print(line, file=out)
            else:
                print(json.dumps(event), file=out)
            if event.get("type") == "message_complete":
                return 0
            if event.get("type") == "error":
                return 1
    return 0


def find_chromium_browser(
    candidates: Sequence[str] = CHROMIUM_FLAVORED_BROWSERS,
) -> str | None:
    """Return the path to the first candidate found on PATH, or None."""
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    return None


def launch_app_window(browser: str, url: str) -> subprocess.Popen[bytes]:
    """Spawn a chromeless standalone window pointed at `url`. Detaches
    so `twrminal window` returns immediately — the window lives as long
    as the user keeps it open, decoupled from this CLI invocation."""
    return subprocess.Popen(
        [browser, f"--app={url}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "serve":
        import uvicorn

        cfg = load_settings()
        uvicorn.run(
            "twrminal.server:create_app",
            factory=True,
            host=cfg.server.host,
            port=cfg.server.port,
            log_level="info",
        )
        return 0

    if args.command == "init":
        cfg = load_settings()
        cfg.ensure_paths()
        print(f"config ready at {cfg.config_file}")
        print(f"database path {cfg.storage.db_path}")
        return 0

    if args.command == "window":
        cfg = load_settings()
        host = args.host or cfg.server.host
        port = args.port or cfg.server.port
        url = f"http://{host}:{port}/"
        browser = args.browser or find_chromium_browser()
        if browser is None:
            print(
                "twrminal window: no Chromium-flavored browser found on PATH.\n"
                "  Install one of: "
                + ", ".join(CHROMIUM_FLAVORED_BROWSERS)
                + "\n  …or pass --browser /path/to/binary.\n"
                f"  You can also open {url} in your default browser.",
                file=sys.stderr,
            )
            return 1
        launch_app_window(browser, url)
        print(f"twrminal window: opened {url} via {browser}", file=sys.stderr)
        return 0

    if args.command == "send":
        cfg = load_settings()
        host = args.host or cfg.server.host
        port = args.port or cfg.server.port
        token = args.token or (cfg.auth.token if cfg.auth.enabled else None)
        query = f"?token={token}" if token else ""
        url = f"ws://{host}:{port}/ws/sessions/{args.session}{query}"
        return asyncio.run(_run_send(url, args.message, sys.stdout, pretty=args.format == "pretty"))

    return 1
