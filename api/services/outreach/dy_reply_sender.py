# -*- coding: utf-8 -*-
"""抖音评论区受控回复：CDP 浏览器内仿人工操作。

流程（全部在已登录的浏览器里完成，AI 不产生内容，只执行已审核文本）：
1. 通过 CDP 连接本机浏览器（需已登录抖音，见 config.CDP_DEBUG_PORT）
2. 打开目标视频页 ``https://www.douyin.com/video/<aweme_id>``
3. 在评论区滚动定位目标评论（抖音没有 comment-id 锚点/xsec_token 机制，
   按「昵称 + 评论正文前缀」匹配）
4. 点击该评论的「回复」，在 contenteditable 输入框里逐字输入（随机延迟）
5. dry_run=True 时停在点发送前（链路验证用，零账号风险）；
   否则提交并确认成功（页面出现我们发送的文本）

失败时抛 :class:`ReplySendError`，由 reply_automation 的 dy 发送循环记录并停损。
"""

from __future__ import annotations

import asyncio
import random
from typing import Optional

try:  # playwright is a hard dependency of the project already
    from playwright.async_api import Browser, BrowserContext, Page, async_playwright
except Exception:  # pragma: no cover - tests run without browser
    async_playwright = None  # type: ignore[assignment]

from tools.human_behavior import (
    human_click,
    human_pause,
    scroll_container_smooth,
)

from .reply_sender import ReplySendError

_DY_VIDEO_URL = "https://www.douyin.com/video/{aweme_id}"
_PAGE_TIMEOUT_MS = 30000
_MAX_SCROLL_ROUNDS = 12
# 评论项/输入框的选择器按优先级尝试（抖音前端改版频繁，多备几手）
_COMMENT_ITEM_SELECTORS = (
    '[data-e2e="comment-item"]',
    "div.comment-item",
    '[data-e2e="comment-list"] > div',
)
_REPLY_BTN_SELECTORS = (
    '[data-e2e="comment-reply"]',
    "span.reply",
)
_INPUT_SELECTORS = (
    '[data-e2e="comment-input"] [contenteditable="true"]',
    '[contenteditable="true"]',
)
_SEND_BTN_SELECTORS = (
    '[data-e2e="comment-send"]',
    'button:has-text("发送")',
)


# 连接/登录态等公共逻辑统一在 browser_reply_base（2026-11-11 去重：
# 原先与 xhs_reply_sender 逐字重复三处，相似度 0.43）。
from .browser_reply_base import (
    PlatformLoginCheck,
    connect_browser,
    pick_context,
    read_login_present,
)

_DY_LOGIN = PlatformLoginCheck(
    domain="https://www.douyin.com",
    cookie_name="LOGIN_STATUS",
    expected_value="1",
    platform_label="抖音",
)


async def _connect_browser() -> Browser:
    """连接本机 CDP 浏览器（须已启动且登录抖音）。"""
    return await connect_browser(platform_label="抖音")


async def _pick_context(browser: Browser) -> BrowserContext:
    return await pick_context(browser)


async def fetch_dy_login_state() -> bool:
    """检查本机 CDP 浏览器里的抖音登录态（LOGIN_STATUS cookie）。

    供采集/发送前的就绪检查：连不上浏览器或未登录都算未就绪。
    """
    browser = await _connect_browser()
    try:
        return await read_login_present(browser, _DY_LOGIN) is not None
    finally:
        try:
            await browser.close()
        except Exception:
            pass


async def _check_login(context: BrowserContext, page: "Page") -> None:
    """确认登录态：LOGIN_STATUS cookie 为 1（与 dy login 模块同一判据）。"""
    try:
        cookies = await context.cookies([_DY_LOGIN.domain])
        status = next(
            (str(c.get("value") or "") for c in cookies if c.get("name") == _DY_LOGIN.cookie_name),
            "",
        )
    except Exception:
        status = ""
    if status != _DY_LOGIN.expected_value:
        raise ReplySendError(
            f"浏览器里未登录{_DY_LOGIN.platform_label}"
            f"（{_DY_LOGIN.cookie_name} 非 {_DY_LOGIN.expected_value}）。"
            "请在受控浏览器窗口中登录后重试"
        )


async def _pause(lo: float = 0.6, hi: float = 2.2) -> None:
    await human_pause(lo, hi)


def _norm(s: str) -> str:
    """匹配用的宽松归一：去空白，忽略大小写。"""
    return "".join(str(s or "").split()).lower()


async def _find_comment_item(page: Page, commenter: str, comment_text: str):
    """在评论区滚动查找目标评论元素；找不到返回 None。

    抖音评论项没有 id 锚点，按「昵称」或「正文前缀」匹配（正文可能被
    emoji/表情符号修饰，前缀匹配取前 16 个归一字符）。
    """
    name_key = _norm(commenter)[:12]
    text_key = _norm(comment_text)[:16]
    for _round in range(_MAX_SCROLL_ROUNDS):
        items = page.locator(", ".join(_COMMENT_ITEM_SELECTORS))
        try:
            count = await items.count()
        except Exception:
            count = 0
        for i in range(count):
            item = items.nth(i)
            try:
                body = _norm(await item.inner_text())
            except Exception:
                continue
            if (name_key and name_key in body) or (text_key and text_key in body):
                return item
        # 评论区懒加载：拟人滚动评论列表容器，退化用窗口滚动
        try:
            await scroll_container_smooth(
                page, '[data-e2e="comment-list"], .comment-list', random.randint(600, 1200)
            )
        except Exception:
            try:
                await page.mouse.wheel(0, random.randint(500, 1000))
            except Exception:
                await page.evaluate("window.scrollBy(0, 800)")
        await _pause(0.8, 1.6)
    return None


async def _reply_flow(
    page: Page,
    context: BrowserContext,
    aweme_id: str,
    message: str,
    commenter: str,
    comment_text: str,
    dry_run: bool,
) -> str:
    target = _DY_VIDEO_URL.format(aweme_id=aweme_id)
    try:
        await page.goto(target, wait_until="domcontentloaded", timeout=_PAGE_TIMEOUT_MS)
    except Exception as exc:
        raise ReplySendError(f"打开视频页失败：{exc}") from exc

    await _check_login(context, page)

    # 等评论区出现（视频页右侧面板；部分场景需点开评论开关）
    try:
        await page.wait_for_selector(
            ", ".join(_COMMENT_ITEM_SELECTORS), timeout=_PAGE_TIMEOUT_MS
        )
    except Exception:
        # 评论区可能收起：尝试点「评论」开关展开
        try:
            toggle = page.locator('[data-e2e="comment-entry"], [data-e2e="video-comment"], button:has-text("评论")')
            if await toggle.count() > 0:
                await human_click(page, toggle.first, timeout=5000)
                await page.wait_for_selector(
                    ", ".join(_COMMENT_ITEM_SELECTORS), timeout=10000
                )
        except Exception as exc:
            raise ReplySendError("页面加载异常（评论区未出现），可能是视频已删除或网络问题") from exc

    item = await _find_comment_item(page, commenter, comment_text)
    if item is None:
        raise ReplySendError(
            f"未能定位目标评论（昵称={commenter[:16]}），可能已被删除或不在前 {_MAX_SCROLL_ROUNDS} 屏"
        )

    # 点「回复」
    reply_btn = item.locator(", ".join(_REPLY_BTN_SELECTORS))
    try:
        await item.hover()
        await _pause(0.3, 0.9)
        await human_click(page, reply_btn.first, timeout=5000)
    except Exception as exc:
        raise ReplySendError(f"点击「回复」按钮失败：{exc}") from exc

    # 回复输入框（页面底部 contenteditable）
    editor = page.locator(", ".join(_INPUT_SELECTORS))
    try:
        await editor.first.wait_for(timeout=5000)
    except Exception as exc:
        raise ReplySendError("点击回复后未出现输入框，页面结构可能已更新") from exc
    await human_click(page, editor.first)
    await _pause(0.3, 0.8)
    await editor.first.press_sequentially(message, delay=random.randint(60, 130))
    await _pause(0.4, 1.1)

    if dry_run:
        # 干跑：文本已填进输入框，停在点发送前。链路验证用，不产生任何发送动作。
        return "DRY-RUN-OK"

    return await _submit_and_verify(page, message)


async def _submit_and_verify(page: Page, message: str) -> str:
    """点击发送并确认成功；成功返回空串，失败抛错。"""
    send_btn = page.locator(", ".join(_SEND_BTN_SELECTORS))
    try:
        await human_click(page, send_btn.first, timeout=5000)
    except Exception:
        await page.keyboard.press("Enter")

    verify = page.locator(f"text={message[:24]}")
    try:
        await verify.first.wait_for(timeout=10000)
    except Exception:
        page_text = ""
        try:
            page_text = await page.inner_text("body")
        except Exception:
            pass
        for keyword, reason in (
            ("频繁", "操作过于频繁，被平台限流，请稍后再试"),
            ("敏感", "评论内容包含敏感词，请修改后重试"),
            ("登录", "登录态失效，请重新登录抖音"),
        ):
            if keyword in page_text:
                # 与「等待超时」这个底层异常无关，显式切断异常链
                raise ReplySendError(reason) from None
        raise ReplySendError(
            "发送后未能确认成功（页面未出现回复内容），请人工核查"
        ) from None
    return ""


async def send_dy_reply_async(
    *,
    content_id: str,
    comment_id: str,
    message: str,
    commenter: str = "",
    comment_text: str = "",
    browser: Optional["Browser"] = None,
    dry_run: bool = False,
) -> str:
    """连接浏览器并回复；dry_run=True 停在发送前一步（链路验证）。可注入 browser（测试用）。"""
    aweme_id = str(content_id or "").strip()
    if not aweme_id:
        raise ReplySendError("缺少目标视频 id，无法回复")
    if not (message or "").strip():
        raise ReplySendError("回复内容为空")
    if not commenter and not comment_text:
        raise ReplySendError("缺少评论定位信息（昵称/正文），无法找到目标评论")

    owned = browser is None
    browser = browser or await _connect_browser()
    try:
        context = await _pick_context(browser)
        page = await context.new_page()
        try:
            return await _reply_flow(
                page, context, aweme_id, message, commenter, comment_text, dry_run
            )
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


def send_dy_reply(
    *,
    content_id: str,
    comment_id: str,
    message: str,
    commenter: str = "",
    comment_text: str = "",
    dry_run: bool = False,
) -> str:
    """同步入口（reply_automation 的 dy 发送循环调用；运行在线程中）。"""
    return asyncio.run(
        send_dy_reply_async(
            content_id=content_id,
            comment_id=comment_id,
            message=message,
            commenter=commenter,
            comment_text=comment_text,
            dry_run=dry_run,
        )
    )
