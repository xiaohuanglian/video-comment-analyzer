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


async def _check_login(page: "Page") -> None:
    """检查小红书登录态。

    cookie 不可靠：访客也会拿到 38 位的 ``web_session``。可靠的判据是页面
    全局状态 ``__INITIAL_STATE__.user.userInfo.userId``，仅登录用户非空。
    在目标笔记页上检查（该页同样携带用户状态）。
    """
    try:
        info = await page.evaluate(
            """() => {
              const s = window.__INITIAL_STATE__ || {};
              const u = (s.user && s.user.userInfo) || {};
              return {hasUser: !!(s.user && s.user.userInfo), userId: String(u.userId || '')};
            }"""
        )
    except Exception:
        info = None
    if info and info.get("hasUser"):
        if not info.get("userId"):
            raise ReplySendError(
                "浏览器里未登录小红书（页面用户状态为访客）。"
                "请在受控浏览器窗口中登录后重试"
            )
        return
    # 页面状态拿不到时退回 cookie 检查（弱判据，仅作兑底）
    raise ReplySendError(
        "无法确认小红书登录态（页面未提供用户状态），请确认已在浏览器中登录后重试"
    )


async def _human_pause(lo: float = 0.6, hi: float = 2.2) -> None:
    """随机短暂停顿，模拟人的操作节奏。"""
    await asyncio.sleep(random.uniform(lo, hi))


async def _scroll_to_find_comment(page: Page, comment_id: str):
    """在评论区滚动查找目标评论元素；找不到返回 None。

    小红书笔记页的滚动容器是右侧面板的 ``.note-scroller``，评论懒加载
    需滚动该容器（窗口滚动不生效）。
    """
    selectors = [
        f"div[id='comment-{comment_id}']",
        f"[id='comment-{comment_id}']",
        f"[id='{comment_id}']",
    ]
    for _round in range(_MAX_SCROLL_ROUNDS):
        for selector in selectors:
            loc = page.locator(selector)
            try:
                if await loc.count() > 0:
                    return loc.first
            except Exception:
                continue
        # 评论区懒加载：滚动右侧面板的 note-scroller，退化用窗口滚动
        try:
            await page.evaluate(
                "document.querySelector('.note-scroller')?.scrollBy(0, arguments_delta)".replace(
                    "arguments_delta", str(random.randint(800, 1400))
                )
            )
        except Exception:
            await page.mouse.wheel(0, random.randint(600, 1200))
        await _human_pause(0.8, 1.8)
    return None


async def _type_like_human(locator, text: str) -> None:
    """逐字输入，每个字符间隔随机几十到一百多毫秒。"""
    await locator.click()
    await _human_pause(0.3, 0.8)
    await locator.press_sequentially(text, delay=random.randint(60, 130))


async def _submit_and_verify(page: Page, message: str) -> str:
    """点击发送并确认成功；成功返回空串（无平台回执 id），失败抛错。"""
    # 发送按钮在页面底部 engage-bar（button.submit），不在评论区容器内
    send_btn = page.locator(".engage-bar button.submit")
    if await send_btn.count() == 0:
        send_btn = page.locator("button", has_text="发送")
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


async def _reply_flow(page: Page, note_id: str, comment_id: str, message: str, url: str = "") -> str:
    """在一个已登录的页面上完成整条回复；成功返回回复标识（可能为空）。"""
    # 优先用带 xsec_token 的完整链接（2024 起直链无 token 会 404）
    target = url.strip() or _XHS_NOTE_URL.format(note_id=note_id)
    try:
        await page.goto(target, wait_until="domcontentloaded", timeout=_PAGE_TIMEOUT_MS)
    except Exception as exc:
        raise ReplySendError(f"打开笔记页失败：{exc}") from exc

    if "/404" in (page.url or ""):
        raise ReplySendError(
            "笔记页无法浏览（404/风控校验失败）。"
            "旧采集数据的评论链接缺少 xsec_token，请重新采集该笔记的评论"
        )

    # 登录态检查（页面用户状态，访客 userId 为空）
    await _check_login(page)

    try:
        await page.wait_for_selector(".comments-container", timeout=_PAGE_TIMEOUT_MS)
    except Exception as exc:
        raise ReplySendError("页面加载异常（评论区容器未出现），可能是笔记已删除或网络问题") from exc

    comment = await _scroll_to_find_comment(page, comment_id)
    if comment is None:
        raise ReplySendError(f"未能定位目标评论（comment_id={comment_id}），可能已被删除或不在前 {_MAX_SCROLL_ROUNDS} 屏")

    # 点「回复」（.reply 在评论项 interactions 区），输入框在页面底部 engage-bar 切换为回复模式
    reply_btn = comment.locator(".reply")
    try:
        await comment.hover()
        await _human_pause(0.3, 0.9)
        await reply_btn.first.click(timeout=5000)
    except Exception as exc:
        raise ReplySendError(f"点击「回复」按钮失败：{exc}") from exc

    # 确认 engage-bar 已进入回复模式（出现「发送/取消」按钮）
    try:
        await page.wait_for_selector(".engage-bar button.submit, .engage-bar .cancel", timeout=5000)
    except Exception as exc:
        raise ReplySendError("点击回复后未进入回复模式（发送/取消按钮未出现）") from exc

    # 回复输入框：页面级 contenteditable（.content-input），不是评论项内嵌的
    editor = page.locator(".content-input[contenteditable='true']")
    if await editor.count() == 0:
        editor = page.locator(".engage-bar [contenteditable='true']")
    if await editor.count() == 0:
        editor = page.locator("[contenteditable='true']")
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
    url: str = "",
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
        page = await context.new_page()
        try:
            return await _reply_flow(page, note_id, comment_id, message, url=url)
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


def send_xhs_reply(*, content_id: str, comment_id: str, message: str, cookie: str = "", url: str = "") -> str:
    """同步入口（reply_sender 调用；运行在 reply 线程中）。"""
    return asyncio.run(
        send_xhs_reply_async(content_id=content_id, comment_id=comment_id, message=message, url=url)
    )
