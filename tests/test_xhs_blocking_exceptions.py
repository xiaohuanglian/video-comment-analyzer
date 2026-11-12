"""账号级异常不许被宽容分支吞掉。

2026-11-11 事故的真实行为不是「程序崩了」，而是程序记了一条 error，然后继续把剩下的
关键词 / 笔记全打完——`CaptchaError` / `PlatformAccessError` / `IPBlockError` 都继承
`DataFetchError`，被 `except DataFetchError` 一句吞了。这个文件锁住「穿出去」。
"""
import asyncio

import pytest

from media_platform.xhs.exception import (
    BLOCKING_EXCEPTIONS,
    CaptchaError,
    DataFetchError,
    IPBlockError,
    NoteNotFoundError,
    PlatformAccessError,
    is_blocking,
)


class TestExceptionHierarchy:
    def test_captcha_and_access_are_data_fetch_errors(self):
        """这两个同时是 DataFetchError——这正是它们会被 ``except DataFetchError`` 吞掉的原因，
        也是必须在宽容分支之前单列 ``except BLOCKING_EXCEPTIONS`` 的原因。"""
        assert issubclass(CaptchaError, DataFetchError)
        assert issubclass(PlatformAccessError, DataFetchError)

    def test_ip_block_is_separate(self):
        """IPBlockError 不走 DataFetchError，历史上就是因为没被吞才偶尔起了作用。"""
        assert not issubclass(IPBlockError, DataFetchError)
        assert IPBlockError in BLOCKING_EXCEPTIONS

    def test_note_not_found_is_not_blocking(self):
        assert not is_blocking(NoteNotFoundError("笔记不存在"))

    @pytest.mark.parametrize(
        "exc",
        [CaptchaError("461"), PlatformAccessError("401"), IPBlockError("300012")],
    )
    def test_is_blocking(self, exc):
        assert is_blocking(exc)

    def test_plain_exception_is_not_blocking(self):
        assert not is_blocking(RuntimeError("boom"))


class TestDetailTaskDoesNotSwallow:
    def test_detail_task_reraises_captcha(self, monkeypatch):
        """detail 模式撞验证码必须抛，不能 return None 然后接着打下一篇。"""
        from media_platform.xhs import core

        crawler = core.XiaoHongShuCrawler.__new__(core.XiaoHongShuCrawler)
        crawler.xhs_client = _BoomClient(CaptchaError("461 CAPTCHA"))
        crawler.index_url = "https://www.xiaohongshu.com"
        crawler.playwright_proxy = None

        with pytest.raises(CaptchaError):
            asyncio.run(
                crawler.get_note_detail_async_task(
                    "note1", "pc_search", "token", asyncio.Semaphore(1)
                )
            )

    def test_detail_task_still_returns_none_on_normal_error(self, monkeypatch):
        from media_platform.xhs import core

        crawler = core.XiaoHongShuCrawler.__new__(core.XiaoHongShuCrawler)
        crawler.xhs_client = _BoomClient(DataFetchError("解析失败"))
        crawler.index_url = "https://www.xiaohongshu.com"
        crawler.playwright_proxy = None

        assert (
            asyncio.run(
                crawler.get_note_detail_async_task(
                    "note1", "pc_search", "token", asyncio.Semaphore(1)
                )
            )
            is None
        )


class _BoomClient:
    """最小替身：一调就抛指定异常，避免真的发网络请求。"""

    def __init__(self, exc):
        self.exc = exc

    async def get_note_by_id(self, *a, **kw):
        raise self.exc

    async def get_note_by_id_from_html(self, *a, **kw):
        raise self.exc


class TestSubCommentLoopDoesNotSwallow:
    def test_blocking_escapes_per_comment_loop(self):
        """外层 per-comment 循环里，账号级拦截必须穿出去而不是 continue。"""
        import inspect

        from media_platform.xhs import client

        src = inspect.getsource(client.XiaoHongShuClient.get_comments_all_sub_comments)
        # 两处 except BLOCKING_EXCEPTIONS: raise（内层分页 + 外层 per-comment）
        assert src.count("except BLOCKING_EXCEPTIONS") == 2
        assert src.count("except BLOCKING_EXCEPTIONS:\n") == 2
