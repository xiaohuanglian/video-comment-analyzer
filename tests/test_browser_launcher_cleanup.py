# -*- coding: utf-8 -*-
"""Browser launcher self-healing for leftover Chrome profile locks."""

from __future__ import annotations

import os

from tools.browser_launcher import BrowserLauncher


def test_clear_stale_profile_locks_removes_singletons(tmp_path):
    profile = tmp_path / "cdp_bili_user_data_dir"
    profile.mkdir()
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "Other"):
        (profile / name).write_text("x")
    # make SingletonLock a symlink like Chromium does on macOS
    (profile / "SingletonLock").unlink()
    os.symlink("host-1234", profile / "SingletonLock")

    BrowserLauncher().clear_stale_profile_locks(str(profile))

    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        assert not (profile / name).exists()
    # unrelated files must be left alone
    assert (profile / "Other").exists()


def test_clear_stale_profile_locks_is_safe_when_missing(tmp_path):
    # no exception when the directory has no lock files
    BrowserLauncher().clear_stale_profile_locks(str(tmp_path / "nope"))


def test_kill_stale_browsers_no_match_returns_zero(tmp_path):
    assert BrowserLauncher().kill_stale_browsers(str(tmp_path / "unique-profile-xyz")) == 0


class _ExitedProcess:
    returncode = 1

    def poll(self):
        return 1


def test_wait_for_browser_ready_fails_fast_on_early_exit():
    launcher = BrowserLauncher()
    launcher.browser_process = _ExitedProcess()
    # free port so the socket check never succeeds; early exit must return quickly
    import time as _time

    started = _time.time()
    ready = launcher.wait_for_browser_ready(port_free_guard(), timeout=30)
    assert ready is False
    assert _time.time() - started < 5  # did not wait the full 30s


def port_free_guard() -> int:
    import socket as _socket

    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]