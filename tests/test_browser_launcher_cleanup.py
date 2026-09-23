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