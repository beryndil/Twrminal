from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

import tomli_w
from websockets.asyncio.client import connect as ws_connect

from bearings import __version__
from bearings.bearings_dir import pending as pending_ops
from bearings.bearings_dir.check import run_check
from bearings.bearings_dir.init_dir import init_directory
from bearings.bearings_dir.onboard import render_brief
from bearings.config import DATA_HOME, ProfileName, Settings, load_settings
from bearings.profiles import (
    apply_profile,
    available_profiles,
    merge_profile_into_toml,
)
from bearings.todo import dispatch as _todo_dispatch
from bearings.todo import register_parser as _todo_register

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


# Argparse's `_SubParsersAction` is only subscriptable at type-check
# time; runtime evaluation of `_SubParsersAction[ArgumentParser]`
# raises TypeError. Guard the alias behind TYPE_CHECKING so mypy /
# editors see the parameterized form while runtime gets the bare class.
if TYPE_CHECKING:
    _SubParsers = argparse._SubParsersAction[argparse.ArgumentParser]
else:
    _SubParsers = argparse._SubParsersAction


def _add_init_parser(sub: _SubParsers) -> None:
    init = sub.add_parser("init", help="Initialize config + database on disk")
    init.add_argument(
        "--profile",
        choices=available_profiles(),
        default=None,
        help=(
            "Permission profile to materialize into config.toml. "
            "`safe` (public default): auth on, sandbox working_dir, no "
            "~/.claude inherit, no MCP/hooks, bypassPermissions blocked. "
            "`workstation`: auth on, $HOME working_dir, MCP/hooks "
            "allowed, bypassPermissions allowed but ephemeral. "
            "`power-user`: today's defaults restored. "
            "Omit to leave config.toml untouched."
        ),
    )


def _add_window_parser(sub: _SubParsers) -> None:
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
    window.add_argument(
        "--plain",
        action="store_true",
        help=(
            "Skip Bearings' SSB customization. Firefox: drops the bundled profile "
            "(no userChrome.css collapse, uses your default profile). Chromium: "
            "drops --app=URL so the page opens in a normal browser window."
        ),
    )
    window.add_argument(
        "--profile",
        dest="profile_path",
        default=None,
        help=(
            "Path to a custom browser profile directory. Firefox: passed as "
            "--profile <path>. Chromium: passed as --user-data-dir=<path>. "
            "Mutually exclusive with --plain."
        ),
    )


def _add_send_parser(sub: _SubParsers) -> None:
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


def _add_here_parser(sub: _SubParsers) -> None:
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


def _add_pending_parser(sub: _SubParsers) -> None:
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


def _add_gc_parser(sub: _SubParsers) -> None:
    gc = sub.add_parser(
        "gc",
        help="Garbage-collect on-disk state (uploads, etc.).",
    )
    gc_sub = gc.add_subparsers(dest="gc_command", required=True)
    gc_uploads = gc_sub.add_parser(
        "uploads",
        help=(
            "Sweep the upload directory: delete UUID subdirs whose "
            "newest mtime is older than --retention-days (default: "
            "uploads.retention_days from config, 30)."
        ),
    )
    gc_uploads.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help=(
            "Override `uploads.retention_days`. UUID subdirs whose "
            "newest mtime is older than N days get pruned. 0 sweeps "
            "everything (use only after backing up)."
        ),
    )
    gc_uploads.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print which UUID subdirs WOULD be removed and how many "
            "bytes that would free, without touching anything on disk."
        ),
    )


def _add_status_parser(sub: _SubParsers) -> None:
    status = sub.add_parser(
        "status",
        help="Print server connectivity, version, and session/runner counts.",
    )
    status.add_argument("--host", default=None, help="Server host (default: from config)")
    status.add_argument("--port", type=int, default=None, help="Server port (default: from config)")
    status.add_argument(
        "--token",
        default=None,
        help="Auth token (default: from config auth.token when auth.enabled)",
    )


def _add_verify_parser(sub: _SubParsers) -> None:
    verify = sub.add_parser(
        "verify",
        help=("Print synth-gate work-evidence for an executor session (decision-discipline §4)."),
    )
    verify.add_argument("session", help="Executor session id to verify")
    verify.add_argument("--host", default=None, help="Server host (default: from config)")
    verify.add_argument("--port", type=int, default=None, help="Server port (default: from config)")
    verify.add_argument(
        "--token",
        default=None,
        help="Auth token (default: from config auth.token when auth.enabled)",
    )


def _add_log_parser(sub: _SubParsers) -> None:
    log_cmd = sub.add_parser(
        "log",
        help="Tail recent messages from a session (default: most-recently-updated).",
    )
    log_cmd.add_argument(
        "--session",
        default=None,
        help="Session id to tail. Omit to use the most-recently-updated session.",
    )
    log_cmd.add_argument(
        "--tail",
        type=int,
        default=10,
        help="Number of trailing messages to print (default: 10).",
    )
    log_cmd.add_argument("--host", default=None, help="Server host (default: from config)")
    log_cmd.add_argument(
        "--port", type=int, default=None, help="Server port (default: from config)"
    )
    log_cmd.add_argument(
        "--token",
        default=None,
        help="Auth token (default: from config auth.token when auth.enabled)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Top-level argparse builder for the `bearings` CLI.

    Each subcommand parser is wired by a focused `_add_*_parser`
    helper so this function stays a flat registration table — when a
    new subcommand lands, add the helper above and one line here."""
    parser = argparse.ArgumentParser(prog="bearings")
    parser.add_argument("--version", action="version", version=f"bearings {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="Run the FastAPI server")
    _add_init_parser(sub)
    _add_window_parser(sub)
    _add_send_parser(sub)
    _add_status_parser(sub)
    _add_verify_parser(sub)
    _add_log_parser(sub)
    _add_here_parser(sub)
    _add_pending_parser(sub)
    _todo_register(sub)
    _add_gc_parser(sub)
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


def launch_app_window(
    browser: str,
    url: str,
    *,
    plain: bool = False,
    profile_path: str | None = None,
) -> subprocess.Popen[bytes]:
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

    Two escape hatches override the SSB defaults:

    * ``plain=True`` skips Bearings' customization entirely. Firefox
      drops the bundled profile (regular default-profile window);
      Chromium drops ``--app=URL`` so the page opens in a normal
      browser window. Useful when our userChrome.css collapses
      something the user actually wants visible, or when our profile
      is wedged.
    * ``profile_path=<path>`` points at a user-supplied profile dir.
      Firefox passes it as ``--profile <path>``; Chromium maps it to
      ``--user-data-dir=<path>``. We do **not** bootstrap our
      ``user.js`` / ``userChrome.css`` into a user-supplied profile —
      the escape hatch exists so the user can use their profile as-is.

    The two flags are mutually exclusive — ``main()`` rejects the
    combination at parse time.

    The process is detached (``start_new_session``) so ``bearings window``
    returns immediately and the window's lifetime is decoupled from
    this CLI invocation.
    """
    firefox = _is_firefox_like(browser)
    if firefox:
        if plain:
            argv = [browser, "--new-window", url]
        elif profile_path is not None:
            argv = [browser, "--profile", profile_path, "--new-window", url]
        else:
            profile = _ensure_firefox_ssb_profile()
            argv = [browser, "--profile", str(profile), "--new-window", url]
    else:
        if plain:
            argv = [browser, "--new-window", url]
        elif profile_path is not None:
            argv = [browser, f"--user-data-dir={profile_path}", f"--app={url}"]
        else:
            argv = [browser, f"--app={url}"]
    return subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _write_profile(config_path: Path, profile: ProfileName) -> None:
    """Materialize a profile preset into config.toml.

    Reads the existing TOML (if any), overlays the profile's keys via
    `merge_profile_into_toml`, and writes back. Operator-edited keys
    that the profile doesn't touch survive untouched. The merge is
    section-shallow, not deeply recursive — every config section in
    Bearings is currently a flat key/value table.
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if config_path.exists():
        import tomllib

        existing = tomllib.loads(config_path.read_text())
    merged = merge_profile_into_toml(existing, apply_profile(profile))
    with config_path.open("wb") as fh:
        tomli_w.dump(merged, fh)


def _format_gate_state(cfg: Settings) -> list[str]:
    """Render a one-line-per-gate audit of the active configuration.

    Each line follows `<key> <state>` so a quick scan tells the
    operator which security knobs are open vs. closed. Used by both
    the post-init success message and the `serve` startup banner so
    the same audit text lands in both contexts.
    """
    lines: list[str] = []
    auth = cfg.auth
    lines.append(f"  auth                       {'on' if auth.enabled else 'OFF'}")
    agent = cfg.agent
    lines.append(
        f"  bypassPermissions allowed  {'yes' if agent.allow_bypass_permissions else 'no'}"
    )
    lines.append(
        f"  ~/.claude settings inherit "
        f"{'default' if agent.setting_sources is None else (agent.setting_sources or 'none')}"
    )
    lines.append(f"  MCP servers inherited      {'yes' if agent.inherit_mcp_servers else 'no'}")
    lines.append(f"  hooks inherited            {'yes' if agent.inherit_hooks else 'no'}")
    if agent.workspace_root is not None:
        lines.append(f"  workspace_root             {agent.workspace_root}")
    else:
        lines.append(f"  default working_dir        {agent.working_dir}")
    if agent.default_max_budget_usd is not None:
        lines.append(f"  per-session budget cap     ${agent.default_max_budget_usd:.2f}")
    else:
        lines.append("  per-session budget cap     uncapped")
    lines.append(f"  fs picker root             {cfg.fs.allow_root}")
    lines.append(f"  commands palette scope     {cfg.commands.scope}")
    lines.append(f"  runner idle TTL            {cfg.runner.idle_ttl_seconds:.0f}s")
    lines.append(f"  bind                       {cfg.server.host}:{cfg.server.port}")
    return lines


def _print_profile_banner(cfg: Settings, *, fh: Any) -> None:
    """Print the active permission profile + a per-gate audit.

    Visible-by-default on `bearings serve` so the operator sees their
    posture every restart. Suppressible via `profile.show_banner =
    false` for systemd-user operators who already read the journal.
    """
    name = cfg.profile.name or "(none — raw defaults)"
    bar = "─" * 60
    print(bar, file=fh)
    print(f"Bearings permission profile: {name}", file=fh)
    print(bar, file=fh)
    for line in _format_gate_state(cfg):
        print(line, file=fh)
    print(bar, file=fh)


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


def _handle_serve_command(args: argparse.Namespace) -> int:
    """Run the FastAPI server via uvicorn after the bind/auth
    interlock check (2026-04-21 security audit §6).

    Bearings has no TLS of its own; reverse-proxy users terminate
    upstream. So "public interface + no token" is equivalent to
    handing every LAN device a shell on this account. Fail at
    startup rather than discover it from access logs later."""
    import uvicorn

    cfg = load_settings()
    interlock_error = _check_bind_auth_interlock(cfg)
    if interlock_error is not None:
        print(interlock_error, file=sys.stderr)
        return 2
    if cfg.profile.show_banner:
        _print_profile_banner(cfg, fh=sys.stdout)
    # Wire a root handler BEFORE uvicorn.run so application loggers
    # (bearings.*) reach the journal. uvicorn's default LOGGING_CONFIG
    # only attaches handlers to `uvicorn`, `uvicorn.error`, and
    # `uvicorn.access`; everything else propagates to root, which has
    # no handler by default → messages hit the WARNING-level lastResort
    # and INFO/DEBUG vanish silently. Discovered while shipping the
    # ws_agent D1 diagnostic logs (plan-a-way-to-agile-pillow.md): the
    # WS-accept lines logged fine (uvicorn-owned), but the application's
    # `log.info` calls in ws_agent.py never reached journalctl. uvicorn
    # uses `disable_existing_loggers=False`, so a root handler set here
    # survives uvicorn's dictConfig and catches everything that
    # propagates up from `bearings.*` loggers.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    uvicorn.run(
        "bearings.server:create_app",
        factory=True,
        host=cfg.server.host,
        port=cfg.server.port,
        log_level="info",
    )
    return 0


def _handle_init_command(args: argparse.Namespace) -> int:
    """Materialize config + DB paths, then optionally apply the
    profile in `--profile`. Surfaces the auto-generated auth token
    so the operator can wire it into a browser bookmark / shell alias
    before the banner-on-serve reveals it again."""
    cfg = load_settings()
    cfg.ensure_paths()
    if args.profile is not None:
        _write_profile(cfg.config_file, args.profile)
        print(f"profile '{args.profile}' written to {cfg.config_file}")
        cfg = load_settings()  # reload so the printed summary reflects the write
    print(f"config ready at {cfg.config_file}")
    print(f"database path {cfg.storage.db_path}")
    if args.profile is not None:
        if cfg.auth.enabled and cfg.auth.token:
            print(f"auth token: {cfg.auth.token}")
        print()
        _print_profile_banner(cfg, fh=sys.stdout)
    return 0


def _handle_window_command(args: argparse.Namespace) -> int:
    """Launch the UI in a standalone-style browser window. Validates
    the --plain / --profile flag exclusivity, autodetects a browser
    on PATH when --browser is absent, and surfaces a paste-ready
    fallback URL when no supported browser can be located."""
    if args.plain and args.profile_path is not None:
        print(
            "bearings window: --plain and --profile are mutually exclusive.",
            file=sys.stderr,
        )
        return 2
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
    launch_app_window(browser, url, plain=args.plain, profile_path=args.profile_path)
    print(f"bearings window: opened {url} via {browser}", file=sys.stderr)
    return 0


def _handle_send_command(args: argparse.Namespace) -> int:
    """Send a one-shot prompt over the agent WS, streaming events to
    stdout. The token resolution mirrors the WS auth helpers — config
    token used only when auth is enabled."""
    cfg = load_settings()
    host = args.host or cfg.server.host
    port = args.port or cfg.server.port
    token = args.token or (cfg.auth.token if cfg.auth.enabled else None)
    query = f"?token={token}" if token else ""
    url = f"ws://{host}:{port}/ws/sessions/{args.session}{query}"
    return asyncio.run(_run_send(url, args.message, sys.stdout, pretty=args.format == "pretty"))


def _http_get_json(url: str, token: str | None) -> Any:
    """Stdlib-only GET → JSON. Avoids an httpx/requests dep in the CLI
    surface; the server is local so connection failures are the common
    hard error and we surface them with a one-line hint."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"could not reach {url}: {exc}. Is `bearings serve` running?") from exc


def _handle_status_command(args: argparse.Namespace) -> int:
    """Print server health, version, sessions count, active runners.

    Two HTTP calls (health + sessions list); intentionally no streaming
    so the command exits cleanly when piped or scripted."""
    cfg = load_settings()
    host = args.host or cfg.server.host
    port = args.port or cfg.server.port
    token = args.token or (cfg.auth.token if cfg.auth.enabled else None)
    base = f"http://{host}:{port}"
    try:
        health = _http_get_json(f"{base}/api/health", token)
        sessions = _http_get_json(f"{base}/api/sessions?limit=1000", token)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    rows = sessions if isinstance(sessions, list) else sessions.get("sessions", [])
    running = sum(1 for s in rows if s.get("kind") == "chat" and s.get("closed_at") is None)
    # Reaching this point means both /health and /sessions returned 200,
    # so the server is up and answering. The /health body itself is
    # ancillary metadata (auth on/off, data_dir) — rendered alongside
    # the OK banner rather than relied on for the health verdict.
    print(f"server  : {base}  (OK)")
    print(f"version : {health.get('version', 'unknown')}")
    print(f"auth    : {health.get('auth', 'unknown')}")
    print(f"sessions: {len(rows)} total, {running} open chat sessions")
    print(f"db_path : {cfg.storage.db_path}")
    return 0


def _handle_verify_command(args: argparse.Namespace) -> int:
    """Print synth-gate evidence for one executor session. The
    orchestrator (Dave or LLM) reads this output before toggling the
    master checklist item per `~/.claude/rules/decision-discipline.md` §4."""
    cfg = load_settings()
    host = args.host or cfg.server.host
    port = args.port or cfg.server.port
    token = args.token or (cfg.auth.token if cfg.auth.enabled else None)
    base = f"http://{host}:{port}"
    try:
        evidence = _http_get_json(f"{base}/api/sessions/{args.session}/work_evidence", token)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"session : {evidence.get('session_id', args.session)}")
    linked = evidence.get("linked_checklist")
    if linked:
        check = linked.get("checked_at") or "(unchecked)"
        block = f"  blocked: {linked['blocked_reason_text']}" if linked.get("blocked_at") else ""
        print(f"item    : #{linked['item_id']} {linked.get('label', '')}  [{check}]{block}")
    else:
        print("item    : (no linked checklist item)")
    print("tools   :")
    for t in evidence.get("tool_summary", []):
        marker = "" if t["failed"] == 0 else f"  ⚠ {t['failed']} failed"
        print(f"  {t['name']:14}  ok={t['ok']:3}  fail={t['failed']:3}{marker}")
    files = evidence.get("files_modified", [])
    if files:
        print(f"files   : {len(files)} modified")
        for p in files[-10:]:
            print(f"  {p}")
        if len(files) > 10:
            print(f"  ... ({len(files) - 10} more)")
    commits = evidence.get("bash_commits", [])
    if commits:
        print(f"commits : {len(commits)}")
        for c in commits[-5:]:
            print(f"  {c}")
    failures = evidence.get("bash_failures", [])
    if failures:
        print(f"bash failures: {len(failures)}")
        for f in failures[-3:]:
            cmd = f["cmd"][:80]
            print(f"  ! {cmd}")
    snippet = evidence.get("last_assistant_snippet")
    if snippet:
        print(f"last say:\n  {snippet}")
    return 0


def _handle_log_command(args: argparse.Namespace) -> int:
    """Tail the last N messages from one session. Default session is
    the most-recently-updated row (sessions are returned newest-first
    by the list endpoint)."""
    cfg = load_settings()
    host = args.host or cfg.server.host
    port = args.port or cfg.server.port
    token = args.token or (cfg.auth.token if cfg.auth.enabled else None)
    base = f"http://{host}:{port}"
    try:
        sid = args.session
        if sid is None:
            sessions = _http_get_json(f"{base}/api/sessions?limit=1", token)
            rows = sessions if isinstance(sessions, list) else sessions.get("sessions", [])
            if not rows:
                print("(no sessions)", file=sys.stderr)
                return 1
            sid = rows[0]["id"]
        msgs = _http_get_json(f"{base}/api/sessions/{sid}/messages?limit={args.tail}", token)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    items = msgs if isinstance(msgs, list) else msgs.get("messages", [])
    print(f"session : {sid}  ({len(items)} messages)")
    for m in items:
        role = m.get("role", "?")
        ts = m.get("created_at", "")
        body = (m.get("content") or "").strip().splitlines()
        head = body[0] if body else ""
        if len(head) > 100:
            head = head[:97] + "..."
        print(f"  {ts}  {role:9}  {head}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch the parsed CLI command to its per-subcommand handler.

    Adding a new subcommand: wire the parser in `build_parser()`,
    add a `_handle_*_command` (or reuse the existing `_run_*`
    helpers for the directory/checklist subtrees), and register the
    pair below. Unknown commands return exit `1` so a future parser
    drift surfaces visibly rather than silently no-op'ing."""
    args = build_parser().parse_args(argv)
    handlers: dict[str, Callable[[argparse.Namespace], int]] = {
        "serve": _handle_serve_command,
        "init": _handle_init_command,
        "window": _handle_window_command,
        "send": _handle_send_command,
        "status": _handle_status_command,
        "verify": _handle_verify_command,
        "log": _handle_log_command,
        "here": _run_here,
        "pending": _run_pending,
        "todo": _todo_dispatch,
        "gc": _run_gc,
    }
    handler = handlers.get(args.command)
    if handler is None:
        return 1
    return handler(args)


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


def _format_bytes(n: int) -> str:
    """Render a byte count as a short human string (B/KB/MB/GB).

    Mirrors the frontend's `formatBytes` exactly enough for the
    summary line — picks a single unit, no decimal places below 1 KB.
    Kept local because nothing else server-side currently needs it.
    """
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(n)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.1f} {units[idx]}"


def _run_gc(args: argparse.Namespace) -> int:
    """Drive `bearings gc <subcommand>`.

    The sweep is intentionally read-only when `--dry-run` is set so
    the operator can preview an aggressive `--retention-days 0` before
    committing. Output format is one path per line (so it can be fed
    to `xargs ls -ld` for inspection) plus a final summary line.
    """
    if args.gc_command != "uploads":
        return 1

    import time

    from bearings.uploads_gc import find_expired_subdirs, prune_subdirs

    cfg = load_settings()
    retention = (
        args.retention_days if args.retention_days is not None else cfg.uploads.retention_days
    )
    if retention < 0:
        print(
            f"bearings gc uploads: --retention-days must be ≥ 0 (got {retention}).",
            file=sys.stderr,
        )
        return 2

    upload_dir = Path(cfg.uploads.upload_dir)
    cutoff = time.time() - retention * 86400
    expired = find_expired_subdirs(upload_dir, cutoff_epoch=cutoff)

    if not expired:
        print(f"bearings gc uploads: nothing to prune under {upload_dir}")
        print(f"  retention: {retention}d, scanned {upload_dir}")
        return 0

    total_bytes = sum(e.size_bytes for e in expired)
    verb = "would prune" if args.dry_run else "pruning"
    print(f"bearings gc uploads: {verb} {len(expired)} subdir(s) under {upload_dir}")
    for entry in expired:
        age_days = (time.time() - entry.newest_mtime) / 86400
        print(f"  {entry.path}  ({_format_bytes(entry.size_bytes)}, {age_days:.1f}d old)")

    if args.dry_run:
        print(
            f"  total: {len(expired)} subdir(s), "
            f"{_format_bytes(total_bytes)} (dry-run, nothing removed)"
        )
        return 0

    result = prune_subdirs(expired)
    print(f"  removed: {result.removed} subdir(s), freed {_format_bytes(result.freed_bytes)}")
    if result.errors:
        # Surface each failure on stderr so a recurring permissions
        # problem is visible across runs without parsing the success
        # summary. Exit 1 if any directory failed to clean up — the
        # caller's cron job should retry rather than mark success.
        for path, msg in result.errors:
            print(f"  failed to remove {path}: {msg}", file=sys.stderr)
        return 1
    return 0
