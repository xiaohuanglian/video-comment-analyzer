# -*- coding: utf-8 -*-
"""浏览器受控回复的公共底座。

为什么要有它（2026-11-11 审计）：
`xhs_reply_sender.py` 与 `dy_reply_sender.py` 相似度 0.43（difflib 实测），
其中 `_config_debug_port` / `_connect_browser` / `_pick_context` /
登录态检查几乎逐字重复。项目还要接快手/微博/知乎/贴吧，照原样会变成
6 份拷贝，任何一处修 bug 都要改 6 遍。

边界不变：这里**只**提供连接与登录态检查，不含任何平台业务逻辑。
真正的回复流程（找评论、输入、提交、校验）仍在各平台模块内，
因为那部分差异是真实的（小红书有 xsec_token 直链，抖音靠昵称+正文定位）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

try:  # pragma: no cover - 环境缺 playwright 时由各平台给出可执行提示
    from playwright.async_api import Browser, BrowserContext, Page, async_playwright
except ImportError:  # pragma: no cover
    Browser = BrowserContext = Page = Any  # type: ignore[assignment,misc]
    async_playwright = None  # type: ignore[assignment]


class ReplySendError(RuntimeError):
    """受控回复失败（不可重试的前提不满足，或平台拒绝）。"""


def config_debug_port() -> int:
    """CDP 调试端口（默认 9222，可用 config.CDP_DEBUG_PORT 覆盖）。"""
    try:
        import config  # type: ignore

        return int(getattr(config, "CDP_DEBUG_PORT", 9222) or 9222)
    except Exception:  # noqa: BLE001 - 配置缺失时用默认端口
        return 9222


@dataclass(frozen=True)
class PlatformLoginCheck:
    """登录态判据。

    小红书与抖音的判据不同（cookie 名、期望值），但流程一致：
    取指定域下的 cookie → 找目标 name → 比对值。
    """

    domain: str
    cookie_name: str
    expected_value: str
    platform_label: str


async def connect_browser(*, platform_label: str) -> "Browser":
    """连接本机已登录的 CDP 浏览器。"""
    if async_playwright is None:
        raise ReplySendError("playwright 未安装，无法进行浏览器受控回复")
    port = config_debug_port()
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp(f"http://localhost:{port}", timeout=10000)
    except Exception as exc:
        await pw.stop()
        raise ReplySendError(
            f"无法连接本机浏览器（CDP 端口 {port}）：{exc}。"
            f"请先启动带调试端口的浏览器并登录{platform_label}"
            f"（浏览器会复用 browser_data 登录态）"
        ) from exc
    return browser


async def pick_context(browser: "Browser") -> "BrowserContext":
    """取第一个上下文（复用已登录的档案）；没有就新建。"""
    contexts = browser.contexts
    if contexts:
        return contexts[0]
    return await browser.new_context()


async def read_login_present(browser: "Browser", check: PlatformLoginCheck) -> Optional[str]:
    """返回匹配到的 cookie 值；未登录返回 None。"""
    try:
        context = await pick_context(browser)
        cookies = await context.cookies([check.domain])
    except Exception:  # noqa: BLE001 - 读 cookie 失败等同未登录
        return None
    for cookie in cookies:
        if cookie.get("name") == check.cookie_name:
            value = str(cookie.get("value") or "")
            if not check.expected_value or value == check.expected_value:
                return value
    return None


async def require_login(browser: "Browser", check: PlatformLoginCheck) -> None:
    """确认已登录；未登录抛带可执行提示的 ReplySendError。"""
    value = await read_login_present(browser, check)
    if value is None:
        raise ReplySendError(
            f"浏览器里未登录{check.platform_label}"
            f"（缺少 {check.cookie_name} 或值不符）。请在受控浏览器窗口中登录后重试"
        )


async def with_browser(
    fn: Callable[["Browser"], Awaitable[Any]],
    *,
    platform_label: str,
) -> Any:
    """连接 → 执行 → 关闭（关闭失败不影响结果）。"""
    browser = await connect_browser(platform_label=platform_label)
    try:
        return await fn(browser)
    finally:
        try:
            await browser.close()
        except Exception:  # noqa: BLE001 - 关闭失败不该覆盖主流程结果
            pass


def run_async(coro: Awaitable[Any]) -> Any:
    """同步包装：给 `asyncio.to_thread` 场景用（内部起独立事件循环）。"""
    return asyncio.run(coro)
