# -*- coding: utf-8 -*-
"""抖音采集防封回归测试（2026-11-12 改造之后补的）。

改造前抖音这条链路是"看起来有防护、实际一处都没生效"：

- ``client.request()`` 只在 ``response.text == ""`` 时抛一个裸 ``Exception``，
  **从不写平台冷却**。上层 ``except DataFetchError: break`` 一吞，``main.py``
  会认为采集跑通了，于是 `clear_stale_cooldown` 把刚落的冷却清掉。
- ``search()`` 用的是通用 3 秒（``CRAWLER_MAX_SLEEP_SEC``），比 detail 档
  （12s+8s）还快 4 倍，是整条链路上最裸的一段。
- 每个请求都 ``get_web_id()`` 随机生成一次 webid；``common_params`` 里写死
  Chrome 125 / 2560×1440 / 8 核，与真实浏览器和 cookie 全都对不上。
- 夜间静默、搜索配额的入口只接了小红书。

这个文件锁住改造后的四类行为：
1. 拦截 → 落冷却 → 抛专用异常（一次性、可跨进程）。
2. 指纹参数来自浏览器，webid 会话内稳定，msToken 缺失时不发空串。
3. 搜索走专用节奏档，且有配额/夜间静默。
4. 滑块自动重试收敛，过不去就抛 ``CaptchaError``。
"""

import asyncio
import json
from datetime import datetime

import pytest

import config
from media_platform.douyin import client as dy_client_mod
from media_platform.douyin.client import DouYinClient
from media_platform.douyin.exception import (
    ABORT_EXCEPTIONS,
    CaptchaError,
    DataFetchError,
    DouYinAccountBlockedError,
    PlatformAccessError,
    RateLimitError,
    is_blocking,
)
from tools import crawl_pacing as cp
from tools import crawl_safety as cs
from tools.browser_fingerprint import BrowserFingerprint, DeviceProfile

# ---------------------------------------------------------------------------
# 1. 平台级间隔与冷却时长
# ---------------------------------------------------------------------------


def test_douyin_detail_and_search_use_different_pacing():
    """搜索档必须比 detail 档慢：搜索是主动去库里捞，比按 ID 取详情敏感得多。"""
    detail_base, detail_jitter = cp.compute_crawl_interval("dy")
    search_base, search_jitter = cp.compute_crawl_interval("dy", "search")
    assert (detail_base, detail_jitter) == (12.0, 8.0)
    assert search_base >= detail_base * 3
    assert search_jitter > detail_jitter


def test_douyin_pacing_keys_exist_in_config():
    """``getattr(config, key, default)`` 拼错键名不会报错，只会静默用通用值。"""
    for platform, (base_key, jitter_key) in cp._PLATFORM_PACING.items():
        assert hasattr(config, base_key), f"{platform} 缺少 {base_key}"
        assert hasattr(config, jitter_key), f"{platform} 缺少 {jitter_key}"
    for (platform, kind), (base_key, jitter_key) in cp._PACING_KINDS.items():
        assert hasattr(config, base_key), f"{platform}/{kind} 缺少 {base_key}"
        assert hasattr(config, jitter_key), f"{platform}/{kind} 缺少 {jitter_key}"


def test_douyin_search_keys_are_not_generic_fallback(monkeypatch):
    """抖音搜索不能退回 3 秒的通用值——那正是改造前的行为。"""
    monkeypatch.setattr(config, "ENABLE_SAFE_CRAWL_MODE", True)
    base, _ = cp.compute_crawl_interval("dy", "search")
    generic, _ = cp.compute_crawl_interval("", "")
    assert base >= generic * 10


def test_douyin_blocked_cooldown_is_account_scale():
    """抖音封账号，冷却要按小时算，不能是限流的 15 分钟。"""
    blocked = cp._cooldown_seconds(cp.PLATFORM_BLOCKED, "dy")
    rate_limited = cp._cooldown_seconds(cp.RATE_LIMITED, "dy")
    assert blocked >= 3600 * 4
    assert blocked > rate_limited * 10


def test_account_blocked_exception_is_classified_as_platform_blocked():
    """类名必须进 ``_BLOCKING_EXC_NAMES``。

    否则 "account blocked" 会先命中限流正则，把 6 小时冷却降级成 15 分钟。
    """
    assert "DouYinAccountBlockedError" in cp._BLOCKING_EXC_NAMES
    failure = cp.classify_failure(DouYinAccountBlockedError("account blocked"), platform="dy")
    assert failure.code == cp.PLATFORM_BLOCKED


def test_blocking_exceptions_tuple_is_complete():
    """``BLOCKING_EXCEPTIONS`` 决定落多长的冷却；``ABORT_EXCEPTIONS`` 决定停不停手。"""
    for exc_type in (DouYinAccountBlockedError, CaptchaError, PlatformAccessError):
        assert is_blocking(exc_type("x"))
    # 限流要停手，但不按"账号已异常"的 6 小时处理
    assert not is_blocking(RateLimitError("x"))
    assert issubclass(RateLimitError, ABORT_EXCEPTIONS)
    # 普通取数失败既不停批，也不落冷却：否则一次 NotFound 就整批作废
    assert not is_blocking(DataFetchError("x"))
    assert not issubclass(DataFetchError, ABORT_EXCEPTIONS)


# ---------------------------------------------------------------------------
# 2. 客户端：拦截 → 冷却 → 停手
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_state(tmp_path):
    cp.reset_cooldown_store(cp.CooldownStore(tmp_path / "cooldowns.json"))
    cs.reset_search_budget(cs.SearchBudget(tmp_path / "dy_search_budget.json", platform="dy"))
    yield
    cp.reset_cooldown_store(None)
    cs.reset_search_budget(None)


_EMPTY = object()


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, text=_EMPTY):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        # text=_EMPTY 表示"真的返回空字符串"；不传则按 payload 序列化
        self.text = json.dumps(self._payload) if text is _EMPTY else text

    def json(self):
        return self._payload

    def __repr__(self):
        # 默认 repr 带模块名（本文件名里有 "crawl_guard"），会被 classify_failure 误判
        return f"<Response [{self.status_code}]>"


class _FakeAsyncClient:
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
    monkeypatch.setattr(dy_client_mod, "make_impersonated_client", lambda **kw: _FakeAsyncClient(**kw))
    return _FakeAsyncClient


def _make_client(**kwargs) -> DouYinClient:
    kwargs.setdefault("headers", {"Cookie": "a=1", "User-Agent": "UA"})
    kwargs.setdefault("playwright_page", None)
    kwargs.setdefault("cookie_dict", {"a": "1"})
    return DouYinClient(**kwargs)


@pytest.mark.parametrize(
    "status,payload,text,expected",
    [
        (403, {"status_code": 8}, _EMPTY, PlatformAccessError),
        (429, {}, "too many", RateLimitError),
        (200, {}, "", DouYinAccountBlockedError),  # 空 body：最典型的"不给你数据"
        (200, {}, "blocked", DouYinAccountBlockedError),
        (200, {}, "<html><title>captcha</title></html>", CaptchaError),
        (200, {}, "<html><body>hello</body></html>", DouYinAccountBlockedError),
        (200, {"status_code": 100, "status_msg": "操作过于频繁"}, _EMPTY, RateLimitError),
        (200, {"status_code": 100, "status_msg": "请求不合法"}, _EMPTY, DataFetchError),
        (200, {"comments": [], "has_more": 0}, _EMPTY, None),  # 正常空页
    ],
)
def test_response_classification(isolated_state, status, payload, text, expected):
    client = _make_client()
    response = _FakeResponse(status, payload, text)
    classified = client._classify_response(response, "https://www.douyin.com/x")
    if expected is None:
        assert classified is None
    else:
        assert type(classified) is expected


def test_comment_body_words_do_not_trigger_block():
    """评论正文里出现"验证码""风控"是正常内容，不能据此判风控。"""
    client = _make_client()
    payload = {"comments": [{"text": "验证码怎么填？刚刚被风控了"}], "has_more": 1}
    assert client._classify_response(_FakeResponse(200, payload), "u") is None


def test_server_error_does_not_write_cooldown(isolated_state, fake_http):
    """5xx 是平台抖动，不是账号问题：不能落 6 小时账号冷却。"""
    fake_http.response_factory = lambda: _FakeResponse(502, {}, "bad gateway")
    client = _make_client()

    async def run():
        with pytest.raises(DataFetchError):
            await client.request("GET", "https://www.douyin.com/aweme/v1/web/comment/list/")

    asyncio.run(run())
    assert cp.platform_cooldown("dy") is None


def test_blocked_writes_platform_cooldown_and_raises(isolated_state, fake_http):
    fake_http.response_factory = lambda: _FakeResponse(200, {}, "")
    client = _make_client()

    async def run():
        with pytest.raises(DouYinAccountBlockedError):
            await client.request("GET", "https://www.douyin.com/aweme/v1/web/comment/list/")

    asyncio.run(run())

    cooldown = cp.platform_cooldown("dy")
    assert cooldown is not None
    assert cooldown["code"] == cp.PLATFORM_BLOCKED
    assert cooldown["retry_after_seconds"] >= 3600 * 4
    assert fake_http.calls == 1, "撞拦截后应立刻停手，不该重试"


def test_cooldown_is_visible_from_a_new_store(isolated_state, fake_http):
    """跨进程可见：新进程第一件事是 ``ensure_platform_available``。"""
    fake_http.response_factory = lambda: _FakeResponse(403, {"status_code": 8}, "")
    client = _make_client()

    async def run():
        with pytest.raises(PlatformAccessError):
            await client.request("GET", "https://www.douyin.com/aweme/v1/web/comment/list/")

    asyncio.run(run())

    fresh_store = cp.CooldownStore(cp.cooldown_store().path)
    cp.reset_cooldown_store(fresh_store)
    with pytest.raises(cp.CrawlBlocked):
        cp.ensure_platform_available("dy")


def test_network_failure_does_not_leak_unbound_local(isolated_state, fake_http):
    """旧代码 ``response`` 未定义就进 except，会抛 UnboundLocalError 掩盖真因。"""

    class _Boom(_FakeAsyncClient):
        async def request(self, method, url, **kwargs):
            raise RuntimeError("connection reset")

    import media_platform.douyin.client as mod

    original = mod.make_impersonated_client
    mod.make_impersonated_client = lambda **kw: _Boom(**kw)
    try:
        client = _make_client()

        async def run():
            with pytest.raises(DataFetchError) as excinfo:
                await client.request("GET", "https://www.douyin.com/x")
            return excinfo

        excinfo = asyncio.run(run())
        assert "connection reset" in str(excinfo.value)
    finally:
        mod.make_impersonated_client = original


# ---------------------------------------------------------------------------
# 3. 指纹 / webid / msToken
# ---------------------------------------------------------------------------


def test_common_params_come_from_browser_fingerprint():
    """参数必须来自指纹对象，而不是写死的 Chrome 125 / 2560×1440。"""
    fingerprint = BrowserFingerprint(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
        sec_ch_ua='"Chromium";v="157", "Not.A/Brand";v="99"',
        sec_ch_ua_platform='"macOS"',
    )
    device = DeviceProfile(screen_width=1920, screen_height=1080, hardware_concurrency=10, device_memory=16)

    async def run():
        client = _make_client(fingerprint=fingerprint, device_profile=device, webid="1234567890")
        params = {"cursor": "0"}
        await client._DouYinClient__process_req_params("/aweme/v1/web/comment/list/", params)
        return params

    params = asyncio.run(run())
    assert params["browser_version"] == "157.0.0.0"
    assert params["engine_version"] == "157.0"
    assert params["screen_width"] == "1920"
    assert params["screen_height"] == "1080"
    assert params["cpu_core_num"] == "10"
    assert params["device_memory"] == "16"


def test_webid_is_stable_across_requests():
    """同一会话每个请求都换 webid = 每秒换一台设备，是最强的机器特征之一。"""

    async def run():
        client = _make_client(webid="777888999")
        seen = []
        for _ in range(3):
            params = {"cursor": "0"}
            await client._DouYinClient__process_req_params("/aweme/v1/web/comment/list/", params)
            seen.append(params["webid"])
        return seen

    seen = asyncio.run(run())
    assert seen == ["777888999"] * 3


def test_ms_token_missing_is_omitted_not_none_string():
    """``localStorage.get("xmst")`` 为 None 时，旧代码会发出字面量 ``msToken=None``。"""

    class _Page:
        async def evaluate(self, script):
            return {}

    async def run():
        client = _make_client(playwright_page=_Page(), webid="1")
        params = {"cursor": "0"}
        await client._DouYinClient__process_req_params("/aweme/v1/web/comment/list/", params)
        return params

    params = asyncio.run(run())
    assert "msToken" not in params, f"不该把空 token 发出去：{params.get('msToken')!r}"


# ---------------------------------------------------------------------------
# 4. 搜索：节奏档 + 配额 + 夜间静默接线
# ---------------------------------------------------------------------------


class TestSearchEntryIsWired:
    """用 ``inspect.getsource`` 断言入口真的调了这些守卫。

    这类接线用行为测试很难覆盖（要跑起整个 crawler），但"忘了接"恰恰是
    最贵的错误：2026-11-11 的小红书事故就是写好了防护却没接进主路径。
    """

    def test_search_uses_budget_and_quiet_hours(self):
        import inspect

        from media_platform.douyin import core as dy_core

        source = inspect.getsource(dy_core.DouYinCrawler.search)
        assert "ensure_not_quiet_hours(platform=\"dy\")" in source
        assert "ensure_batch_allowed(" in source
        assert 'kind="search"' in source
        assert "search_budget(platform=\"dy\").consume(1)" in source

    def test_search_rethrows_blocker(self):
        """拦截异常必须抛回去：吞掉后 main.py 会当作跑通并清掉冷却。"""
        import inspect

        from media_platform.douyin import core as dy_core

        source = inspect.getsource(dy_core.DouYinCrawler.search)
        assert "raise blocker" in source
        assert "except ABORT_EXCEPTIONS" in source

    def test_pagination_loops_rethrow_blocking_exceptions(self):
        import inspect

        from media_platform.douyin import client as dy_client

        source = inspect.getsource(dy_client.DouYinClient.get_aweme_all_comments)
        assert "ABORT_EXCEPTIONS" in source, "翻页循环会把账号级异常吞成 break"
        # get_all_user_aweme_posts 不捕获异常（直接冒泡），也是正确的一种：
        # 只要它没有 `except Exception` 把拦截吞掉。
        posts_source = inspect.getsource(dy_client.DouYinClient.get_all_user_aweme_posts)
        assert "except" not in posts_source, "创作者作品循环不该吞异常"

    def test_detail_and_comments_rethrow_blocking(self):
        import inspect

        from media_platform.douyin import core as dy_core

        for method in (dy_core.DouYinCrawler.get_aweme_detail, dy_core.DouYinCrawler.get_comments):
            source = inspect.getsource(method)
            assert "except ABORT_EXCEPTIONS" in source, f"{method.__name__} 会把账号级异常吞掉"

    def test_main_applies_quiet_hours_to_all_platforms(self):
        import inspect

        import main as main_mod

        source = inspect.getsource(main_mod.main)
        assert "ensure_not_quiet_hours(platform=platform)" in source


def test_search_budget_has_separate_file_per_platform(tmp_path):
    """小红书与抖音的额度必须分开记账：共用一个文件等于互相扣减。"""
    dy_budget = cs.SearchBudget(tmp_path / "dy_search_budget.json", platform="dy")
    cs.reset_search_budget(dy_budget)
    try:
        assert dy_budget.path.name == "dy_search_budget.json"
        assert cs.daily_search_limit("dy") == config.DY_SEARCH_DAILY_LIMIT
        assert cs.max_keywords_per_batch("dy") == config.DY_MAX_KEYWORDS_PER_BATCH
    finally:
        cs.reset_search_budget(None)


def test_search_budget_exhaustion_raises_with_retry_after(tmp_path):
    budget = cs.SearchBudget(tmp_path / "dy_search_budget.json", platform="dy")
    cs.reset_search_budget(budget)
    try:
        for _ in range(cs.daily_search_limit("dy")):
            budget.consume(1)
        with pytest.raises(cs.SearchBudgetExceeded) as excinfo:
            cs.ensure_batch_allowed(1, platform="dy")
        assert excinfo.value.retry_after_seconds > 0
    finally:
        cs.reset_search_budget(None)


def test_douyin_quiet_hours_window(monkeypatch):
    now = datetime.now()
    night = datetime(now.year, now.month, now.day, 3, 0).timestamp()
    day = datetime(now.year, now.month, now.day, 15, 0).timestamp()
    assert cs.in_quiet_hours(night, platform="dy") is True
    assert cs.in_quiet_hours(day, platform="dy") is False
    with pytest.raises(cs.QuietHoursActive):
        cs.ensure_not_quiet_hours(night, platform="dy")
    cs.ensure_not_quiet_hours(day, platform="dy")


def test_quiet_hours_can_be_disabled_for_douyin(monkeypatch):
    monkeypatch.setattr(config, "DY_QUIET_HOURS_START", 0, raising=False)
    monkeypatch.setattr(config, "DY_QUIET_HOURS_END", 0, raising=False)
    now = datetime.now()
    night = datetime(now.year, now.month, now.day, 3, 0).timestamp()
    assert cs.in_quiet_hours(night, platform="dy") is False


# ---------------------------------------------------------------------------
# 5. 登录滑块：收敛而不是加刑
# ---------------------------------------------------------------------------


def test_slider_attempts_are_bounded():
    """对已被标记的账号反复刷滑块是加刑，不是解题。"""
    assert config.DY_SLIDER_MAX_ATTEMPTS <= 5
    assert config.DY_SLIDER_MAX_REFRESH <= 2


def test_slider_failure_raises_captcha_error():
    """滑块过不去必须抛 CaptchaError（→ 平台冷却），而不是 RuntimeError。"""
    from media_platform.douyin.login import DouYinLogin

    class _Page:
        async def wait_for_selector(self, **kwargs):
            return object()  # 每次都"看得到滑块"

        async def content(self):
            return "操作过慢，请重新操作"

        async def click(self, selector=None):
            return None

    class _Ctx:
        pages = []

        async def cookies(self):
            return []

    login = DouYinLogin(
        login_type="qrcode",
        browser_context=_Ctx(),
        context_page=_Page(),
    )
    # move_slider 在这里没有真实页面，必然失败；重要的是失败到底时抛什么
    with pytest.raises(CaptchaError):
        asyncio.run(login.check_page_display_slider(move_step=3, slider_level="hard"))


def test_login_retry_is_not_one_per_second_forever():
    """600 次 × 1s 的登录态轮询本身就是机器特征。"""
    import inspect

    from media_platform.douyin import login as dy_login

    source = inspect.getsource(dy_login.DouYinLogin.check_login_state)
    assert "600" not in source


# ---------------------------------------------------------------------------
# 6. TLS 指纹层
# ---------------------------------------------------------------------------


class TestTlsImpersonation:
    def test_impersonated_client_maps_follow_redirects(self):
        """httpx 的 ``follow_redirects`` 语义必须被适配到 curl_cffi 的 ``allow_redirects``。

        媒体下载与短链解析都依赖这一条；映射错了会让 302 变成"下载到登录页"。
        """
        import inspect

        from tools import httpx_util

        source = inspect.getsource(httpx_util._AdaptedSession.request)
        assert "allow_redirects" in source
        assert "follow_redirects" in source

    def test_adapted_response_has_reason_phrase(self):
        """curl_cffi 的 Response 没有 ``reason_phrase``，但我们下游在用。"""
        from tools.httpx_util import _AdaptedResponse

        class _Raw:
            status_code = 200
            text = "ok"
            content = b"ok"
            headers = {}
            url = "https://example.com"

            def json(self):
                return {}

        adapted = _AdaptedResponse(_Raw())
        assert adapted.reason_phrase == "OK"
        assert adapted.status_code == 200

    def test_make_async_client_stays_httpx(self):
        """``make_async_client`` 有 20 个调用点（CDN/二维码/短链/代理探活），
        必须继续返回 httpx.AsyncClient，不能被 TLS 改造带偏。"""
        import httpx

        from tools.httpx_util import make_async_client

        async def run():
            client = make_async_client()
            try:
                assert isinstance(client, httpx.AsyncClient)
            finally:
                await client.aclose()

        asyncio.run(run())

    def test_falls_back_when_curl_cffi_missing(self, monkeypatch):
        """curl_cffi 不可用时退回 httpx 并告警，而不是直接崩。"""
        import httpx

        from tools import httpx_util

        monkeypatch.setattr(httpx_util, "_CURL_AVAILABLE", False)
        monkeypatch.setattr(httpx_util, "_curl_session_cls", None)

        async def run():
            client = httpx_util.make_impersonated_client()
            try:
                assert isinstance(client, httpx.AsyncClient)
            finally:
                await client.aclose()

        asyncio.run(run())


# ---------------------------------------------------------------------------
# 5. 超时：业务接口与媒体下载分开
# ---------------------------------------------------------------------------


class TestTimeouts:
    """改造前 ``__init__(timeout=60)`` 是硬编码的：业务接口挂住时也要占着浏览器
    整整一分钟，期间 pacer 无法往下走；而那个 60 本来只是给视频下载留的。"""

    def test_business_timeout_comes_from_config(self):
        client = _make_client()
        assert client.timeout == float(config.DY_REQUEST_TIMEOUT_SEC)

    def test_media_timeout_has_floor(self):
        """媒体超时不能低于下限：50MB 视频在慢网络上 20s 下不来。"""
        client = _make_client()
        assert client.media_timeout == dy_client_mod.MEDIA_MIN_TIMEOUT_SEC
        assert client.media_timeout > client.timeout

    def test_explicit_timeout_still_respected(self):
        """显式传值优先：调用方明确知道自己在做什么时不该被配置覆盖。"""
        client = _make_client(timeout=5)
        assert client.timeout == 5.0
        # 但媒体下限仍然兜住——否则显式传个小值就会把视频下载弄坏。
        assert client.media_timeout == dy_client_mod.MEDIA_MIN_TIMEOUT_SEC

    def test_media_download_uses_media_timeout(self, fake_http, monkeypatch):
        """``get_aweme_media`` 必须用 media_timeout，别被业务接口的短超时连坐。"""
        seen = {}

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def request(self, method, url, **kwargs):
                seen.update(kwargs)

                class _Resp:
                    status_code = 200
                    reason_phrase = "OK"
                    content = b"data"
                    text = ""

                    def raise_for_status(self):
                        return None

                return _Resp()

        monkeypatch.setattr(dy_client_mod, "make_async_client", lambda **kw: _Client())
        client = _make_client()
        asyncio.run(client.get_aweme_media("https://v3-web.douyinvod.com/x.mp4"))
        assert seen["timeout"] == client.media_timeout
