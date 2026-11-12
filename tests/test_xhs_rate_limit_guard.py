# -*- coding: utf-8 -*-
"""小红书风控止损回归测试（2026-11-11 账号异常事故之后补的）。

事故复盘（`data/xhs_search/20261111_200159/manifest.json`）：
12 个搜索关键词以通用 3–4.5 秒的间隔在 40 秒内打完，后 3 个词连续返回
HTTP 461 CAPTCHA；而 461 抛的是裸 ``Exception``，被 ``@retry`` 当成可重试错误，
每个词又补了 3 次请求 —— 对已被标记的账号又多打了 9 次。更糟的是整条链路
**一次都没写进平台冷却**，所以第二天（也就是事故之后）任何采集照样放行。

这个文件锁住四件事：
1. 小红书/抖音有平台级间隔覆盖，且键名拼错会立刻暴露（``getattr`` 拼错只会静默取默认值）。
2. 撞验证码只发一次请求，不重试。
3. 撞一次就把平台冷却落盘（跨进程可见）。
4. 新进程（新 store 实例）会被 ``ensure_platform_available`` 拦下。
"""

import asyncio
import json

import pytest
from tenacity import RetryError

import config
from media_platform.xhs import client as xhs_client_mod
from media_platform.xhs.client import XiaoHongShuClient
from media_platform.xhs.exception import CaptchaError, IPBlockError
from tools import crawl_pacing as cp

# ---------------------------------------------------------------------------
# 1. 平台级间隔
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "platform, expected_base, expected_jitter",
    [
        ("bili", 4.0, 2.0),
        ("xhs", 20.0, 12.0),
        ("dy", 12.0, 8.0),
    ],
)
def test_platform_pacing_override_is_wired(platform, expected_base, expected_jitter, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_SAFE_CRAWL_MODE", True)
    base, jitter = cp.compute_crawl_interval(platform)
    assert (base, jitter) == (expected_base, expected_jitter)


def test_platform_pacing_keys_exist_in_config():
    """``getattr(config, key, default)`` 拼错键名不会报错，只会静默用通用值。

    所以这里直接断言键真的存在于 config 上 —— 事故的根源之一就是
    小红书压根没有这两个键，3 秒的通用值被当成"平台配置"用了。
    """
    for platform, (base_key, jitter_key) in cp._PLATFORM_PACING.items():
        assert hasattr(config, base_key), f"{platform} 缺少 {base_key}"
        assert hasattr(config, jitter_key), f"{platform} 缺少 {jitter_key}"


def test_blocked_cooldown_is_longer_for_account_bound_platforms():
    """小红书/抖音封的是账号，冷却必须显著长于 B 站（封 IP）的 30 分钟。"""
    bili = cp._cooldown_seconds(cp.PLATFORM_BLOCKED, "bili")
    xhs = cp._cooldown_seconds(cp.PLATFORM_BLOCKED, "xhs")
    dy = cp._cooldown_seconds(cp.PLATFORM_BLOCKED, "dy")
    assert xhs > bili * 10
    assert dy > bili * 5


def test_rate_limit_cooldown_stays_short():
    """限流（还有救）不该跟风控（账号已异常）一个时长，否则一次抖动停一天。"""
    assert cp._cooldown_seconds(cp.RATE_LIMITED, "xhs") <= 3600


def test_unknown_platform_falls_back_to_generic(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_SAFE_CRAWL_MODE", True)
    assert cp.compute_crawl_interval("") == (3.0, 1.5)


def test_xhs_interval_is_much_slower_than_generic():
    # 事故的直接触发条件：词间只等 3–4.5 秒。这里锁住"小红书必须比通用值慢得多"。
    generic, _ = cp.compute_crawl_interval("")
    xhs, _ = cp.compute_crawl_interval("xhs")
    assert xhs >= generic * 5


# ---------------------------------------------------------------------------
# 2/3. 客户端：461 不重试 + 落冷却
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_cooldowns(tmp_path):
    cp.reset_cooldown_store(cp.CooldownStore(tmp_path / "cooldowns.json"))
    yield cp.cooldown_store()
    cp.reset_cooldown_store(None)


def _make_client() -> XiaoHongShuClient:
    return XiaoHongShuClient(headers={"Cookie": "a=1"}, playwright_page=None, cookie_dict={"a": "1"})


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload

    def __repr__(self):
        # 默认 repr 会带上模块名（本文件名里有 "rate_limit"），
        # 那样错误文本会被 classify_failure 误判成 RATE_LIMITED，掩盖真正要测的分类。
        return f"<Response [{self.status_code}]>"


class _FakeAsyncClient:
    """记录调用次数的最小 httpx.AsyncClient 替身。"""

    calls = 0
    response_factory = None

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, url, **kwargs):
        type(self).calls += 1
        return type(self).response_factory()


@pytest.fixture
def fake_http(monkeypatch):
    _FakeAsyncClient.calls = 0
    monkeypatch.setattr(xhs_client_mod, "make_async_client", lambda **kw: _FakeAsyncClient(**kw))
    return _FakeAsyncClient


def test_captcha_raises_dedicated_error_without_retry(isolated_cooldowns, fake_http):
    """461 只打一次：重试等于对已被标记的账号补刀。"""
    fake_http.response_factory = lambda: _FakeResponse(
        461, headers={"Verifytype": "217", "Verifyuuid": "uuid-1"}
    )
    client = _make_client()

    async def run():
        with pytest.raises(CaptchaError) as excinfo:
            await client.request("GET", "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes")
        return excinfo

    excinfo = asyncio.run(run())
    assert fake_http.calls == 1, f"撞验证码后应立刻停手，实际发了 {fake_http.calls} 次请求"
    assert "CAPTCHA" in str(excinfo.value)


def test_captcha_writes_platform_cooldown(isolated_cooldowns, fake_http):
    fake_http.response_factory = lambda: _FakeResponse(
        461, headers={"Verifytype": "217", "Verifyuuid": "uuid-1"}
    )
    client = _make_client()

    async def run():
        with pytest.raises(CaptchaError):
            await client.request("GET", "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes")

    asyncio.run(run())

    active = cp.platform_cooldown("xhs")
    assert active is not None, "撞验证码必须让整个平台进入冷却"
    assert active["code"] == cp.PLATFORM_BLOCKED
    assert active["retry_after_seconds"] > 0
    # 账号级风控不是 IP 级限流：半小时不够它降温
    assert active["retry_after_seconds"] >= 3600


def test_captcha_cooldown_blocks_a_fresh_process(isolated_cooldowns, fake_http, tmp_path):
    """冷却落盘后，新进程（新 store 实例读同一个文件）必须被拦下。"""
    fake_http.response_factory = lambda: _FakeResponse(
        471, headers={"Verifytype": "217", "Verifyuuid": "uuid-2"}
    )

    async def run():
        with pytest.raises(CaptchaError):
            await _make_client().request("GET", "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes")

    asyncio.run(run())

    state = json.loads((tmp_path / "cooldowns.json").read_text(encoding="utf-8"))
    assert "xhs" in state["platforms"]

    # 模拟新进程：重建 store，只认磁盘
    cp.reset_cooldown_store(cp.CooldownStore(tmp_path / "cooldowns.json"))
    with pytest.raises(cp.CrawlBlocked) as excinfo:
        cp.ensure_platform_available("xhs")
    assert excinfo.value.failure.code == cp.PLATFORM_BLOCKED


def test_ip_block_also_writes_cooldown(isolated_cooldowns, fake_http):
    fake_http.response_factory = lambda: _FakeResponse(
        200, payload={"success": False, "code": 300012, "msg": "network error"}
    )

    async def run():
        with pytest.raises(IPBlockError):
            await _make_client().request("GET", "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes")

    asyncio.run(run())
    assert cp.platform_cooldown("xhs") is not None


def test_note_not_found_does_not_trigger_cooldown(isolated_cooldowns, fake_http):
    """正常业务错误（笔记不存在）不该把整个平台停掉。"""
    fake_http.response_factory = lambda: _FakeResponse(
        200, payload={"success": False, "code": -510000, "msg": "note not found"}
    )
    client = _make_client()

    async def run():
        with pytest.raises(xhs_client_mod.NoteNotFoundError):
            await client.request("GET", "https://edith.xiaohongshu.com/api/sns/web/v1/feed")

    asyncio.run(run())
    assert cp.platform_cooldown("xhs") is None


def test_other_errors_still_retry(isolated_cooldowns, fake_http):
    """别把重试一起关掉：普通上游错误仍应有 3 次重试。"""
    fake_http.response_factory = lambda: _FakeResponse(
        200, payload={"success": False, "code": -1, "msg": "服务器开小差"}
    )
    client = _make_client()

    async def run():
        with pytest.raises(RetryError):
            await client.request("GET", "https://edith.xiaohongshu.com/api/sns/web/v1/feed")

    asyncio.run(run())
    assert fake_http.calls == 3


# ---------------------------------------------------------------------------
# 4. 脚本：撞风控立即停批
# ---------------------------------------------------------------------------


class _FakePage:
    async def goto(self, *a, **kw):
        return None

    async def close(self):
        return None


class _FakeContext:
    async def new_page(self):
        return _FakePage()


class _FakeManager:
    async def launch_and_connect(self, *a, **kw):
        return _FakeContext()

    async def cleanup(self):
        return None


class _FakePlaywrightCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeXhsClient:
    """第 ``raise_at`` 次搜索抛 CaptchaError，其余返回 1 条笔记。"""

    def __init__(self, raise_at: int):
        self.raise_at = raise_at
        self.calls: list[str] = []

    async def pong(self):
        return True

    async def get_note_by_keyword(self, *, keyword, **kw):
        self.calls.append(keyword)
        if len(self.calls) == self.raise_at:
            raise CaptchaError(
                "CAPTCHA appeared, request failed, Verifytype: 217, Verifyuuid: uuid-9, "
                "Response: <Response [461]>"
            )
        return {
            "items": [
                {
                    "id": f"note-{keyword}",
                    "xsec_token": "tok",
                    "note_card": {
                        "type": "normal",
                        "display_title": f"标题 {keyword}",
                        "user": {"nickname": "作者", "user_id": "u1"},
                        "interact_info": {"liked_count": "10"},
                    },
                }
            ]
        }


def test_script_aborts_batch_on_captcha(isolated_cooldowns, monkeypatch, tmp_path):
    """撞一次风控就停：剩余关键词不应再发请求，且冷却必须落盘。"""
    import playwright.async_api as pw_api

    from scripts import xhs_keyword_notes as script

    keywords = ["词一", "词二", "词三", "词四"]
    fake_client = _FakeXhsClient(raise_at=2)

    monkeypatch.setattr(pw_api, "async_playwright", lambda: _FakePlaywrightCtx())
    monkeypatch.setattr(script, "CDPBrowserManager", _FakeManager)
    monkeypatch.setattr(script, "compute_crawl_interval", lambda platform="": (0.0, 0.0))

    async def fake_build_client(page):
        return fake_client

    monkeypatch.setattr(script, "_build_client", fake_build_client)

    manifest = asyncio.run(
        script.collect(keywords, per_keyword=1, total=10, out_dir=tmp_path / "out")
    )

    assert fake_client.calls == ["词一", "词二"], f"撞风控后不该继续，实际打了 {fake_client.calls}"
    assert manifest["aborted"] is True
    aborted = [f for f in manifest["failures"] if f.get("stage") == "aborted"]
    assert aborted and aborted[0]["skipped_keywords"] == ["词三", "词四"]
    assert cp.platform_cooldown("xhs") is not None
    assert manifest["fetched_per_keyword"]["词三"] == 0


def test_script_continues_on_non_blocking_error(isolated_cooldowns, monkeypatch, tmp_path):
    """普通失败（比如单个词上游报错）不该把整批停掉，也不该写平台冷却。"""
    import playwright.async_api as pw_api

    from scripts import xhs_keyword_notes as script

    class _Client(_FakeXhsClient):
        async def get_note_by_keyword(self, *, keyword, **kw):
            if keyword == "词二":
                self.calls.append(keyword)
                raise ValueError("params or payload is required")
            return await super().get_note_by_keyword(keyword=keyword, **kw)

    fake_client = _Client(raise_at=99)
    monkeypatch.setattr(pw_api, "async_playwright", lambda: _FakePlaywrightCtx())
    monkeypatch.setattr(script, "CDPBrowserManager", _FakeManager)
    monkeypatch.setattr(script, "compute_crawl_interval", lambda platform="": (0.0, 0.0))

    async def fake_build_client(page):
        return fake_client

    monkeypatch.setattr(script, "_build_client", fake_build_client)

    manifest = asyncio.run(
        script.collect(["词一", "词二", "词三"], per_keyword=1, total=10, out_dir=tmp_path / "out")
    )

    assert fake_client.calls == ["词一", "词二", "词三"]
    assert manifest["aborted"] is False
    assert cp.platform_cooldown("xhs") is None
