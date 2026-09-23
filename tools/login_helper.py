# -*- coding: utf-8 -*-
"""Shared, resilient login helpers for platform crawlers.

The original per-platform QR flows clicked brittle homepage selectors and
called ``sys.exit()`` on failure, which surfaced as confusing "browser failed"
errors. These helpers instead:

* open the platform's login page (best effort),
* render the QR in the terminal when it can be found,
* poll the login state until the user logs in (the visible browser window is
  enough — the user can scan or type there),
* raise a clear error on timeout instead of killing the process.
"""

from __future__ import annotations

import asyncio
import functools
from typing import Awaitable, Callable, Iterable, Optional

from playwright.async_api import BrowserContext, Page

from tools import utils

# Default wait for a human to complete login in the browser window.
DEFAULT_LOGIN_TIMEOUT = 300
_LOGIN_POLL_SECONDS = 2.0


async def has_login_cookie(
    browser_context: BrowserContext,
    cookie_names: Iterable[str],
) -> bool:
    """True when any of ``cookie_names`` is present in the browser context."""
    try:
        current = await browser_context.cookies()
        _, cookie_dict = utils.convert_cookies(current)
    except Exception:
        return False
    return any(cookie_dict.get(name) for name in cookie_names)


async def show_qrcode_best_effort(page: Page, selectors: Iterable[str]) -> bool:
    """Try several selectors and render the first QR found in the terminal."""
    for selector in selectors:
        try:
            if selector.startswith("canvas"):
                b64 = await utils.find_qrcode_img_from_canvas(page, selector)
            else:
                b64 = await utils.find_login_qrcode(page, selector=selector)
        except Exception:
            b64 = ""
        if b64:
            try:
                loop = asyncio.get_running_loop()
                loop.run_in_executor(None, functools.partial(utils.show_qrcode, b64))
            except Exception:
                pass
            return True
    return False


async def wait_for_login(
    is_logged_in: Callable[[], Awaitable[bool]],
    *,
    timeout: int = DEFAULT_LOGIN_TIMEOUT,
    label: str = "登录",
) -> None:
    """Poll ``is_logged_in`` until it returns True or the timeout elapses."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(30, int(timeout))
    while loop.time() < deadline:
        try:
            if await is_logged_in():
                return
        except Exception:
            pass
        await asyncio.sleep(_LOGIN_POLL_SECONDS)
    raise RuntimeError(
        f"{label}超时：请在自动打开的浏览器窗口中完成登录后重试"
        f"（若窗口未弹出，可改用 cookie 登录）"
    )


async def goto_login_page(page: Page, url: str, *, label: str = "登录页") -> None:
    """Best-effort navigation to a login URL; never fatal."""
    if not url:
        return
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as exc:  # noqa: BLE001
        utils.logger.warning(f"[login_helper] open {label} failed: {exc}; 请手动在浏览器窗口中登录")