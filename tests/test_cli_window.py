from __future__ import annotations

from typing import Any

import pytest

from twrminal import cli


def test_find_browser_picks_first_match_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """shutil.which is called in candidate order; the first hit wins."""
    found: dict[str, str] = {"chromium": "/usr/bin/chromium"}
    monkeypatch.setattr(cli.shutil, "which", lambda name: found.get(name))
    assert (
        cli.find_chromium_browser(("google-chrome-stable", "chromium", "brave"))
        == "/usr/bin/chromium"
    )


def test_find_browser_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)
    assert cli.find_chromium_browser(("google-chrome", "brave")) is None


def test_launch_app_window_passes_app_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class FakePopen:
        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            calls.append(argv)
            self.kwargs = kwargs

    monkeypatch.setattr(cli.subprocess, "Popen", FakePopen)
    cli.launch_app_window("/usr/bin/chromium", "http://127.0.0.1:8787/")
    assert calls == [["/usr/bin/chromium", "--app=http://127.0.0.1:8787/"]]


def test_window_command_errors_without_browser(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "find_chromium_browser", lambda: None)
    rc = cli.main(["window"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no Chromium-flavored browser" in err
    # Still tells the user where they could open it manually.
    assert "http://" in err


def test_window_command_launches_when_browser_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_launch(browser: str, url: str) -> Any:
        calls.append((browser, url))
        return None

    monkeypatch.setattr(cli, "find_chromium_browser", lambda: "/usr/bin/brave")
    monkeypatch.setattr(cli, "launch_app_window", fake_launch)
    rc = cli.main(["window"])
    assert rc == 0
    assert len(calls) == 1
    browser, url = calls[0]
    assert browser == "/usr/bin/brave"
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
    monkeypatch.setattr(cli, "find_chromium_browser", lambda: "/usr/bin/chromium")
    monkeypatch.setattr(cli, "launch_app_window", fake_launch)
    rc = cli.main(["window", "--browser", "/opt/custom-chrome/chrome"])
    assert rc == 0
    assert calls[0][0] == "/opt/custom-chrome/chrome"
