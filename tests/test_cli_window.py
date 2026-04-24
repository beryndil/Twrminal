from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bearings import cli


def test_find_browser_picks_first_match_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """shutil.which is called in candidate order; the first hit wins."""
    found: dict[str, str] = {"chromium": "/usr/bin/chromium"}
    monkeypatch.setattr(cli.shutil, "which", lambda name: found.get(name))
    assert cli.find_browser(("firefox", "chromium", "brave")) == "/usr/bin/chromium"


def test_find_browser_prefers_firefox_over_chrome(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the default SUPPORTED_BROWSERS order, Firefox wins when
    both Firefox and a Chromium-family browser are installed —
    Chromium on Hyprland drops external file drops silently, so we
    route users to Firefox by default."""
    found: dict[str, str] = {
        "firefox": "/usr/bin/firefox",
        "google-chrome-stable": "/usr/bin/google-chrome-stable",
    }
    monkeypatch.setattr(cli.shutil, "which", lambda name: found.get(name))
    assert cli.find_browser() == "/usr/bin/firefox"


def test_find_browser_falls_back_to_chromium(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no Firefox binary is on PATH, autodetect keeps working by
    picking the first Chromium-family hit."""
    found: dict[str, str] = {"chromium": "/usr/bin/chromium"}
    monkeypatch.setattr(cli.shutil, "which", lambda name: found.get(name))
    assert cli.find_browser() == "/usr/bin/chromium"


def test_find_browser_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)
    assert cli.find_browser(("firefox", "google-chrome")) is None


def test_launch_app_window_uses_new_window_for_firefox(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Firefox-family binaries get --profile <dir> --new-window URL so
    the bearings-owned SSB profile (tabs/nav hidden via userChrome.css)
    is what the user sees — reproduces the old Chrome --app SSB feel."""
    calls: list[list[str]] = []

    class FakePopen:
        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            calls.append(argv)
            self.kwargs = kwargs

    profile_dir = tmp_path / "firefox-ssb"
    monkeypatch.setattr(cli, "FIREFOX_SSB_PROFILE_DIR", profile_dir)
    monkeypatch.setattr(cli.subprocess, "Popen", FakePopen)
    cli.launch_app_window("/usr/bin/firefox", "http://127.0.0.1:8787/")
    assert calls == [
        [
            "/usr/bin/firefox",
            "--profile",
            str(profile_dir),
            "--new-window",
            "http://127.0.0.1:8787/",
        ]
    ]
    # Profile is bootstrapped as a side effect of the launch.
    assert (profile_dir / "user.js").exists()
    assert (profile_dir / "chrome" / "userChrome.css").exists()


def test_launch_app_window_uses_app_flag_for_chromium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chromium-family binaries keep the legacy --app=URL launch so
    users without Firefox still get a chromeless standalone window."""
    calls: list[list[str]] = []

    class FakePopen:
        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            calls.append(argv)
            self.kwargs = kwargs

    monkeypatch.setattr(cli.subprocess, "Popen", FakePopen)
    cli.launch_app_window("/usr/bin/chromium", "http://127.0.0.1:8787/")
    assert calls == [["/usr/bin/chromium", "--app=http://127.0.0.1:8787/"]]


def test_launch_app_window_recognizes_firefox_wrappers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Custom Firefox builds (firefox-bin, firefox-esr, librewolf, etc.)
    still take the --profile/--new-window path — matching is substring-
    based on the binary basename so wrappers and distro-renames resolve."""
    calls: list[list[str]] = []

    class FakePopen:
        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            calls.append(argv)
            self.kwargs = kwargs

    monkeypatch.setattr(cli, "FIREFOX_SSB_PROFILE_DIR", tmp_path / "firefox-ssb")
    monkeypatch.setattr(cli.subprocess, "Popen", FakePopen)
    cli.launch_app_window("/opt/firefox/firefox-bin", "http://127.0.0.1:8787/")
    cli.launch_app_window("/usr/bin/librewolf", "http://127.0.0.1:8787/")
    # Each Firefox-family argv is [bin, --profile, <dir>, --new-window, url]
    assert calls[0][1] == "--profile"
    assert calls[0][3] == "--new-window"
    assert calls[1][1] == "--profile"
    assert calls[1][3] == "--new-window"


def test_firefox_ssb_profile_bootstrap_creates_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """First call writes user.js + chrome/userChrome.css with the
    legacy-stylesheet pref and the tabs/nav-collapse rules."""
    profile_dir = tmp_path / "firefox-ssb"
    monkeypatch.setattr(cli, "FIREFOX_SSB_PROFILE_DIR", profile_dir)

    result = cli._ensure_firefox_ssb_profile()

    assert result == profile_dir
    user_js = (profile_dir / "user.js").read_text()
    assert "toolkit.legacyUserProfileCustomizations.stylesheets" in user_js
    userchrome = (profile_dir / "chrome" / "userChrome.css").read_text()
    assert "#TabsToolbar" in userchrome
    assert "#nav-bar" in userchrome


def test_firefox_ssb_profile_bootstrap_preserves_user_edits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A user who tweaks userChrome.css (wider hide rules, titlebar
    fixup, custom accent) keeps their edits across subsequent launches.
    The bootstrap only writes files when they are absent."""
    profile_dir = tmp_path / "firefox-ssb"
    chrome_dir = profile_dir / "chrome"
    chrome_dir.mkdir(parents=True)
    custom_css = "/* user's hand-tuned rules */\n#titlebar { display: none !important; }\n"
    (chrome_dir / "userChrome.css").write_text(custom_css)
    custom_js = '// user pref\nuser_pref("browser.startup.page", 0);\n'
    (profile_dir / "user.js").write_text(custom_js)

    monkeypatch.setattr(cli, "FIREFOX_SSB_PROFILE_DIR", profile_dir)
    cli._ensure_firefox_ssb_profile()

    assert (chrome_dir / "userChrome.css").read_text() == custom_css
    assert (profile_dir / "user.js").read_text() == custom_js


def test_window_command_errors_without_browser(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "find_browser", lambda: None)
    rc = cli.main(["window"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no supported browser" in err
    # Still tells the user where they could open it manually.
    assert "http://" in err


def test_window_command_launches_when_browser_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_launch(browser: str, url: str) -> Any:
        calls.append((browser, url))
        return None

    monkeypatch.setattr(cli, "find_browser", lambda: "/usr/bin/firefox")
    monkeypatch.setattr(cli, "launch_app_window", fake_launch)
    rc = cli.main(["window"])
    assert rc == 0
    assert len(calls) == 1
    browser, url = calls[0]
    assert browser == "/usr/bin/firefox"
    assert url.startswith("http://")
    assert url.endswith("/")


def test_window_command_honors_browser_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--browser overrides autodetect, so the CLI still works when the
    user has a non-standard binary (e.g. ungoogled-chromium in /opt)."""
    calls: list[tuple[str, str]] = []

    def fake_launch(browser: str, url: str) -> Any:
        calls.append((browser, url))
        return None

    # Autodetect would succeed, but --browser must take precedence.
    monkeypatch.setattr(cli, "find_browser", lambda: "/usr/bin/firefox")
    monkeypatch.setattr(cli, "launch_app_window", fake_launch)
    rc = cli.main(["window", "--browser", "/opt/custom-chrome/chrome"])
    assert rc == 0
    assert calls[0][0] == "/opt/custom-chrome/chrome"
