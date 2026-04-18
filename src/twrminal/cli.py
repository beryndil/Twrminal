from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from typing import IO, Any

from websockets.asyncio.client import connect as ws_connect

from twrminal import __version__
from twrminal.config import load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="twrminal")
    parser.add_argument("--version", action="version", version=f"twrminal {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="Run the FastAPI server")
    sub.add_parser("init", help="Initialize config + database on disk")

    send = sub.add_parser("send", help="Send a one-shot prompt to an agent session")
    send.add_argument("--session", required=True, help="Session id")
    send.add_argument("--host", default=None, help="Server host (default: from config)")
    send.add_argument("--port", type=int, default=None, help="Server port (default: from config)")
    send.add_argument("message", help="Prompt text")

    return parser


async def _run_send(url: str, prompt: str, out: IO[str]) -> int:
    async with ws_connect(url) as ws:
        await ws.send(json.dumps({"type": "prompt", "content": prompt}))
        async for raw in ws:
            event: dict[str, Any] = json.loads(raw)
            print(json.dumps(event), file=out)
            if event.get("type") == "message_complete":
                return 0
            if event.get("type") == "error":
                return 1
    return 0


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

    if args.command == "send":
        cfg = load_settings()
        host = args.host or cfg.server.host
        port = args.port or cfg.server.port
        url = f"ws://{host}:{port}/ws/sessions/{args.session}"
        return asyncio.run(_run_send(url, args.message, sys.stdout))

    return 1
