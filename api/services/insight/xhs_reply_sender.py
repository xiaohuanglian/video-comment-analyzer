# -*- coding: utf-8 -*-
"""小红书评论区受控回复：CDP 浏览器内仿人工操作发送。

流程（全部在已登录的浏览器里完成，AI 不产生内容，只执行已审核文本）：
1. 通过 CDP 连接本机浏览器（需已登录小红书，见 config.CDP_DEBUG_PORT）
2. 打开目标笔记页 ``https://www.xiaohongshu.com/explore/<note_id>``
3. 在评论区滚动定位目标评论（优先 ``#comment-<id>``，退化用锚点滚动）
4. 点击该评论的「回复」，在 contenteditable 输入框里逐字输入（随机延迟）
5. 提交并确认成功（页面出现我们发送的文本）

失败时抛 :class:`ReplySendError`，由 reply_runner 记录并继续其余条目。
"""

from __future__ import annotations

import asyncio
import random
from typing import Optional

from tools import utils

try:  # playwright is a hard dependency of the project already
    from playwright.async_api import Browser, BrowserContext, Page, async_playwright
except Exception:  # pragma: no cover - tests run without browser
    async_playwright = None  # type: ignore[assignment]

from .reply_sender import ReplySendError

_XHS_NOTE_URL = "https://www.xiaohongshu.com/explore/{note_id}"
_LOGIN_COOKIE_NAMES = ("web_session", "a1")
_PAGE_TIMEOUT_MS = 30000
_MAX_SCROLL_ROUNDS = 12


def _config_debug_port() -> int:
    try:
        import config  # type: ignore

        return int(getattr(config, "CDP_DEBUG_PORT", 9222) or 9222)
    except Exception:
        return 9222


async def _connect_browser() -> Browser:
    """连接本机 CDP 浏览器（须已启动且登录小红书）。"""
    if async_playwright is None:
        raise ReplySendError("playwright 未安装，无法进行浏览器受控回复")
    port = _config_debug_port()
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp(
            f"http://localhost:{port}", timeout=10000
        )
    except Exception as exc:
        await pw.stop()
        raise ReplySendError(
            f"无法连接本机浏览器（CDP 端口 {port}）：{exc}。"
            f"请先启动带调试端口的浏览器并登录小红书（浏览器会复用 browser_data 登录态）"
        ) from exc
    return browser


async def _pick_context(browser: Browser) -> BrowserContext:
    contexts = browser.contexts
    if contexts:
        return contexts[0]
    return await browser.new_context()


async def _check_login(context: BrowserContext) -> None:
    cookies = await context.cookies()
    names = {c.get("name") for c in cookies}
    if not any(n in names for n in _LOGIN_COOKIE_NAMES):
        raise ReplySendError(
            "浏览器里没有小红书登录态（缺少 web_session cookie）。"
            "请在该浏览器中登录小红书后重试"
        )


async def _human_pause(lo: float = 0.6, hi: float = 2.2) -> None:
    """随机短暂停顿，模拟人的操作节奏。"""
    await asyncio.sleep(random.uniform(lo, hi))


async def _scroll_to_find_comment(page: Page, comment_id: str):
    """在评论区滚动查找目标评论元素；找不到返回 None。"""
    selectors = [
        f"div[id='comment-{comment_id}']",
        f"[id='{comment_id}']",
        f"[id='comment-{comment_id}']",
    ]
    for _round in range(_MAX_SCROLL_ROUNDS):
        for selector in selectors:
            loc = page.locator(selector)
            try:
                if await loc.count() > 0:
                    return loc.first
            except Exception:
                continue
        # 评论区懒加载：滚动评论区容器或页面
        try:
            await page.mouse.wheel(0, random.randint(600, 1200))
        except Exception:
            await page.evaluate("window.scrollBy(0, 900)")
        await _human_pause(0.8, 1.8)
    return None


async def _type_like_human(locator, text: str) -> None:
    """逐字输入，每个字符间隔随机几十到一百多毫秒。"""
    await locator.click()
    await _human_pause(0.3, 0.8)
    await locator.press_sequentially(text, delay=random.randint(60, 130))


async def _submit_and_verify(page: Page, message: str) -> str:
    """点击发送并确认成功；成功返回空串（无平台回执 id），失败抛错。"""
    send_btn = page.locator(".comments-container").locator(
        "button:has-text('发送'), div[class*='submit']:has-text('发送')"
    )
    try:
        await send_btn.first.click(timeout=5000)
    except Exception:
        # 有的版本是输入框内回车提交
        await page.keyboard.press("Enter")

    # 等待页面上出现我们发送的文本（新回复渲染出来）
    verify = page.locator(f"text={message[:24]}")
    try:
        await verify.first.wait_for(timeout=10000)
    except Exception:
        # 检查是否被风控拦截（常见 toast 文案）
        page_text = ""
        try:
            page_text = await page.inner_text("body")
        except Exception:
            pass
        for keyword, reason in (
            ("频繁", "操作过于频繁，被平台限流，请稍后再试"),
            ("敏感", "评论内容包含敏感词，请修改后重试"),
            ("登录", "登录态失效，请重新登录小红书"),
        ):
            if keyword in page_text:
                raise ReplySendError(reason)
        raise ReplySendError("发送后未能确认成功（页面未出现回复内容），请人工核查")
    return ""


async def _reply_flow(page: Page, note_id: str, comment_id: str, message: str) -> str:
    """在一个已登录的页面上完成整条回复；成功返回回复标识（可能为空）。"""
    url = _XHS_NOTE_URL.format(note_id=note_id)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=_PAGE_TIMEOUT_MS)
    except Exception as exc:
        raise ReplySendError(f"打开笔记页失败：{exc}") from exc

    try:
        await page.wait_for_selector(".comments-container", timeout=_PAGE_TIMEOUT_MS)
    except Exception as exc:
        raise ReplySendError("页面加载异常（评论区容器未出现），可能是笔记已删除或网络问题") from exc

    comment = await _scroll_to_find_comment(page, comment_id)
    if comment is None:
        raise ReplySendError(f"未能定位目标评论（comment_id={comment_id}），可能已被删除或不在前 {_MAX_SCROLL_ROUNDS} 屏")

    # 点「回复」展开输入框（有时需先 hover 让按钮出现）
    reply_btn = comment.locator("span:has-text('回复'), a:has-text('回复'), div:has-text('回复')")
    try:
        await comment.hover()
        await _human_pause(0.3, 0.9)
        await reply_btn.first.click(timeout=5000)
    except Exception as exc:
        raise ReplySendError(f"点击「回复」按钮失败：{exc}") from exc

    # 回复输入框：评论项内的 contenteditable，或全局评论输入框（回复模式）
    editor = comment.locator("[contenteditable='true']")
    if await editor.count() == 0:
        editor = page.locator(".comments-container").locator("[contenteditable='true']")
    if await editor.count() == 0:
        raise ReplySendError("未找到回复输入框（contenteditable），页面结构可能已更新")
    await _type_like_human(editor.first, message)
    await _human_pause(0.4, 1.1)
    return await _submit_and_verify(page, message)


async def send_xhs_reply_async(
    *,
    content_id: str,
    comment_id: str,
    message: str,
    browser: Optional["Browser"] = None,
) -> str:
    """连接浏览器并发送；可注入已连接的 browser（测试用）。"""
    note_id = str(content_id or "").strip()
    comment_id = str(comment_id or "").strip()
    if not note_id:
        raise ReplySendError("缺少目标笔记 id，无法回复")
    if not comment_id:
        raise ReplySendError("缺少目标评论 id，无法回复")
    if not (message or "").strip():
        raise ReplySendError("回复内容为空")

    owned = browser is None
    browser = browser or await _connect_browser()
    try:
        context = await _pick_context(browser)
        await _check_login(context)
        page = await context.new_page()
        try:
            return await _reply_flow(page, note_id, comment_id, message)
        finally:
            try:
                await page.close()
            except Exception:
                pass
    finally:
        if owned:
            try:
                await browser.close()
            except Exception:
                pass


def send_xhs_reply(*, content_id: str, comment_id: str, message: str, cookie: str = "") -> str:
    """同步入口（reply_sender 调用；运行在 reply 线程中）。"""
    return asyncio.run(
        send_xhs_reply_async(content_id=content_id, comment_id=comment_id, message=message)
    )
