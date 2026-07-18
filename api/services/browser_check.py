# -*- coding: utf-8 -*-
"""Lightweight browser readiness checks for the Web UI."""

from __future__ import annotations

from typing import Any, Dict

from tools.browser_launcher import BrowserLauncher


def probe_browser_launch() -> Dict[str, Any]:
    """Check that a supported browser is installed (do not launch a visible window)."""
    launcher = BrowserLauncher()
    paths = launcher.detect_browser_paths()
    if not paths:
        return {
            "ok": False,
            "browser": "",
            "error": "未检测到 Chrome 或 Edge，请先安装 Google Chrome。",
        }

    name, version = launcher.get_browser_info(paths[0])
    browser_info = f"{name} {version}".strip()
    return {"ok": True, "browser": browser_info, "error": ""}
