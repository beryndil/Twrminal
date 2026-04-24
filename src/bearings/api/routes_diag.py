"""
Ad-hoc browser-side diagnostic sink.

Dave refuses to open DevTools (2026-04-23 session). To verify what a
real browser loaded — CSS bundle hash, computed `backdrop-filter`,
resolved body `background-image`, active `data-theme` — without making
him copy-paste from a devtools console, we add:

1. A small inline reporter in `app.html` that runs on page load and
   POSTs a snapshot of those values here.
2. This endpoint, which appends the snapshot one-line-JSON per call
   to a well-known path so the agent (or Dave) can `tail` it.

This is deliberately not a permanent feature — it's a diagnostic that
can be ripped out once the theming investigation closes. The log path
lives under `/tmp` so it auto-clears on reboot and doesn't pollute the
user's XDG dirs.

Security posture: the app binds to 127.0.0.1 only (per v0.1.0 config
invariant), so an endpoint that accepts arbitrary JSON and writes to
disk stays contained to Dave's own machine. We still cap body size and
reject non-JSON to avoid being a sloppy drop-anything log sink.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["diag"])

# Fixed path — predictable for `tail -f`, survives until reboot.
LOG_PATH = Path("/tmp/bearings-theme-diag.log")
MAX_BYTES = 8_192  # plenty for a key/value snapshot; rejects anything pathological


@router.post("/diag/theme")
async def log_theme_diag(request: Request) -> dict[str, str]:
    raw = await request.body()
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="diag payload too large")
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=400, detail=f"not json: {err}") from err
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    # Tag server-side wall-clock so we can line up multiple reloads in
    # the log without relying on the browser's Date.now().
    payload["server_ts"] = datetime.now(UTC).isoformat(timespec="seconds")

    # One-line JSON per entry so `tail`/`grep` stay useful.
    line = json.dumps(payload, ensure_ascii=False)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return {"status": "ok", "path": str(LOG_PATH)}
