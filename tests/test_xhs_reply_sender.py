# -*- coding: utf-8 -*-
"""小红书受控回复：链接解析 + 浏览器回复流程（假页面对象）。"""

from __future__ import annotations

import asyncio

import pytest

from api.services.insight.candidate_schemas import CandidateComment, CandidateRecord, OutreachEntry
from api.services.insight.field_mapping import (
    derive_platform_links,
    derive_xhs_links,
    parse_xhs_targets,
)
from api.services.outreach.outreach import _apply_candidate_targets
from api.services.outreach.reply_sender import platform_capability
from api.services.outreach.xhs_reply_sender import ReplySendError, send_xhs_reply_async


# ---------------------------------------------------------------------------
# 链接解析
# ---------------------------------------------------------------------------


class TestXhsLinks:
    def test_derive_xhs_links(self):
        homepage, comment_url = derive_xhs_links("xhs", "u1", "noteabc", "cmt1")
        assert homepage == "https://www.xiaohongshu.com/user/profile/u1"
        assert comment_url == "https://www.xiaohongshu.com/explore/noteabc#comment-cmt1"

    def test_derive_platform_links_routes_by_platform(self):
        assert derive_platform_links("xhs", "u1", "note1", "c1")[1].startswith(
            "https://www.xiaohongshu.com/explore/"
        )
        assert derive_platform_links("bili", "u1", "BV1xx", "c1")[1].startswith(
            "https://www.bilibili.com/video/"
        )

    def test_parse_xhs_targets(self):
        url = "https://www.xiaohongshu.com/explore/64a1b2c3#comment-5f9e8d7c"
        assert parse_xhs_targets(url) == ("64a1b2c3", "5f9e8d7c")
        assert parse_xhs_targets("") == ("", "")
        assert parse_xhs_targets("https://www.xiaohongshu.com/explore/64a1b2c3") == ("64a1b2c3", "")

    def test_apply_candidate_targets_routes_xhs(self):
        candidate = CandidateRecord(
            user_key="k1",
            username="测试",
            platform="xhs",
            comments=[
                CandidateComment(
                    record_id="r1",
                    comment_text="这条笔记怎么导出",
                    comment_url="https://www.xiaohongshu.com/explore/64a1b2c3#comment-5f9e8d7c",
                )
            ],
        )
        entry = OutreachEntry(user_key="k1")
        _apply_candidate_targets(entry, candidate)
        assert entry.platform == "xhs"
        assert entry.target_content_id == "64a1b2c3"
        assert entry.target_comment_id == "5f9e8d7c"


def test_xhs_registered_in_senders():
    assert platform_capability("xhs")
    assert platform_capability("xiaohongshu")


# ---------------------------------------------------------------------------
# 浏览器回复流程（Fake Page）
# ---------------------------------------------------------------------------


class FakeLocator:
    def __init__(self, page: "FakePage", path: str):
        self.page = page
        self.path = path

    def locator(self, selector: str, has_text: str = None) -> "FakeLocator":
        if has_text is not None:
            selector = f"{selector} >> text={has_text}"
        return FakeLocator(self.page, f"{self.path} >> {selector}")

    @property
    def first(self) -> "FakeLocator":
        return self

    def _exists(self) -> bool:
        return self.page.exists(self.path)

    async def count(self) -> int:
        return 1 if self._exists() else 0

    async def click(self, timeout: int = 5000) -> None:
        self.page.actions.append(("click", self.path))
        if not self._exists():
            raise RuntimeError(f"not found: {self.path}")

    async def bounding_box(self, timeout: int = 5000) -> dict:
        if not self._exists():
            raise RuntimeError(f"not found: {self.path}")
        return {"x": 100.0, "y": 200.0, "width": 80.0, "height": 30.0}

    async def hover(self) -> None:
        self.page.actions.append(("hover", self.path))
        if not self._exists():
            raise RuntimeError(f"not found: {self.path}")

    async def press_sequentially(self, text: str, delay: int = 80) -> None:
        self.page.actions.append(("type", self.path, text))
        self.page.typed = text
        if not self._exists():
            raise RuntimeError(f"not found: {self.path}")

    async def wait_for(self, timeout: int = 10000) -> None:
        self.page.actions.append(("wait_for", self.path))
        if not self._exists():
            raise RuntimeError(f"not found: {self.path}")


class FakePage:
    def __init__(self, *, body_text: str = "", verify_ok: bool = True, logged_in: bool = True, url: str = "https://www.xiaohongshu.com/explore/NOTE1"):
        self.actions: list = []
        self.typed = ""
        self.body_text = body_text
        self.verify_ok = verify_ok
        self.logged_in = logged_in
        self.url = url
        self.mouse = FakePage._Mouse(self)

    def exists(self, path: str) -> bool:
        if "text=" in path and ">>" not in path:
            return self.verify_ok
        ok_markers = [
            "div[id='comment-CMT1']",
            "span:has-text('回复')",
            "[contenteditable='true']",
            "button:has-text('发送')",
        ]
        return any(m in path for m in ok_markers)

    def locator(self, selector: str, has_text: str = None) -> FakeLocator:
        if has_text is not None:
            selector = f"{selector} >> text={has_text}"
        return FakeLocator(self, selector)

    async def goto(self, url: str, wait_until: str = "", timeout: int = 0) -> None:
        self.actions.append(("goto", url))

    async def wait_for_selector(self, selector: str, timeout: int = 0) -> None:
        self.actions.append(("wait_for_selector", selector))

    async def inner_text(self, selector: str) -> str:
        return self.body_text

    async def evaluate(self, expr: str, arg=None):
        self.actions.append(("evaluate", expr, arg))
        if "__INITIAL_STATE__" in expr:
            return {
                "hasUser": True,
                "userId": "user123" if self.logged_in else "",
            }
        return None

    async def close(self) -> None:
        self.actions.append(("close",))

    class _Mouse:
        def __init__(self, page: "FakePage"):
            self._page = page

        async def wheel(self, x: int, y: int) -> None:
            pass

        async def move(self, x: float, y: float) -> None:
            self._page.actions.append(("mouse_move", x, y))

        async def down(self) -> None:
            self._page.actions.append(("mouse_down",))

        async def up(self) -> None:
            self._page.actions.append(("mouse_up",))

    class _Keyboard:
        async def press(self, key: str) -> None:
            pass

    keyboard = _Keyboard()


class FakeContext:
    def __init__(self, page: FakePage):
        self.page = page

    async def cookies(self) -> list:
        return [{"name": "web_session", "value": "x"}]

    async def new_page(self) -> FakePage:
        return self.page


class FakeBrowser:
    def __init__(self, context: FakeContext):
        self.contexts = [context]
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _run(coro):
    return asyncio.run(coro)


def test_xhs_reply_flow_success():
    page = FakePage()
    browser = FakeBrowser(FakeContext(page))
    result = _run(
        send_xhs_reply_async(
            content_id="NOTE1",
            comment_id="CMT1",
            message="我之前也碰到过，后来这样解决的",
            browser=browser,
        )
    )
    assert result == ""
    gotos = [a for a in page.actions if a[0] == "goto"]
    assert gotos == [("goto", "https://www.xiaohongshu.com/explore/NOTE1")]
    assert page.typed == "我之前也碰到过，后来这样解决的"
    # 输入是逐字 press_sequentially（仿人工），不是一次性填入
    typed = [a for a in page.actions if a[0] == "type"]
    assert len(typed) == 1
    # 拟人点击链：鼠标轨迹移动 + 按下/抬起（human_click 不再走 locator.click）
    assert any(a[0] == "mouse_down" for a in page.actions)
    assert any(a[0] == "mouse_move" for a in page.actions)
    # 页面用完关闭
    assert ("close",) in page.actions


def test_xhs_reply_flow_rate_limited():
    page = FakePage(body_text="操作太频繁了，请稍后再试", verify_ok=False)
    browser = FakeBrowser(FakeContext(page))
    with pytest.raises(ReplySendError) as exc:
        _run(
            send_xhs_reply_async(
                content_id="NOTE1", comment_id="CMT1", message="试试看", browser=browser
            )
        )
    assert "频繁" in str(exc.value)


def test_xhs_reply_flow_missing_ids():
    browser = FakeBrowser(FakeContext(FakePage()))
    with pytest.raises(ReplySendError):
        _run(send_xhs_reply_async(content_id="", comment_id="c1", message="x", browser=browser))
    with pytest.raises(ReplySendError):
        _run(send_xhs_reply_async(content_id="n1", comment_id="", message="x", browser=browser))
    with pytest.raises(ReplySendError):
        _run(send_xhs_reply_async(content_id="n1", comment_id="c1", message="  ", browser=browser))


def test_xhs_reply_flow_not_logged_in():
    page = FakePage(logged_in=False)
    browser = FakeBrowser(FakeContext(page))
    with pytest.raises(ReplySendError) as exc:
        _run(
            send_xhs_reply_async(
                content_id="NOTE1", comment_id="CMT1", message="x", browser=browser
            )
        )
    assert "登录" in str(exc.value)


def test_xhs_reply_flow_comment_not_found():
    class NotFoundPage(FakePage):
        def exists(self, path: str) -> bool:
            # 评论元素永远找不到
            return "contenteditable" in path

    page = NotFoundPage()
    browser = FakeBrowser(FakeContext(page))
    with pytest.raises(ReplySendError) as exc:
        _run(
            send_xhs_reply_async(
                content_id="NOTE1", comment_id="GONE", message="x", browser=browser
            )
        )
    assert "定位目标评论" in str(exc.value)
