from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import IO, Any

from websockets.asyncio.client import connect as ws_connect

from bearings import __version__
from bearings.bearings_dir import pending as pending_ops
from bearings.bearings_dir.check import run_check
from bearings.bearings_dir.init_dir import init_directory
from bearings.bearings_dir.onboard import render_brief
from bearings.config import DATA_HOME, Settings, load_settings

# Hostnames / IPs that the interlock treats as loopback-only. Anything
# else (wildcard binds like `0.0.0.0` / `::`, a LAN address, an
# externally-routable IP) has to be paired with `auth.enabled = true`
# or the server refuses to start. `::` covers both "all IPv6" and
# "any IPv6 loopback" ambiguity the same way `0.0.0.0` does for v4 —
# we treat the wildcard forms as non-loopback because they'll pick up
# a real interface too. 2026-04-21 security audit §6 (2026-04-23 fix).
_LOOPBACK_BINDS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1", "::ffff:127.0.0.1"})

# Autodetect order for the `window` subcommand. Firefox-family
# binaries come first because Chromium on Hyprland silently drops
# external file drops (dragenter/dragover fire; drop does not —
# confirmed via server-side DND_PROBE instrumentation on 2026-04-24).
# Firefox handles the same wl_data_device exchange correctly on the
# same compositor, so we prefer it when both are installed. Chromium
# stays on the list as a fallback — the paste / Browse button /
# zenity attach-file paths still work there for users without Firefox.
FIREFOX_BROWSERS: tuple[str, ...] = (
    "firefox",
    "firefox-esr",
    "firefox-developer-edition",
    "firefox-nightly",
    "librewolf",
    "waterfox",
    "floorp",
)

# Chromium-family binaries. All accept --app=URL to launch a
# chromeless standalone window.
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

# Combined autodetect order — Firefox wins when both are present.
SUPPORTED_BROWSERS: tuple[str, ...] = FIREFOX_BROWSERS + CHROMIUM_FLAVORED_BROWSERS

# Firefox profile directory owned by Bearings. Created on first
# `bearings window` launch and kept stable across runs so cache /
# cookies / session history survive. Kept separate from the user's
# regular Firefox profile so our userChrome.css customizations don't
# interfere with normal browsing.
FIREFOX_SSB_PROFILE_DIR: Path = DATA_HOME / "firefox-ssb"

# Preferences that make userChrome.css actually load (legacy stylesheet
# customization is off by default since Firefox 69). Written once on
# first profile bootstrap; subsequent `bearings window` launches leave
# this file alone so a user can add prefs without getting stomped.
_FIREFOX_USER_JS = """\
// Bearings SSB profile — written on first bootstrap, safe to edit.
// `bearings window` will not overwrite this file once it exists.
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("datareporting.policy.firstRunURL", "");
"""

# userChrome.css collapses the tab strip, nav bar, and bookmarks
# toolbar so the Bearings UI fills the window — reproduces the old
# Chrome `--app` SSB visual feel. Also written once; user edits are
# preserved across launches.
_FIREFOX_USERCHROME_CSS = """\
/* Bearings SSB profile — hide Firefox chrome so the Bearings UI looks
 * like a native app window. Safe to edit locally; `bearings window`
 * will not overwrite this file once it exists. */
#TabsToolbar,
#nav-bar,
#PersonalToolbar {
  visibility: collapse !important;
}
"""


def _ensure_firefox_ssb_profile() -> Path:
    """Create the bearings-owned Firefox profile if missing.

    Writes ``user.js`` and ``chrome/userChrome.css`` on first call.
    Subsequent calls are no-ops when the files already exist, so a
    user who tweaks the CSS (wider hide rules, a titlebar fixup, a
    custom accent color) keeps their edits across launches.

    Idempotent: safe to call on every ``bearings window`` invocation.
    """
    profile_dir = FIREFOX_SSB_PROFILE_DIR
    profile_dir.mkdir(parents=True, exist_ok=True)
    chrome_dir = profile_dir / "chrome"
    chrome_dir.mkdir(exist_ok=True)
    userchrome = chrome_dir / "userChrome.css"
    if not userchrome.exists():
        userchrome.write_text(_FIREFOX_USERCHROME_CSS)
    user_js = profile_dir / "user.js"
    if not user_js.exists():
        user_js.write_text(_FIREFOX_USER_JS)
    return profile_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bearings")
    parser.add_argument("--version", action="version", version=f"bearings {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="Run the FastAPI server")
    sub.add_parser("init", help="Initialize config + database on disk")

    window = sub.add_parser(
        "window",
        help="Open the UI in a standalone browser window (Firefox preferred, Chromium fallback)",
    )
    window.add_argument("--host", default=None, help="Server host (default: from config)")
    window.add_argument("--port", type=int, default=None, help="Server port (default: from config)")
    window.add_argument(
        "--browser",
        default=None,
        help="Path to a Firefox- or Chromium-family browser binary. Defaults to autodetect.",
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

    here = sub.add_parser(
        "here",
        help="Per-directory `.bearings/` context (init, check).",
    )
    here_sub = here.add_subparsers(dest="here_command", required=True)
    here_init = here_sub.add_parser(
        "init", help="Run onboarding ritual and write .bearings/ to CWD"
    )
    here_init.add_argument(
        "--dir",
        default=None,
        help="Target directory (default: current working directory)",
    )
    here_check = here_sub.add_parser(
        "check",
        help="Re-validate environment + git state, bump state.toml.last_validated",
    )
    here_check.add_argument(
        "--dir",
        default=None,
        help="Target directory (default: current working directory)",
    )

    pending = sub.add_parser(
        "pending",
        help="Manage in-flight operations in .bearings/pending.toml",
    )
    pending_sub = pending.add_subparsers(dest="pending_command", required=True)
    p_add = pending_sub.add_parser("add", help="Add or update a pending operation")
    p_add.add_argument("name", help="Unique operation name")
    p_add.add_argument("--description", default="", help="Human-readable description (≤500 chars)")
    p_add.add_argument(
        "--command",
        dest="op_command",
        default=None,
        help="Command that would resolve this op (≤2048 chars)",
    )
    p_add.add_argument(
        "--dir",
        default=None,
        help="Target directory (default: current working directory)",
    )
    p_resolve = pending_sub.add_parser("resolve", help="Remove a pending operation")
    p_resolve.add_argument("name", help="Name of the operation to resolve")
    p_resolve.add_argument(
        "--dir",
        default=None,
        help="Target directory (default: current working directory)",
    )
    p_list = pending_sub.add_parser("list", help="List pending operations (oldest first)")
    p_list.add_argument(
        "--dir",
        default=None,
        help="Target directory (default: current working directory)",
    )

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


def find_browser(
    candidates: Sequence[str] = SUPPORTED_BROWSERS,
) -> str | None:
    """Return the path to the first candidate found on PATH, or None.

    The default candidate order is Firefox-family first, Chromium
    fallback second — see SUPPORTED_BROWSERS for the rationale.
    """
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    return None


def _is_firefox_like(browser_path: str) -> bool:
    """True when the binary basename matches a Firefox-family browser.

    Match is substring-based so wrappers like ``/opt/firefox/firefox-bin``
    or ``librewolf-stable`` still resolve correctly. Unknown names fall
    through to the Chromium --app path, preserving legacy behavior for
    anyone pointing --browser at a custom Chrome wrapper.
    """
    name = Path(browser_path).name.lower()
    return any(fam in name for fam in ("firefox", "librewolf", "waterfox", "floorp"))


def launch_app_window(browser: str, url: str) -> subprocess.Popen[bytes]:
    """Spawn a standalone browser window pointed at `url` and detach.

    Firefox-family browsers get a bearings-owned SSB profile (via
    ``--profile <dir>``) plus ``--new-window URL`` — the profile's
    ``userChrome.css`` collapses tabs/nav/bookmarks so the window
    looks like the old Chrome ``--app`` SSB. The profile is bootstrapped
    lazily on first launch and never overwrites user edits afterward.

    Chromium-family browsers get ``--app=URL`` (native chromeless SSB)
    for users without Firefox. The flag split exists because Chromium
    on Hyprland silently drops external file drops — Firefox is the
    default launcher so drag-and-drop file attachments survive the
    composer path. See TODO.md 2026-04-24.

    The process is detached (``start_new_session``) so ``bearings window``
    returns immediately and the window's lifetime is decoupled from
    this CLI invocation.
    """
    if _is_firefox_like(browser):
        profile = _ensure_firefox_ssb_profile()
        argv = [browser, "--profile", str(profile), "--new-window", url]
    else:
        argv = [browser, f"--app={url}"]
    return subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _check_bind_auth_interlock(cfg: Settings) -> str | None:
    """Return an error message when `server.host` exposes Bearings
    beyond loopback with no auth token, otherwise `None`.

    Callable from `main()` and from tests without starting uvicorn.
    Scoped to what Bearings itself can verify at boot — a reverse
    proxy terminating TLS + auth upstream is a legitimate pattern
    but requires the operator to flip `auth.enabled = true` so the
    process-local gate matches reality.
    """
    host = cfg.server.host.strip()
    if host in _LOOPBACK_BINDS:
        return None
    if cfg.auth.enabled and cfg.auth.token:
        return None
    return (
        f"bearings serve: refusing to bind {host!r} without auth. "
        'Set `auth.enabled = true` and `auth.token = "..."` in config.toml, '
        "or bind a loopback address (127.0.0.1 / ::1 / localhost). "
        "Security audit §6 (2026-04-21)."
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "serve":
        import uvicorn

        cfg = load_settings()
        # 2026-04-21 security audit §6: refuse to expose Bearings on a
        # non-loopback interface with no auth gate. Bearings has no
        # TLS of its own (yet — reverse-proxy users terminate upstream),
        # so "public interface + no token" is equivalent to handing
        # every LAN device a shell on this account. Fail at startup
        # rather than discover it from access logs later.
        interlock_error = _check_bind_auth_interlock(cfg)
        if interlock_error is not None:
            print(interlock_error, file=sys.stderr)
            return 2
        uvicorn.run(
            "bearings.server:create_app",
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
        browser = args.browser or find_browser()
        if browser is None:
            print(
                "bearings window: no supported browser found on PATH.\n"
                "  Install one of: "
                + ", ".join(SUPPORTED_BROWSERS)
                + "\n  …or pass --browser /path/to/binary.\n"
                f"  You can also open {url} in your default browser.",
                file=sys.stderr,
            )
            return 1
        launch_app_window(browser, url)
        print(f"bearings window: opened {url} via {browser}", file=sys.stderr)
        return 0

    if args.command == "send":
        cfg = load_settings()
        host = args.host or cfg.server.host
        port = args.port or cfg.server.port
        token = args.token or (cfg.auth.token if cfg.auth.enabled else None)
        query = f"?token={token}" if token else ""
        url = f"ws://{host}:{port}/ws/sessions/{args.session}{query}"
        return asyncio.run(_run_send(url, args.message, sys.stdout, pretty=args.format == "pretty"))

    if args.command == "here":
        return _run_here(args)

    if args.command == "pending":
        return _run_pending(args)

    return 1


def _resolve_dir(raw: str | None) -> Path:
    """Resolve the `--dir` CLI flag to an absolute path. None → CWD."""
    return Path(raw).resolve() if raw else Path.cwd().resolve()


def _run_here(args: argparse.Namespace) -> int:
    target = _resolve_dir(args.dir)
    if args.here_command == "init":
        brief, root = init_directory(target)
        print(render_brief(brief))
        print()
        print(f"Wrote .bearings/ to {root}")
        return 0
    if args.here_command == "check":
        try:
            state = run_check(target)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        dirty = "dirty" if state.dirty else "clean"
        branch = state.branch or "(detached)"
        print(f"Revalidated {target}: branch {branch}, {dirty}.")
        print(f"last_validated = {state.environment.last_validated.isoformat()}")
        for note in state.environment.notes:
            print(f"  note: {note}")
        return 0
    return 1


def _run_pending(args: argparse.Namespace) -> int:
    target = _resolve_dir(args.dir)
    if args.pending_command == "add":
        op = pending_ops.add(
            target,
            args.name,
            description=args.description,
            command=args.op_command,
        )
        print(f"Pending: {op.name} (started {op.started.isoformat()})")
        return 0
    if args.pending_command == "resolve":
        removed = pending_ops.resolve(target, args.name)
        if removed is None:
            print(f"No pending op named {args.name!r}.", file=sys.stderr)
            return 1
        print(f"Resolved: {removed.name}")
        return 0
    if args.pending_command == "list":
        ops = pending_ops.list_ops(target)
        if not ops:
            print("(no pending operations)")
            return 0
        for op in ops:
            desc = f" — {op.description}" if op.description else ""
            print(f"  {op.started.isoformat()}  {op.name}{desc}")
        return 0
    return 1
